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
JUDGE_THRESHOLD = float(os.getenv("JUDGE_THRESHOLD", "0.60"))  # bu güvenin altı hakem geçişine gider
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

# Süreç genelinde aynı anda kaç LLM isteği açık olabilir (llm.chat içindeki global
# semafor). Birden fazla mod artık paralel koştuğundan (benchmark) bu tek, MERKEZİ
# sınır önemli: dağınık yerel semaforlar mod paralelliğiyle birlikte toplam eşzamanlı
# istek sayısını kontrolsüz büyütürdü. Sağlayıcının rate limit'ine göre ayarlayın.
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "8"))
