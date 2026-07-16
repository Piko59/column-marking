import os

from dotenv import load_dotenv

load_dotenv()  # proje kökündeki .env dosyasını okur (yoksa sessizce geçer)

# LLM bağlantısı — OpenAI-uyumlu her uç ile çalışır (vLLM / Ollama / kurum içi gateway).
# Kurum içi/yerel dağıtım varsayılır; URL ve anahtar .env'den doldurulur.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-35")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# Kurum içi HTTPS uçlarında sertifika doğrulaması: "0" yapılırsa kapanır — kurum
# CA'lı/self-signed sertifikalı uçlar için gereklidir (yalnız izole kurum ağında).
LLM_VERIFY_SSL = os.getenv("LLM_VERIFY_SSL", "1") != "0"

if not LLM_BASE_URL or not LLM_API_KEY:
    raise RuntimeError(
        "LLM_BASE_URL ve/veya LLM_API_KEY tanımlı değil. .env.example dosyasını .env "
        "olarak kopyalayıp kurum içi LLM ucunuzun adresini ve anahtarını girin "
        "(anahtar istemeyen uçlar için LLM_API_KEY=dummy yeterlidir; bkz. README)."
    )

# Pipeline ayarları
USE_CACHE = os.getenv("USE_CACHE", "0") == "1"  # kapalı: her sorgu yeniden değerlendirilir
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))          # tek LLM çağrısındaki maks. kolon sayısı
# Hakem tetikleyici 1: kazanan kategorinin olasılığı (guven) bu eşiğin altındaysa
# model o kategoriye yeterince emin değil demektir → ikinci görüş (hakem) alınır.
JUDGE_THRESHOLD = float(os.getenv("JUDGE_THRESHOLD", "0.75"))
# Hakem tetikleyici 2: en yüksek iki olasılığın farkı (marj) bu değerden küçükse iki
# kategori boğazlaşıyor (gerçek belirsizlik) — kazanan olasılık yüksek olsa bile hakem
# çağrılır. İki tetikleyici bağımsızdır; biri yeterlidir (bkz. pipeline.process_superbatch).
JUDGE_MARGIN_THRESHOLD = float(os.getenv("JUDGE_MARGIN_THRESHOLD", "0.25"))
# Tekrarlanabilirlik: varsayılan 0 (deterministik) — denetimde "aynı girdiye aynı çıktı"
# sorusu gelir; farklılık istenirse .env'den yükseltin. LLM_SEED, sağlayıcı destekliyorsa
# (OpenAI-uyumlu "seed" alanı) örnekleme akışını da sabitler; desteklemiyorsa yok sayılır.
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_SEED = int(os.getenv("LLM_SEED", "7"))
# Düşünen (reasoning) modellerde harcanacak düşünme bütçesi: low/medium/high veya "" (gönderme).
# "low" hız için; başarı düşerse "medium"/"high" deneyin. Desteklemeyen modelde yok sayılır.
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")
# Tekil sorgunun DERİN ANALİZ modu: tek kolon incelenirken zaman kritik değildir,
# düşünme bütçesi yükseltilir (+ arayüz hakemi de açar). Toplu koşu REASONING_EFFORT'ta kalır.
SINGLE_REASONING_EFFORT = os.getenv("SINGLE_REASONING_EFFORT", "high")
# OpenRouter'da tek bir batch çağrısının 100 saniyeyi aştığı gözlendi (paylaşımlı
# barındarma, değişken kuyruk); 120s'lik eski varsayılan timeout+retry fırtınasına yol
# açıyordu. Yerel vLLM'de çağrılar çok daha kısa sürer; istenirse .env'den düşürün.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
CACHE_FILE = os.getenv("CACHE_FILE", "classification_cache.json")
# İnsan inceleme kararlarının (onayla/düzelt/nötr) kalıcı sözlüğü.
DECISIONS_FILE = os.getenv("DECISIONS_FILE", "review_decisions.json")
# Yüklenebilecek maksimum Excel boyutu (MB) — bellek koruması.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
# Ham veri tablosu yüklemede örnekleme: kolon başına kaç örnek değer, kaç satır taranır.
SAMPLE_VALUES_PER_COLUMN = int(os.getenv("SAMPLE_VALUES_PER_COLUMN", "5"))
SAMPLE_SCAN_ROWS = int(os.getenv("SAMPLE_SCAN_ROWS", "500"))
# Boş değilse tüm /api/* istekleri X-API-Token başlığında bu değeri taşımak zorundadır.
# Localhost'ta gereksiz; uygulama ağda başka makinelere açılacaksa doldurun.
APP_API_TOKEN = os.getenv("APP_API_TOKEN", "")

# Süreç genelinde aynı anda kaç LLM isteği açık olabilir (llm.chat içindeki global
# semafor). Birden fazla mod artık paralel koştuğundan (benchmark) bu tek, MERKEZİ
# sınır önemli: dağınık yerel semaforlar mod paralelliğiyle birlikte toplam eşzamanlı
# istek sayısını kontrolsüz büyütürdü. Sağlayıcının rate limit'ine göre ayarlayın.
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "8"))
