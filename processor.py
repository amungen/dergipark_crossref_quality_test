# processor.py
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from selenium import webdriver

from config import CROSSREF_API_TEMPLATE, UA, POLITE_DELAY
from utils import (
    normalize_text, append_jsonl, read_jsonl_names,
    build_doi_url, check_url_selenium
)

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
        append_jsonl(detail_path, {
            "level": "ERROR", "issn": issn, "msg": msg,
            "api_url": api_url, "dp_journal_name": dp_journal_name
        })
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

    # (İstersen bu kontrolü kaldırabilirsin; hızlı skip artık main'de yapılabilir)
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
        "issn": issn, "journal_name": journal_name,
        "dp_journal_name": dp_journal_name, "api_url": api_url,
        "total": total
    })

    for i, it in enumerate(items, 1):
        doi = (it.get("DOI") or "").strip()
        title_list = it.get("title") or []
        title = (title_list[0] if title_list else "").strip()
        title_norm = normalize_text(title)

        # Aday URL'ler
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

        # Dedup
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
                break
            time.sleep(POLITE_DELAY)

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
        "journal_name": journal_name,
        "dp_journal_name": dp_journal_name,
        "issn": issn,
        "total": total,
        "accessible": accessible_cnt,
        "correct": correct_cnt,
        "fetcher": "selenium"
    })

    print(f"[DONE] {journal_name} | ISSN={issn} | total={total} | accessible={accessible_cnt} | correct={correct_cnt}")
