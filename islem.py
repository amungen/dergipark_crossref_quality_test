# dergipark_journals.py
import json
import time
import random
from urllib.parse import urljoin, urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE = "https://dergipark.org.tr"
START_URL = f"{BASE}/tr/pub/explore/journals"

def build_driver(headless=False):  # <-- GÖRÜNÜR İÇİN headless=False
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    # Daha stabil davranışlar:
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=tr-TR")
    opts.add_argument("--user-agent=PiriHarvester/1.0 (+mail@example.com)")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                            options=opts)

def wait_for_list(driver):
    # Listenin geldiğini garanti et
    WebDriverWait(driver, 20).until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "h5 > a[href^='/tr/pub/']")
        )
    )

def extract_page(driver):
    """Sayfadaki dergi adlarını ve linkleri döndürür."""
    wait_for_list(driver)
    anchors = driver.find_elements(By.CSS_SELECTOR, "h5 > a[href^='/tr/pub/']")
    rows = []
    for a in anchors:
        name = (a.text or "").strip()
        href = a.get_attribute("href")
        if href and href.startswith("/"):
            href = urljoin(BASE, href)
        if name and href:
            rows.append({"journal_name": name, "journal_url": href})
    return rows

def find_next_page(driver):
    """
    'Sonraki Sayfa' linkini robust biçimde bul:
      1) rel='next'
      2) 'Sonraki Sayfa' metni içeren <a>
      3) Alt kısımda '?page=' içeren ve 'Sonraki' metni taşıyan <a>
    Dönüş: URL (str) ya da None
    """
    # 1) rel="next" olan link
    try:
        next_by_rel = driver.find_elements(By.CSS_SELECTOR, "a[rel='next']")
        for el in next_by_rel:
            href = el.get_attribute("href")
            cls = el.get_attribute("class") or ""
            if href and "disabled" not in cls:
                return href
    except Exception:
        pass

    # 2) Metinden yakala
    try:
        candidates = driver.find_elements(By.XPATH, "//a[contains(., 'Sonraki Sayfa')]")
        for el in candidates:
            cls = el.get_attribute("class") or ""
            if "disabled" in cls:
                continue
            href = el.get_attribute("href") or ""
            if href:
                return href
    except Exception:
        pass

    # 3) Alt bölümde genel fallback: '?page=' içeren butonlar
    try:
        bottom_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='?page=']")
        for el in bottom_links:
            text = (el.text or "").strip()
            cls = el.get_attribute("class") or ""
            if "Sonraki" in text and "disabled" not in cls:
                href = el.get_attribute("href")
                if href:
                    return href
    except Exception:
        pass

    return None

def page_no_from_url(url: str):
    """Debug için: URL'den page numarasını çek."""
    try:
        q = parse_qs(urlparse(url).query)
        return int(q.get("page", [1])[0])
    except Exception:
        return None

def crawl_all(headless=False, delay_between_pages=(0.6, 1.2), max_pages=None):
    driver = build_driver(headless=headless)
    all_rows = []
    try:
        current_url = START_URL
        visited = 0

        while current_url:
            driver.get(current_url)
            # nazik gecikme (rastgele jitter ile)
            time.sleep(random.uniform(0.3, 0.8))

            rows = extract_page(driver)
            all_rows.extend(rows)

            visited += 1
            print(f"[INFO] Sayfa {page_no_from_url(current_url) or visited}: "
                  f"{len(rows)} dergi, toplam {len(all_rows)}")

            if max_pages and visited >= max_pages:
                break

            next_url = find_next_page(driver)
            if not next_url:
                print("[INFO] Son sayfaya ulaşıldı veya 'Sonraki Sayfa' bulunamadı.")
                break

            # nazik gecikme (range)
            time.sleep(random.uniform(*delay_between_pages))
            current_url = next_url

        return all_rows
    finally:
        # İstersen burada kapatma yerine input() ile bekletebilirsin
        driver.quit()

if __name__ == "__main__":
    data = crawl_all(headless=False)  # <-- GÖRÜNÜR
    with open("dergipark_journals.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Toplam {len(data)} dergi kaydedildi → dergipark_journals.json")
