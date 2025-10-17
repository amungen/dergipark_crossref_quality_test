import argparse
import time
import re
import sys
from typing import Optional, Tuple

import requests

CROSSREF_API_TEMPLATE = (
    "https://api.crossref.org/journals/{issn}/works"
    "?select=DOI,prefix,title,publisher,type,title,resource,URL,ISSN,created"
    "&rows=1000&sort=created&order=asc"
)
UA = "PiriLinkTester/1.0 (mailto:you@example.com)"
TIMEOUT = 15
SLEEP_BETWEEN = 0  # ✅ gecikme kaldırıldı

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()

def check_url(url: str, title_norm: str) -> Tuple[int, bool, str]:
    """
    URL'e GET atar:
      - status_code
      - başlık içeriyor mu (bool)
      - özel durum: 200 ama içerikte '404 Not Found' varsa 404 gibi kabul edilir
    """
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
                return 404, False, "200 ama sayfada '404 Not Found' var ❌"
            contains_title = title_norm in text_norm if title_norm else False
            return status, contains_title, "200 OK"
        else:
            return status, False, f"HTTP {status}"
    except requests.RequestException as e:
        return 0, False, f"Bağlantı hatası: {e}"

def build_doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    if not doi:
        return ""
    return f"https://doi.org/{doi}"

def main():
    parser = argparse.ArgumentParser(description="Crossref link testi (ISSN bazlı).")
    parser.add_argument("--issn", default="2148-5704", help="ISSN (ör. 2148-5704)")
    args = parser.parse_args()

    api_url = CROSSREF_API_TEMPLATE.format(issn=args.issn)
    print(f"[INFO] Crossref API: {api_url}")

    try:
        r = requests.get(api_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERR] Crossref API hatası: {e}")
        sys.exit(1)

    data = r.json()
    items = (data.get("message") or {}).get("items") or []
    total = len(items)
    print(f"[INFO] Toplam kayıt: {total}")

    ok_cnt = 0
    err_cnt = 0

    for i, it in enumerate(items, 1):
        doi = (it.get("DOI") or "").strip()
        title_list = it.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        title_norm = normalize_text(title)

        # URL sırası: 1) resource.primary.URL  2) URL  3) DOI->doi.org
        resource_primary_url = ""
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
        details = []

        for label, url in candidates:
            if not url:
                details.append(f"{label}: boş")
                continue
            status, has_title, info = check_url(url, title_norm)
            if status == 200 and has_title:
                details.append(f"{label}: 200 + başlık VAR ✅")
                passed = True
                break
            elif status == 200 and not has_title:
                details.append(f"{label}: 200 ama başlık YOK ⚠")
            elif status == 404:
                details.append(f"{label}: 404 (sayfada '404 Not Found') ❌")
            elif status == 0:
                details.append(f"{label}: BAĞLANTI HATASI ❌")
            else:
                details.append(f"{label}: {info} ❌")

        if passed:
            ok_cnt += 1
            print(f"[{i}/{total}] PASS  DOI={doi}  | {title[:80]!r}")
        else:
            err_cnt += 1
            print(f"[{i}/{total}] FAIL  DOI={doi}  | {title[:80]!r}")

        for d in details:
            print("    -", d)

    print("\n[ÖZET]")
    print(f"  Başarılı: {ok_cnt}")
    print(f"  Başarısız: {err_cnt}")
    print(f"  Toplam: {total}")

if __name__ == "__main__":
    main()
