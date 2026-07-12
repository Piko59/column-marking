import os

from dotenv import load_dotenv

load_dotenv()  # proje kökündeki .env dosyasını okur (yoksa sessizce geçer)

QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://openrouter.ai/api/v1")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen/qwen3.6-27b")
QWEN_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

if not QWEN_API_KEY:
    raise RuntimeError(
        "OPENROUTER_API_KEY tanımlı değil. .env.example dosyasını .env olarak kopyalayıp "
        "API anahtarınızı girin (bkz. README)."
    )

# Pipeline ayarları
USE_CACHE = os.getenv("USE_CACHE", "0") == "1"  # kapalı: her sorgu yeniden değerlendirilir
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "25"))          # tek LLM çağrısındaki maks. kolon sayısı
JUDGE_THRESHOLD = float(os.getenv("JUDGE_THRESHOLD", "0.75"))  # bu güvenin altı (veya marj < JUDGE_MARGIN_THRESHOLD) hakem geçişine gider
# Olasılık dağılımının marjı (en yüksek iki olasılık arasındaki fark) bu değerden
# küçükse model gerçekten kararsız demektir — güven yüksek olsa bile hakem çağrılır.
JUDGE_MARGIN_THRESHOLD = float(os.getenv("JUDGE_MARGIN_THRESHOLD", "0.25"))
# Tekrarlanabilirlik: varsayılan 0 (deterministik) — denetimde "aynı girdiye aynı çıktı"
# sorusu gelir; farklılık istenirse .env'den yükseltin. LLM_SEED, sağlayıcı destekliyorsa
# (OpenAI-uyumlu "seed" alanı) örnekleme akışını da sabitler; desteklemiyorsa yok sayılır.
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_SEED = int(os.getenv("LLM_SEED", "7"))
# Düşünen (reasoning) modellerde harcanacak düşünme bütçesi: low/medium/high veya "" (gönderme).
# "low" hız için; başarı düşerse "medium"/"high" deneyin. Desteklemeyen modelde yok sayılır.
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "low")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
CACHE_FILE = os.getenv("CACHE_FILE", "classification_cache.json")
# İnsan inceleme kararlarının (onayla/düzelt/nötr) kalıcı sözlüğü.
DECISIONS_FILE = os.getenv("DECISIONS_FILE", "review_decisions.json")
# Few-shot: her LLM çağrısına, o partideki kolonlara en benzer en fazla K insan-onaylı
# karar örnek olarak eklenir (0 = kapalı). Havuz ne kadar büyürse büyüsün prompt'a giren
# miktar K ile sınırlıdır — şişme yapısal olarak engellenir.
FEWSHOT_K = int(os.getenv("FEWSHOT_K", "8"))
# Bu benzerliğin (token Jaccard) altındaki kararlar örnek olarak alınmaz — alakasız
# örnek, örneksizden kötüdür.
FEWSHOT_MIN_SIM = float(os.getenv("FEWSHOT_MIN_SIM", "0.3"))

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
