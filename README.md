# 📚 DergiPark & Crossref Link Tester

Bu proje, **DergiPark** üzerinde listelenen dergilerin meta verilerini çekmek, ayrıntılı ISSN/eISSN bilgilerini toplamak ve **Crossref** API’si üzerinden makale DOI linklerinin geçerliliğini test etmek için geliştirilmiştir.  
Selenium ve Requests kütüphaneleri kullanılarak hem **tarayıcı tabanlı** hem de **doğrudan HTTP** kontrolü yapılabilir.

---

## 🚀 Özellikler

- 🕷️ DergiPark üzerinden dergi listesi toplama (Selenium crawler)
- 🧾 Dergi sayfalarından ISSN, eISSN, yayıncı ve periyot bilgisi çekme
- 🔗 Crossref API üzerinden DOI listesi alma ve geçerlilik testi yapma
- 🌐 DOI linklerinin status code (200/404) ve başlık eşleşmesiyle doğrulanması
- 🪵 Tüm sonuçların `JSON` veya `JSONL` formatında loglanması

---

## 📁 Proje Yapısı

```
.
├── crossref_link_tester.py               # Requests tabanlı Crossref link testi
├── crossref_link_tester_log.py           # Log dosyası yazma destekli sürüm
├── crossref_link_tester_selenium_jsonl.py# Selenium tabanlı link testi
├── islem.py                              # Ortak yardımcı fonksiyonlar
├── dergipark_journals.py                 # DergiPark crawler (dergi listesi)
├── dergipark_journals.json               # İlk çekilen dergi listesi (örnek)
├── dergipark_journals_detail.py          # Dergi meta verisi ayrıntılı çekme
├── dergipark_journals_detail.json        # Örnek meta veri çıktısı
└── README.md
```

---

## 🧰 Gereksinimler

- Python 3.9+
- Google Chrome & ChromeDriver
- Aşağıdaki Python paketleri:
  ```bash
  pip install selenium webdriver-manager requests
  ```

---

## 🕸️ Dergi Listesi Toplama

Tüm DergiPark dergilerinin temel ad ve URL bilgisini çekmek için:

```bash
python dergipark_journals.py
```

Bu işlem `dergipark_journals.json` dosyasını oluşturur.  
Veri yapısı örneği:

```json
[
  {
    "journal_name": "Ankara Avrupa Çalışmaları Dergisi",
    "journal_url": "https://dergipark.org.tr/tr/pub/aacd"
  },
  ...
]
```

---

## 📝 Dergi Meta Verisi Çekme

DergiPark’taki her dergi sayfasından ISSN, eISSN, yayın periyodu ve yayıncı bilgisini çekmek için:

```bash
python dergipark_journals_detail.py
```

Çıktı örneği (`dergipark_journals_detail.json`):

```json
{
  "journal_name": "Ankara Avrupa Çalışmaları Dergisi",
  "issn": "1303-2518",
  "eissn": "2980-3349",
  "founded": "2001",
  "period": "Yılda 2 Sayı",
  "publisher_name": "Ankara Üniversitesi",
  "publisher_url": "https://dergipark.org.tr/tr/pub/publisher/45"
}
```

---

## 🌐 Crossref DOI Link Testi

Bir derginin ISSN numarasına göre Crossref DOI’larını çekip geçerliliklerini test etmek için:

```bash
python crossref_link_tester.py --issn 2148-5704
```

Alternatif Selenium tabanlı test:

```bash
python crossref_link_tester_selenium_jsonl.py --issn 2148-5704
```

Çıktılar `summary.jsonl` ve `detail.jsonl` dosyalarına yazılır.

---

## 📊 Loglama

- **summary.jsonl** → Dergi bazlı özet kayıtlar  
- **detail.jsonl** → Her DOI denemesinin ayrıntılı sonucu  
- Örnek log satırı:

```json
{
  "issn": "2148-5704",
  "doi": "10.1234/example-doi",
  "status": 200,
  "title_match": true,
  "url_type": "resource.primary.URL",
  "message": "200 OK"
}
```

---

## ⚡ Faydalı Notlar

- DergiPark scraper’ı çok sayıda sayfayı gezdiği için `--headless` opsiyonuyla arka planda çalıştırılabilir.  
- Selenium sürücüsü ilk kullanımda `webdriver-manager` tarafından otomatik kurulur.  
- Crossref API isteklerinde User-Agent eklemek zorunludur (projedeki UA kullanılır).

---

## 🧑‍💻 Katkıda Bulunma

1. Bu repo’yu forklayın.  
2. Yeni özellik veya düzeltmeleri bir branch’te geliştirin.  
3. Pull request gönderin.

---

## 📜 Lisans

Bu proje MIT lisansı ile lisanslanmıştır.  
Veriler, DergiPark ve Crossref API servislerinden çekilmektedir.
