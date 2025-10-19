# utils.py
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Set, Tuple

import requests
from selenium import webdriver

from config import UA

# ---------- Metin yardımcıları ----------
def normalize_text(s: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", s or "").strip().lower()

# ---------- JSONL yardımcıları ----------
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

# ---------- PDF yardımcıları ----------
def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Tercihen pdfminer.six ile PDF metni çıkar. Yoksa kaba fallback:
    latin-1 decode (errors='ignore').
    """
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(BytesIO(pdf_bytes)) or ""
        return text
    except Exception:
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
        text = extract_text_from_pdf_bytes(resp.content)
        return status, normalize_text(text)
    except requests.RequestException:
        return 0, ""

# ---------- Selenium + ağ ----------
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
                        # final_url eşleşmesi varsa onu tercih et
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

def build_doi_url(doi: str) -> str:
    doi = (doi or "").strip()
    return f"https://doi.org/{doi}" if doi else ""

def check_url_selenium(driver: webdriver.Chrome, url: str, title_norm: str) -> Tuple[int, bool, str, bool]:
    """
    Selenium ile URL'i aç ve değerlendir:
      - HTTP status,
      - başlık var mı,
      - info,
      - erişilebilir mi (200 + body '404 not found' değil).
    PDF ise bytes indirip PDF metninde başlık ara.
    """
    from config import TIMEOUT  # sadece garanti amaçlı
    if not url:
        return 0, False, "boş URL", False

    status, html, final_url, mime_type = get_http_status_source_mime(driver, url)

    # PDF ise
    if is_pdf_mime_or_url(mime_type, final_url):
        pdf_status, pdf_text_norm = fetch_pdf_text(final_url)
        st = pdf_status if pdf_status != 0 else (status if status != 0 else 200)
        if st == 200:
            if "404 not found" in pdf_text_norm:
                return 404, False, "PDF 200 ama içerikte '404 not found' var ❌", False
            has_title = title_norm in pdf_text_norm if title_norm else False
            return 200, has_title, "200 OK (PDF)", True
        else:
            return st, False, f"HTTP {st} (PDF)", False

    # HTML benzeri
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

def load_summary_names(summary_path: Path) -> Set[str]:
    """
    summary.jsonl içindeki journal_name VE dp_journal_name alanlarını
    (küçük harfe çevirerek) set olarak döndürür.
    """
    names: Set[str] = set()
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                jn = (obj.get("journal_name") or "").strip().lower()
                djn = (obj.get("dp_journal_name") or "").strip().lower()
                if jn:
                    names.add(jn)
                if djn:
                    names.add(djn)
    return names
