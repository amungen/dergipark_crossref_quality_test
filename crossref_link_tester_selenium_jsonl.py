import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import time
from io import BytesIO

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# ====== Crossref & Genel Ayarlar ======
CROSSREF_API_TEMPLATE = (
    "https://api.crossref.org/journals/{issn}/works"
    "?select=DOI,prefix,title,publisher,type,resource,URL,ISSN,created,container-title"
    "&rows=50&sort=created&order=asc"
)
UA = "AcademicLinkTester/1.0"
TIMEOUT = 5


# ====== Selenium Driver ======
def build_driver(detach=True) -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=tr-TR")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if detach:
        opts.add_experimental_option("detach", True)
    # HTTP durumlarını + mimeType'ı performance log'tan okumak için
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.set_page_load_timeout(TIMEOUT)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass
    return driver


# ====== Yardımcılar ======
def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl_names(path: Path) -> Set[str]:
    """summary.jsonl içindeki journal_name’leri (küçük harf) set olarak oku."""
    names: Set[str] = set()
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


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Tercihen pdfminer.six ile PDF metni çıkar. Yoksa kaba fallback:
    latin-1 decode (errors='ignore') ile byte içinden düz metin ayıklamaya çalış.
    """
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(pdf_bytes)) or ""
        return text
    except Exception:
        # pdfminer yoksa/başarısızsa kaba fallback
        try:
            return pdf_bytes.decode("latin-1", errors="ignore")
        except Exception:
            return ""


def fetch_pdf_text(url: str) -> Tuple[int, str]:
    """
    PDF içeriğini indirip metne çevir. (status_code, text_norm) döndür.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": UA},
            allow_redirects=True,
            timeout=15,
            verify=True,
        )
        status = resp.status_code
        if status != 200 or not resp.content:
            return status, ""
        # Bazı sunucular yanlış content-type verebilir; doğrudan PDF bytes'tan dene
        text = extract_text_from_pdf_bytes(resp.content)
        return status, normalize_text(text)
    except requests.RequestException:
        return 0, ""


def get_http_status_source_mime(driver: webdriver.Chrome, url: str) -> Tuple[int, str, str, str]:
    """
    URL'e driver.get; performance loglarından Document status + mimeType'ı bul.
    Dönüş: (status_code_or_0, page_source, final_url, mimeType_or_empty)
    """
    if not url:
        return 0, "", "", ""
    try:
        # Önceki logları temizle
        try:
            _ = driver.get_log("performance")
        except Exception:
            pass

        driver.get(url)

        status_code = 0
        mime_type = ""
        final_url = driver.current_url or url

        try:
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                except Exception:
                    continue
                if msg.get("method") == "Network.responseReceived":
                    params = msg.get("params", {})
                    if params.get("type") == "Document":
                        resp = params.get("response", {})
                        resp_url = resp.get("url") or ""
                        code = int(resp.get("status", 0))
                        mtype = resp.get("mimeType") or ""
                        # final_url ile eşleşeni tercih et; yoksa son görüleni al
                        if resp_url == final_url:
                            status_code = code
                            mime_type = mtype or mime_type
                        else:
                            status_code = code
                            mime_type = mtype or mime_type
        except Exception:
            pass

        html = driver.page_source or ""
        return status_code, html, final_url, (mime_type or "")
    except Exception:
        return 0, "", "", ""


def is_pdf_mime_or_url(mime_type: str, url: str) -> bool:
    mime_type = (mime_type or "").lower()
    url_l = (url or "").lower()
    return ("application/pdf" in mime_type) or url_l.endswith(".pdf")


