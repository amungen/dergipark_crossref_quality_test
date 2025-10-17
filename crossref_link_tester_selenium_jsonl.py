import argparse
import re
import sys
import json
from typing import Tuple, List, Dict, Any
from pathlib import Path
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

CROSSREF_API_TEMPLATE = (
    "https://api.crossref.org/journals/{issn}/works"
    "?select=DOI,prefix,title,publisher,type,resource,URL,ISSN,created,container-title"
    "&rows=100&sort=created&order=asc"
)

UA = "PiriLinkTester/1.0 (mailto:you@example.com)"
TIMEOUT = 15


# ---------------- Selenium Driver ----------------
def build_driver():
    opts = Options()
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=tr-TR")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # pencere kapanmasın
    opts.add_experimental_option("detach", True)
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.set_page_load_timeout(TIMEOUT)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass
    return driver


# ---------------- Yardımcı fonksiyonlar ----------------
def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def check_url_selenium(driver, url: str, title_norm: str) -> Tuple[int, bool, str, bool]:
    """
    Selenium ile URL'e git → status_code, title var mı, info, erişilebilir mi
    """
    if not url:
        return 0, False, "boş URL", False

    status = 0
    try:
        driver.get(url)
        # --- Status code'u performance log'tan almayı dene ---
        logs = driver.get_log("performance")
        for entry in logs:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") == "Network.responseReceived":
                response = msg.get("params", {}).get("response", {})
                if response.get("url") == url or url in response.get("url", ""):
                    status = response.get("status", 0)
                    break

        # --- HTML içeriğini al ---
        html = driver.page_source
        text_norm = normalize_text(html)

        # Eğer status bulunamadıysa içerikten tahmin
        if status == 0:
            if "404 not found" in text_norm:
                status = 404
            else:
                status = 200

        if status == 200:
            if "404 not found" in text_norm:
                return 404, False, "200 ama body 404 içeriyor ❌", False
            has_title = title_norm in text_norm if title_norm else False
            return 200, has_title, "200 OK", True
        else:
            return status, False, f"HTTP {status}", False

    except Exception as e:
        return 0, False, f"Hata: {e}", False


def build_doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    if not doi:
        return ""
    return f"https://doi.org/{doi}"


def read_jsonl_names(path: Path) -> set:
    """summary.jsonl içindeki journal_name’leri set olarak oku (varsa)."""
    names = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    name = (obj.get("journal_name") or "").strip()
                    if name:
                        names.add(name.lower())
                except json.JSONDecodeError:
                    continue
    return names


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------- Ana akış ----------------
def main():
    parser = argparse.ArgumentParser(description="Crossref link testi (ISSN bazlı) → Selenium + JSONL")
    parser.add_argument("--issn", default="2148-5704", help="ISSN")
    parser.add_argument("--summary", default="summary.jsonl", help="Özet JSONL dosyası")
    parser.add_argument("--detail", default="detail.jsonl", help="Detay JSONL dosyası")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    detail_path = Path(args.detail)

    # API'den makale verisi çek
    import requests
    api_url = CROSSREF_API_TEMPLATE.format(issn=args.issn)
    try:
        r = requests.get(api_url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        msg = f"[ERR] Crossref API hatası: {e}"
        print(msg)
        append_jsonl(detail_path, {"level": "ERROR", "issn": args.issn, "msg": msg})
        sys.exit(1)

    data = r.json()
    items = (data.get("message") or {}).get("items") or []
    total = len(items)

    # Dergi adı
    journal_name = "Unknown Journal"
    if items:
        it0 = items[0]
        ct = it0.get("container-title") or []
        if ct and ct[0]:
            journal_name = ct[0].strip()
        elif (it0.get("publisher") or "").strip():
            journal_name = it0.get("publisher").strip()

    # summary'de varsa atla
    if journal_name.strip().lower() in read_jsonl_names(summary_path):
        print(f"[INFO] {journal_name} zaten summary.jsonl içinde.")
        sys.exit(0)

    driver = build_driver()

    accessible_cnt = 0
    correct_cnt = 0

    append_jsonl(detail_path, {
        "level": "INFO",
        "event": "start",
        "journal_name": journal_name,
        "issn": args.issn,
        "total": total
    })

    for i, it in enumerate(items, 1):
        doi = (it.get("DOI") or "").strip()
        title_list = it.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        title_norm = normalize_text(title)

        # URL adayları
        resource_primary_url = (((it.get("resource") or {}).get("primary") or {}).get("URL") or "").strip()
        crossref_url = (it.get("URL") or "").strip()
        doi_url = build_doi_url(doi)

        raw_candidates = [
            ("resource.primary.URL", resource_primary_url),
            ("URL", crossref_url),
            ("DOI", doi_url)
        ]

        # dedup
        unique_urls = []
        labels_for_url = {}
        for label, url in raw_candidates:
            if not url:
                continue
            if url not in labels_for_url:
                labels_for_url[url] = [label]
                unique_urls.append(url)
            else:
                labels_for_url[url].append(label)

        passed = False
        this_item_accessible = False
        trials = []

        for url in unique_urls:
            label = labels_for_url[url][0]
            aliases = labels_for_url[url][1:]
            status, has_title, info, is_accessible = check_url_selenium(driver, url, title_norm)
            trials.append({
                "label": label,
                "aliases": aliases,
                "url": url,
                "status": status,
                "has_title": has_title,
                "is_accessible": is_accessible,
                "info": info
            })
            if is_accessible:
                this_item_accessible = True
            if status == 200 and has_title:
                passed = True
                break

        if this_item_accessible:
            accessible_cnt += 1
        if passed:
            correct_cnt += 1

        append_jsonl(detail_path, {
            "journal_name": journal_name,
            "issn": args.issn,
            "idx": i,
            "total": total,
            "doi": doi,
            "title": title,
            "passed": passed,
            "accessible": this_item_accessible,
            "trials": trials
        })

    append_jsonl(summary_path, {
        "journal_name": journal_name,
        "issn": args.issn,
        "total": total,
        "accessible": accessible_cnt,
        "correct": correct_cnt
    })

    print(f"[DONE] {journal_name} | total={total} | accessible={accessible_cnt} | correct={correct_cnt}")
    print(f"[INFO] summary → {summary_path}")
    print(f"[INFO] detail  → {detail_path}")

    # pencereyi kapatmadan bekle
    input("Tarayıcı açık. Kapatmak için Enter'a basın...")
    driver.quit()


if __name__ == "__main__":
    main()
