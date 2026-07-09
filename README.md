# Kolon İşaretleme

Veritabanı kolon envanterini (Excel) 7 gizlilik kategorisine göre çok-etiketli sınıflandıran web uygulaması.

| # | Kategori |
|---|----------|
| 1 | Kişisel Veri |
| 2 | Özel Nitelikli Kişisel Veri |
| 3 | Hassas Veri |
| 4 | Banka Sırrı |
| 5 | Müşteri Sırrı |
| 6 | Gizli / Çok Gizli Veri |
| 7 | Şifreli Veri |

## Kurulum ve Çalıştırma

```bash
pip install -r requirements.txt
copy .env.example .env        # Linux/Mac: cp .env.example .env
# .env dosyasını açıp OPENROUTER_API_KEY değerini kendi anahtarınızla doldurun
uvicorn main:app --port 8000
```

Tarayıcıda: **http://localhost:8000**

Tüm ayarlar `.env` dosyasından (veya ortam değişkenlerinden) okunur; seçenekler için
[.env.example](.env.example) dosyasına bakın. `.env` dosyası `.gitignore`'dadır ve
**asla commit edilmez**; anahtar tanımlı değilse uygulama açılışta anlaşılır bir
hata verir.


## Mimari — LLM Hattı

"7 kategori için 7 ayrı prompt" yerine **tablo bazlı toplu, çok-etiketli tek prompt +
seçici hakem** yaklaşımı kullanıldı. Nedenleri:

- Kategoriler bağımsız değil (2 ⊂ 1; 4 ile 5 ancak yan yana görülünce ayrışır).
  Kategorileri tek tek soran model her soruya "evet" demeye meyillidir.
- 7 kat çağrı = 7 kat maliyet/süre; local 120b modelde daha da kritik.
- `arAppNo` gibi kısaltmaların anlamı tablo bağlamından gelir; asıl kazanç
  kategoriye bölmek değil, **tabloya göre gruplamak**tır.

```
Excel → Ön işleme        rules.py   olası önek/sözlük İPUÇLARI üretir (bağlayıcı değildir);
                                    asıl kısaltma açılımını LLM kendisi çıkarır ("acilim";
                                    emin değilse null → arayüzde "açılım bulunamadı")
      → Aşama 1          pipeline   tablo başına ≤25 kolon, tek prompt; LLM her kolon için
                                    4 adım uygular: açılım → olası kategoriler → TEK ana
                                    kategori → güven; teknik kolonlar "teknik" işaretlenir
      → Aşama 2 (hakem)  pipeline   yalnız GERÇEKTEN kararsız kolonlar (güven < 0.60 ve
                                    teknik değil) yeniden değerlendirilir
      → Excel çıktı      main.py    Ana Kategori + kategori başına 0/1 + teknik + açılım
                                    + güven + gerekçe
```

Her kolona olası kategoriler listesi ve **tek bir ana kategori** atanır; teknik/işlemsel
kolonlar en yakın kategoriye bağlanıp `teknik=1` işaretlenir. Önbellek varsayılan olarak
**kapalıdır** — her sorgu yeniden değerlendirilir (`USE_CACHE=1` ile açılabilir).
Hakem geçişi arayüzden kapatılabilir. Eşikler `config.py` içinde
(`BATCH_SIZE`, `JUDGE_THRESHOLD`, hız için `REASONING_EFFORT=low`).

Kategori tanımları mevzuata dayanır: KVKK m.3/d ve m.6; 5411 sayılı Bankacılık Kanunu m.73;
Sır Niteliğindeki Bilgilerin Paylaşılması Hakkında Yönetmelik (BDDK, 2021); Bankaların Bilgi
Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında Yönetmelik ("hassas veri" tanımı).

## Veri geldiğinde (gelecek adım)

Kolon altındaki örnek veriler geldiğinde `prompts.build_batch_prompt` içine her kolon
için 3-5 maskelenmiş örnek değer eklemek yeterli — pipeline değişmez, doğruluk belirgin
artar. Örnek değerleri LLM'e göndermeden önce maskelemeyi (ilk/son karakterler hariç
yıldızlama) unutmayın; sınıflandırmaya çalıştığınız şey zaten gizli veri olabilir.

## Dosya Yapısı

```
main.py                  FastAPI: upload / classify / analyze / export uçları
config.py                model, anahtar ve pipeline ayarları
classifier/
  categories.py          7 kategori + tanımları (tek doğruluk kaynağı)
  rules.py               önek çözümü, tokenizasyon, anahtar kelime sözlüğü
  prompts.py             toplu sınıflandırma + hakem prompt'ları
  llm.py                 OpenAI-uyumlu istemci (retry + JSON ayıklama)
  pipeline.py            orkestrasyon: kural → önbellek → toplu LLM → hakem
static/                  arayüz (index.html, style.css, app.js)
classification_cache.json  otomatik oluşan sonuç önbelleği
```

## Excel Formatı

Başlık eşleştirme esnektir ("Kolon Ad", "Kolon Adı", "COLUMN_NAME" hepsi çalışır).
Zorunlu tek sütun **Kolon Ad**; Tablo Ad şiddetle önerilir (bağlam oradan gelir).