def check_url_selenium(driver: webdriver.Chrome, url: str, title_norm: str) -> Tuple[int, bool, str, bool]:
    """
    Selenium ile URL'i aç ve değerlendir:
      - HTTP status,
      - başlık var mı,
      - info,
      - erişilebilir mi (200 + body '404 not found' değil).
    PDF ise bytes indirip PDF metninde başlık ara.
    """
    if not url:
        return 0, False, "boş URL", False

    status, html, final_url, mime_type = get_http_status_source_mime(driver, url)

    # Eğer PDF ise: requests ile indir → metni çıkar → başlık ara
    if is_pdf_mime_or_url(mime_type, final_url):
        pdf_status, pdf_text_norm = fetch_pdf_text(final_url)
        # status belirleme mantığı
        st = pdf_status if pdf_status != 0 else (status if status != 0 else 200)
        if st == 200:
            # PDF'te '404 not found' beklenmez ama yine de kontrol edebiliriz
            if "404 not found" in pdf_text_norm:
                return 404, False, "PDF 200 ama içerikte '404 not found' var ❌", False
            has_title = title_norm in pdf_text_norm if title_norm else False
            return 200, has_title, "200 OK (PDF)", True
        else:
            return st, False, f"HTTP {st} (PDF)", False

    # HTML benzeri: eski mantık
    if not html:
        return (404 if status == 0 else status), False, "İçerik boş / yüklenemedi", False

    text_norm = normalize_text(html)
    if status == 0:
        status = 404 if "404 not found" in text_norm else 200
    if status == 200:
        if "404 not found" in text_norm:
            return 404, False, "200 ama body 404 içeriyor ❌", False
        has_title = title_norm in text_norm if title_norm else False
        return 200, has_title, "200 OK", True
    return status, False, f"HTTP {status}", False


def build_doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    return f"https://doi.org/{doi}" if doi else ""


