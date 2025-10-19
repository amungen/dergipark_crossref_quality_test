# main.py
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Set

from config import START_INDEX, POLITE_DELAY
from driver import build_driver
from utils import append_jsonl, load_summary_names
from processor import process_one_issn


def main():
    parser = argparse.ArgumentParser(
        description="DergiPark JSON → Crossref Selenium toplu doğrulama (PDF destekli)"
    )
    parser.add_argument("--input", default="dergipark_journals_detail.json",
                        help="DergiPark dergi listesi JSON (array)")
    parser.add_argument("--summary", default="summary.jsonl", help="Özet JSONL dosyası")
    parser.add_argument("--detail", default="detail.jsonl", help="Detay JSONL dosyası")
    parser.add_argument("--max", type=int, default=0, help="İlk N dergi ile sınırla (0=hepsi)")
    parser.add_argument("--start", type=int, default=START_INDEX,
                        help=f"Başlangıç index'i (1-based). Varsayılan: {START_INDEX}")
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

    # --- summary.jsonl'deki dergi adlarını (journal_name + dp_journal_name) tek seferde yükle
    processed_names = load_summary_names(summary_path)

    # Selenium (tek pencere)
    driver = build_driver(detach=True)

    processed_issns: Set[str] = set()  # bu koşuda tekrar ISSN işlenmesin
    total_cnt = 0
    N = len(journals)
    start_idx = max(1, int(args.start))

    for idx, j in enumerate(journals, start=1):
        if args.max and total_cnt >= args.max:
            break
        if idx < start_idx:
            continue

        dp_name = (j.get("journal_name") or "").strip()
        dp_name_l = dp_name.lower()

        # --- Hızlı SKIP (isim bazlı): summary’de aynı ad varsa Crossref/Selenium'a girmeden atla
        if dp_name_l in processed_names:
            info = f"[FAST-SKIP] summary’de isim var: {dp_name}"
            print(info)
            append_jsonl(detail_path, {
                "level": "INFO",
                "event": "fast-skip-name",
                "dp_journal_name": dp_name,
                "idx": idx
            })
            continue

        issn = (j.get("issn") or "").strip()
        eissn = (j.get("eissn") or "").strip()
        chosen_issn = issn if issn else eissn

        if not chosen_issn:
            info = f"[SKIP] ISSN ve eISSN yok: {dp_name}"
            print(info)
            append_jsonl(detail_path, {
                "level": "WARN", "event": "skip-no-issn",
                "dp_journal_name": dp_name, "idx": idx
            })
            continue

        if chosen_issn in processed_issns:
            info = f"[SKIP] Aynı ISSN tekrar: {chosen_issn} ({dp_name})"
            print(info)
            append_jsonl(detail_path, {
                "level": "INFO", "event": "skip-dup-issn",
                "issn": chosen_issn, "dp_journal_name": dp_name, "idx": idx
            })
            continue

        print(f"[RUN] {idx}/{N}  {dp_name}  → ISSN={chosen_issn}")
        process_one_issn(driver, chosen_issn, summary_path, detail_path, dp_journal_name=dp_name)
        processed_issns.add(chosen_issn)
        total_cnt += 1

        # Dergi bazında nazik gecikme
        time.sleep(POLITE_DELAY)

    input("Tarayıcı açık. Kapatmak için Enter'a basın...")
    driver.quit()


if __name__ == "__main__":
    main()
