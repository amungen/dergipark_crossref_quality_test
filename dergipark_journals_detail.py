import json
import time
import random
from pathlib import Path
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ----------------------------------
# Ayarlar
# ----------------------------------
INPUT_JSON  = "dergipark_journals.json"        # <-- Kullanıcının istediği giriş dosyası adı
OUTPUT_JSON = "dergipark_journals_detail.json"
BASE        = "https://dergipark.org.tr"
WAIT_TIMEOUT = 20                              # saniye
SLEEP_RANGE  = (0.6, 1.2)                      # sayfalar arası nazik gecikme

# ----------------------------------
# WebDriver
# ----------------------------------
def build_driver(headless=False):              # görünür tarayıcı için headless=False
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=tr-TR")
    opts.add_argument("--user-agent=PiriHarvester/1.0 (+you@example.com)")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.set_page_load_timeout(60)
    return driver

# ----------------------------------
# Yardımcılar
# ----------------------------------
def txt_or_none(el):
    try:
        t = (el.text or "").strip()
        return t if t else None
    except:
        return None

def find_text(driver, css, sub_css=None):
    """CSS ile bul, alt elemandan metin çek (ör. '.no-wrap'). Yoksa üstten çek."""
    try:
        el = driver.find_element(By.CSS_SELECTOR, css)
        if sub_css:
            try:
                sub = el.find_element(By.CSS_SELECTOR, sub_css)
                return txt_or_none(sub)
            except:
                return txt_or_none(el)
        return txt_or_none(el)
    except:
        return None

def absolutize(href):
    if not href:
        return None
    return urljoin(BASE, href) if href.startswith("/") else href

def wait_meta_block(driver):
    # meta bloğu (veya sayfadaki temel çerçeve) gelsin
    WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.any_of(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#meta-block")),
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#journal-content, main"))
        )
    )

# ----------------------------------
# Sayfadan alanları çek
# ----------------------------------
def scrape_journal_meta(driver, url):
    driver.get(url)
    wait_meta_block(driver)
    # ufak gecikme (dinamik alanlar için)
    time.sleep(random.uniform(0.2, 0.5))

    # ISSN / e-ISSN / Başlangıç
    issn       = find_text(driver, "#meta-issn",   ".no-wrap")
    eissn      = find_text(driver, "#meta-eissn",  ".no-wrap")
    founded    = find_text(driver, "#meta-founded", ".no-wrap")

    # Periyot (genelde link içinde yazıyor; yoksa container metninden ayıkla)
    period = None
    try:
        # Önce link içinden
        a = driver.find_element(By.CSS_SELECTOR, "#meta-period a")
        period = txt_or_none(a)
    except:
        # Container metninden (başlığı kaldırmaya çalış)
        raw = find_text(driver, "#meta-period")
        if raw:
            period = raw.replace("Periyot:", "").strip() or None

    # Yayımcı adı + link (varsa)
    publisher_name = None
    publisher_url  = None
    try:
        pub_a = driver.find_element(By.CSS_SELECTOR, "#publisher a")
        publisher_name = txt_or_none(pub_a)
        publisher_url  = absolutize(pub_a.get_attribute("href"))
    except:
        # Bazı sayfalarda link olmayabilir; çıplak metni dene
        publisher_name = find_text(driver, "#publisher")
        if publisher_name:
            publisher_name = publisher_name.replace("Yayımcı:", "").strip() or None

    return {
        "issn": issn,
        "eissn": eissn,
        "founded": founded,
        "period": period,
        "publisher_name": publisher_name,
        "publisher_url": publisher_url,
    }

# ----------------------------------
# Ana akış
# ----------------------------------
def main(headless=False):
    # 1) Giriş JSON'u oku
    in_path = Path(INPUT_JSON)
    if not in_path.exists():
        raise FileNotFoundError(f"Giriş dosyasını bulamadım: {in_path.resolve()}")

    with in_path.open("r", encoding="utf-8") as f:
        journals = json.load(f)

    # Basit şema bekliyoruz: [{"journal_name": "...", "journal_url": "..."}, ...]
    driver = build_driver(headless=headless)

    detailed = []
    try:
        for idx, j in enumerate(journals, start=1):
            name = j.get("journal_name")
            url  = j.get("journal_url")

            if not url:
                print(f"[WARN] URL yok, atlanıyor: {name}")
                continue

            print(f"[{idx}/{len(journals)}] Ziyaret: {url}")
            try:
                meta = scrape_journal_meta(driver, url)
            except Exception as e:
                print(f"[ERR] Çekilemedi ({url}): {e}")
                meta = {
                    "issn": None, "eissn": None, "founded": None,
                    "period": None, "publisher_name": None, "publisher_url": None
                }

            detailed.append({
                "journal_name": name,
                "journal_url": url,
                **meta
            })

            # Nazik gecikme
            time.sleep(random.uniform(*SLEEP_RANGE))

    finally:
        # Tarayıcı açık kalsın istersen bu satırı kapat, altta Enter bekletebilirsin
        driver.quit()
        # input("Kapatmak için Enter...")

    # 3) Çıkışı yaz
    out_path = Path(OUTPUT_JSON)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(detailed, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Toplam {len(detailed)} dergi işlendi → {out_path.resolve()}")

if __name__ == "__main__":
    # Görünür tarayıcı: headless=False
    main(headless=False)