# ====== Asıl iş: tek ISSN işleme ======
def process_one_issn(
    driver: webdriver.Chrome,
    issn: str,
    summary_path: Path,
    detail_path: Path,
    dp_journal_name: str = None
) -> None:
    """Bir ISSN için Crossref -> Selenium doğrulama -> summary/detail JSONL yaz."""
    api_url = CROSSREF_API_TEMPLATE.format(issn=issn)
    try:
        r = requests.get(api_url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        msg = f"[ERR] Crossref API hatası: {e}"
        print(msg)
        append_jsonl(detail_path, {"level": "ERROR", "issn": issn, "msg": msg, "api_url": api_url,
                                   "dp_journal_name": dp_journal_name})
        return

    data = r.json()
    items = (data.get("message") or {}).get("items") or []
    total = len(items)

    # Crossref'ten dergi adı
    journal_name = "Unknown Journal"
    if items:
        it0 = items[0]
        ct = it0.get("container-title") or []
        if ct and isinstance(ct, list) and ct[0]:
            journal_name = (ct[0] or "").strip()
        elif (it0.get("publisher") or "").strip():
            journal_name = (it0.get("publisher") or "").strip()

    # summary.jsonl’de aynı journal_name varsa atla (mevcut davranışı koru)
    existing_names = read_jsonl_names(summary_path)
    if journal_name.strip().lower() in existing_names:
        info = f"[INFO] summary.jsonl içinde '{journal_name}' zaten var; atlandı."
        print(info)
        append_jsonl(detail_path, {
            "level": "INFO", "event": "skip-existing",
            "issn": issn, "journal_name": journal_name,
            "dp_journal_name": dp_journal_name, "msg": info
        })
        return

    accessible_cnt = 0
    correct_cnt = 0

    append_jsonl(detail_path, {
        "level": "INFO", "event": "start",
        "issn": issn,
        "journal_name": journal_name,
        "dp_journal_name": dp_journal_name,
        "api_url": api_url,
        "total": total
    })

    for i, it in enumerate(items, 1):
        doi = (it.get("DOI") or "").strip()
        title_list = it.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        title_norm = normalize_text(title)

        # Aday URL'ler (öncelik sırası)
        try:
            resource_primary_url = (
                ((it.get("resource") or {}).get("primary") or {}).get("URL") or ""
            ).strip()
        except Exception:
            resource_primary_url = ""
        crossref_url = (it.get("URL") or "").strip()
        doi_url = build_doi_url(doi)

        raw_candidates: List[Tuple[str, str]] = [
            ("resource.primary.URL", resource_primary_url),
            ("URL", crossref_url),
            ("DOI", doi_url),
        ]

        # Dedup: aynı URL tek kez
        unique_urls: List[str] = []
        labels_for_url: Dict[str, List[str]] = {}
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
        trials: List[Dict[str, Any]] = []

        for url in unique_urls:
            primary_label = labels_for_url[url][0]
            aliases = labels_for_url[url][1:]
            status, has_title, info, is_accessible = check_url_selenium(driver, url, title_norm)
            trials.append({
                "label": primary_label,
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
                break  # ilk başarılıda dur
            # nazik gecikme: hedef siteleri yormamak için
            time.sleep(0.5)

        if this_item_accessible:
            accessible_cnt += 1
        if passed:
            correct_cnt += 1

        append_jsonl(detail_path, {
            "journal_name": journal_name,
            "dp_journal_name": dp_journal_name,
            "issn": issn,
            "idx": i,
            "total": total,
            "doi": doi,
            "title": title,
            "passed": passed,
            "accessible": this_item_accessible,
            "trials": trials
        })

    # Özet satırı
    append_jsonl(summary_path, {
        "journal_name": journal_name,         # Crossref'teki isim
        "dp_journal_name": dp_journal_name,   # DergiPark'taki isim (referans)
        "issn": issn,
        "total": total,
        "accessible": accessible_cnt,
        "correct": correct_cnt,
        "fetcher": "selenium"
    })

    print(f"[DONE] {journal_name} | ISSN={issn} | total={total} | accessible={accessible_cnt} | correct={correct_cnt}")


# ====== Toplu: DergiPark JSON'unu oku ve sırayla ISSN/eISSN ile çalıştır ======
def main():
    parser = argparse.ArgumentParser(
        description="DergiPark JSON → Crossref Selenium toplu doğrulama (PDF destekli)"
    )
    parser.add_argument("--input", default="dergipark_journals_detail.json",
                        help="DergiPark dergi listesi JSON (array)")
    parser.add_argument("--summary", default="summary.jsonl", help="Özet JSONL dosyası")
    parser.add_argument("--detail", default="detail.jsonl", help="Detay JSONL dosyası")
    parser.add_argument("--max", type=int, default=0, help="İlk N dergi ile sınırla (0=hepsi)")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[ERR] Girdi dosyası yok: {in_path.resolve()}")
        sys.exit(1)

    try:
        journals = json.loads(in_path.read_text(encoding="utf-8"))
        if not isinstance(journals, list):
            raise ValueError("Girdi JSON bir liste (array) olmalı.")
    except Exception as e:
        print(f"[ERR] JSON okunamadı: {e}")
        sys.exit(1)

    summary_path = Path(args.summary)
    detail_path = Path(args.detail)

    # Tek pencere Selenium
    driver = build_driver(detach=True)
    START_INDEX = 2162
    processed_issns: Set[str] = set()
    total_cnt = 0
    for idx, j in enumerate(journals, start=1):
        if args.max and total_cnt >= args.max:
            break
        if idx < START_INDEX:
            continue
            
        dp_name = (j.get("journal_name") or "").strip()
        issn = (j.get("issn") or "").strip()
        eissn = (j.get("eissn") or "").strip()

        chosen_issn = issn if issn else eissn
        if not chosen_issn:
            info = f"[SKIP] ISSN ve eISSN yok: {dp_name}"
            print(info)
            append_jsonl(detail_path, {"level": "WARN", "event": "skip-no-issn",
                                       "dp_journal_name": dp_name})
            continue

        if chosen_issn in processed_issns:
            info = f"[SKIP] Aynı ISSN tekrar: {chosen_issn} ({dp_name})"
            print(info)
            append_jsonl(detail_path, {"level": "INFO", "event": "skip-dup-issn",
                                       "issn": chosen_issn, "dp_journal_name": dp_name})
            continue

        print(f"[RUN] {idx}/{len(journals)}  {dp_name}  → ISSN={chosen_issn}")
        process_one_issn(driver, chosen_issn, summary_path, detail_path, dp_journal_name=dp_name)
        processed_issns.add(chosen_issn)
        total_cnt += 1

    input("Tarayıcı açık. Kapatmak için Enter'a basın...")
    driver.quit()


if __name__ == "__main__":
    main()
