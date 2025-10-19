import json
from collections import Counter, defaultdict
import math

summary_file = "summary.jsonl"

total_journals = 0
total_articles = 0
total_accessible = 0
total_correct = 0

journal_stats = []

# --- Dosyayı oku ---
with open(summary_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        total_journals += 1
        total_articles += data.get("total", 0)
        total_accessible += data.get("accessible", 0)
        total_correct += data.get("correct", 0)

        acc = data.get("accessible", 0)
        tot = data.get("total", 0)
        cor = data.get("correct", 0)

        access_rate = (acc / tot * 100) if tot > 0 else 0.0
        correct_rate = (cor / tot * 100) if tot > 0 else 0.0

        journal_stats.append({
            "issn": data.get("issn", ""),
            "name": data.get("journal_name", "N/A"),
            "accessible": acc,
            "total": tot,
            "correct": cor,
            "access_rate": access_rate,
            "correct_rate": correct_rate
        })

# --- Genel istatistik ---
print("📊 GENEL İSTATİSTİKLER")
print(f"Toplam dergi sayısı: {total_journals}")
print(f"Toplam makale sayısı: {total_articles}")
if total_articles > 0:
    print(f"Erişilebilen makale sayısı: {total_accessible} ({total_accessible/total_articles*100:.2f}%)")
    print(f"Başlık eşleşen makale sayısı: {total_correct} ({total_correct/total_articles*100:.2f}%)\n")
else:
    print(f"Erişilebilen makale sayısı: {total_accessible}")
    print(f"Başlık eşleşen makale sayısı: {total_correct}\n")

# --- Erişim oranı 100% ve 0% olanlar ---
full_access_journals = [j for j in journal_stats if j["access_rate"] == 100.0]
zero_access_journals = [j for j in journal_stats if j["access_rate"] == 0.0]

print(f"✅ Erişim oranı %100 olan dergi sayısı: {len(full_access_journals)}")
for j in full_access_journals:
    print(f"   - {j['issn']}\t{j['name']} (Toplam {j['total']} makale)")

print(f"\n🚫 Erişim oranı %0 olan dergi sayısı: {len(zero_access_journals)}")
for j in zero_access_journals:
    print(f"   - {j['issn']}\t{j['name']} (Toplam {j['total']} makale)")

# --- Dağılım aralıkları ---
def bucket(rate):
    if rate == 0:
        return "0%"
    elif 0 < rate < 25:
        return "0-25%"
    elif 25 <= rate < 50:
        return "25-50%"
    elif 50 <= rate < 75:
        return "50-75%"
    elif 75 <= rate < 100:
        return "75-99%"
    else:
        return "100%"

buckets = Counter(bucket(j["access_rate"]) for j in journal_stats)

print("\n📈 Erişim oranı dağılımı:")
for k in ["0%", "0-25%", "25-50%", "50-75%", "75-99%", "100%"]:
    print(f"{k:>8}: {buckets.get(k, 0)} dergi")

# --- YENİ: Erişim% ↔ Doğruluk% ilişkisi ---

# 1) Pearson korelasyon (erişim% ve doğruluk% arasında)
xs = [j["access_rate"] for j in journal_stats]
ys = [j["correct_rate"] for j in journal_stats]

def pearson_r(x, y):
    n = len(x)
    if n < 2:
        return float('nan')
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    den_x = math.sqrt(sum((a - mean_x) ** 2 for a in x))
    den_y = math.sqrt(sum((b - mean_y) ** 2 for b in y))
    if den_x == 0 or den_y == 0:
        return float('nan')
    return num / (den_x * den_y)

r = pearson_r(xs, ys)
print("\n🔗 Erişim% ↔ Doğruluk% ilişkisi")
print(f"Pearson korelasyon r: {r:.4f} (1'e yakın: güçlü pozitif, 0: ilişkisiz, -1: güçlü negatif)")

# 2) Erişim oranı dilimine göre ortalama doğruluk oranı
cond = defaultdict(list)
for j in journal_stats:
    cond[bucket(j["access_rate"])].append(j["correct_rate"])

print("\n🧮 Erişim dilimine göre ortalama doğruluk oranı:")
for k in ["0%", "0-25%", "25-50%", "50-75%", "75-99%", "100%"]:
    vals = cond.get(k, [])
    avg = (sum(vals) / len(vals)) if vals else 0.0
    print(f"{k:>8}: dergi={len(vals):3d}, ort. doğruluk%={avg:6.2f}")

# --- Dergi Bazlı Liste (ISSN \t İsim ...) ---
print("\n📄 Tüm dergilerin erişim/ doğruluk oranları:")
print(f"{'ISSN':<12}\t{'Dergi Adı':50s} {'Toplam':>6} {'Erişim':>8} {'Doğru':>8} {'Erişim%':>10} {'Doğru%':>10}")
print("-" * 105)
for j in sorted(journal_stats, key=lambda x: x["access_rate"], reverse=True):
    # Başta ISSN sonra \t, sonra isim
    print(f"{j['issn']:<12}\t{j['name'][:50]:50s} {j['total']:6d} {j['accessible']:8d} {j['correct']:8d} {j['access_rate']:10.2f} {j['correct_rate']:10.2f}")
