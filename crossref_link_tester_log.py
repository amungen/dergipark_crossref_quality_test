import argparse
import re
import sys
import json
from typing import Tuple, List, Dict, Any
from pathlib import Path

import requests

CROSSREF_API_TEMPLATE = (
    "https://api.crossref.org/journals/{issn}/works"
    "?select=DOI,prefix,title,publisher,type,resource,URL,ISSN,created,container-title"
    "&rows=100&sort=created&order=asc"
)
UA = "PiriLinkTester/1.0 (mailto:you@example.com)"
TIMEOUT = 5

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

def check_url(url: str, title_norm: str) -> Tuple[int, bool, str, bool]:
    """
    URL'e GET atar ve döndürür:
      status_code,
      title içeriyor mu (bool),
      bilgi mesajı,
      'erişilebilir' mi (HTTP 200 ve body’de '404 not found' YOK)
    """
    if not url:
        return 0, False, "boş URL", False
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": UA},
            allow_redirects=True,
            timeout=TIMEOUT,
            verify=True,
        )
        status = resp.status_code
        if status == 200:
            text_norm = normalize_text(resp.text)
            if "404 not found" in text_norm:
                return 404, False, "200 ama sayfada '404 Not Found' var ❌", False
            contains_title = title_norm in text_norm if title_norm else False
            return status, contains_title, "200 OK", True
        else:
            return status, False, f"HTTP {status}", False
    except requests.RequestException as e:
        return 0, False, f"Bağlantı hatası: {e}", False

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

def main():
    parser = argparse.ArgumentParser(description="Crossref link testi (ISSN bazlı) → JSONL summary & detail.")
    parser.add_argument("--issn", default="2148-5704", help="ISSN (ör. 2148-5704)")
    parser.add_argument("--summary", default="summary.jsonl", help="Özet JSONL dosyası")
    parser.add_argument("--detail", default="detail.jsonl", help="Detay JSONL dosyası")
    args = parser.parse_args()

    api_url = CROSSREF_API_TEMPLATE.format(issn=args.issn)
    detail_path = Path(args.detail)
    summary_path = Path(args.summary)

    # Crossref verisini çek
    try:
        r = requests.get(api_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        msg = f"[ERR] Crossref API hatası: {e}"
        print(msg)
        # hata da detail.jsonl'a yazılsın
        append_jsonl(detail_path, {"level": "ERROR", "issn": args.issn, "msg": msg, "api_url": api_url})
        sys.exit(1)

    data = r.json()
    items = (data.get("message") or {}).get("items") or []
    total = len(items)

    # Dergi adı tespiti
    journal_name = "Unknown Journal"
    if items:
        it0 = items[0]
        ct = it0.get("container-title") or []
        if ct and isinstance(ct, list) and ct[0]:
            journal_name = ct[0].strip()
        elif (it0.get("publisher") or "").strip():
            journal_name = it0.get("publisher").strip()

    # Summary’de aynı dergi varsa atla
    existing_names = read_jsonl_names(summary_path)
    if journal_name.strip().lower() in existing_names:
        msg = f"[INFO] summary.jsonl içinde '{journal_name}' zaten var; yeni kayıt yazılmadı."
        print(msg)
        append_jsonl(detail_path, {"level": "INFO", "issn": args.issn, "journal_name": journal_name, "msg": msg})
        sys.exit(0)

    # Sayaçlar
    accessible_cnt = 0
    correct_cnt = 0

    # Her kayıt için dene ve detail.jsonl’a yaz
    append_jsonl(detail_path, {
        "level": "INFO",
        "event": "start",
        "journal_name": journal_name,
        "issn": args.issn,
        "api_url": api_url,
        "total": total
    })

    for i, it in enumerate(items, 1):
        doi = (it.get("DOI") or "").strip()
        title_list = it.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        title_norm = normalize_text(title)

        # Aday URL sırası
        try:
            resource_primary_url = (
                ((it.get("resource") or {}).get("primary") or {}).get("URL") or ""
            ).strip()
        except Exception:
            resource_primary_url = ""

        crossref_url = (it.get("URL") or "").strip()
        doi_url = build_doi_url(doi)

        candidates = [
            ("resource.primary.URL", resource_primary_url),
            ("URL", crossref_url),
            ("DOI", doi_url),
        ]

        passed = False
        this_item_accessible = False
        trials: List[Dict[str, Any]] = []

        for label, url in candidates:
            status, has_title, info, is_accessible = check_url(url, title_norm)
            trials.append({
                "label": label,
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
                break  # sıralı strateji: ilk başarılıda dur

        if this_item_accessible:
            accessible_cnt += 1
        if passed:
            correct_cnt += 1

        # detail.jsonl satırı
        append_jsonl(detail_path, {
            "journal_name": journal_name,
            "issn": args.issn,
            "idx": i,
            "total": total,
            "doi": doi,
            "title": title,
            "passed": passed,           # 200 + title var
            "accessible": this_item_accessible,  # en az bir geçerli 200
            "trials": trials
        })

    # summary.jsonl satırı
    append_jsonl(summary_path, {
        "journal_name": journal_name,
        "issn": args.issn,
        "total": total,
        "accessible": accessible_cnt,
        "correct": correct_cnt
    })

    print(f"[DONE] {journal_name} | ISSN={args.issn} | total={total} | accessible={accessible_cnt} | correct={correct_cnt}")
    print(f"[INFO] summary → {summary_path}")
    print(f"[INFO] detail  → {detail_path}")

if __name__ == "__main__":
    main()
