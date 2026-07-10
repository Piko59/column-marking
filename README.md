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

Tekrarlanabilirlik için varsayılan `LLM_TEMPERATURE=0` ve sabit `LLM_SEED=7`
(sağlayıcı destekliyorsa) kullanılır — denetimde "aynı girdiye aynı çıktı" sorusu
gelir; ihtiyaç hâlinde `.env`'den yükseltin.

### Testler

```bash
pip install -r requirements-dev.txt
pytest
```

Kural katmanı, JSON ayıklama, sonuç doğrulama (`_sanitize`) ve Excel başlık eşleme
gibi saf fonksiyonlar için birim testler `tests/` altında. Gerçek bir API anahtarı
gerekmez — `tests/conftest.py` sahte bir anahtar enjekte eder.


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

**Hız:** Gecikme büyük ölçüde çağrı başına sabit bir model gecikmesinden gelir (kolon
sayısından değil), bu yüzden iki paralellik ekseni var: küçük tablolar `BATCH_SIZE`'a
kadar TEK çağrıda birleştirilir (her biri kendi ŞEMA/TABLO bölümünde, bağlam karışmaz —
bkz. `prompts.build_multi_table_prompt`), ve (benchmark'ta) üç mod eşzamanlı koşar.
Gerçek eşzamanlı istek sınırı TEK, merkezi bir yerde: `llm._get_semaphore()`
(`config.LLM_CONCURRENCY`, varsayılan 8) — iki paralellik ekseni birden var olduğundan
dağınık yerel semaforlar toplam isteği kontrolsüz büyütürdü.

Kategori tanımları mevzuata dayanır: KVKK m.3/d ve m.6; 5411 sayılı Bankacılık Kanunu m.73;
Sır Niteliğindeki Bilgilerin Paylaşılması Hakkında Yönetmelik (BDDK, 2021); Bankaların Bilgi
Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında Yönetmelik ("hassas veri" tanımı).

## Örnek Değerler (İçerik Sinyali)

Kolon başına 3-5 örnek değer verilirse (`RowIn.ornek_degerler`), bunlar LLM'e
gönderilmeden önce **maskelenir** (`rules.mask_sample`: uzunluk + ilk/son birkaç
karakter korunur, ortası yıldızlanır — TCKN'nin 11 hane, IBAN'ın "TR" ile başlayıp
26 karakter olması gibi biçim sinyalleri kalır, tam değer gitmez). `classify_rows`
üç modu destekler:

| mode | isim | içerik | ne zaman |
|---|---|---|---|
| `name_content` (varsayılan) | var | varsa gider | üretim |
| `name_only` | var | gitmez | yalnız isim sinyalini ölçmek için |
| `content_only` | anonimleştirilir | gider | yalnız içerik sinyalini ölçmek için |

`content_only` ve `name_only`, esas olarak aşağıdaki **Benchmark** özelliği için var.

## Benchmark

Arayüzdeki **Benchmark** sekmesi, `benchmark/dataset.py` içindeki elle etiketlenmiş,
ground truth'u kesin **112 satırlık** sentetik bir veri setini üç modda (yukarıdaki
tablo) çalıştırıp doğruluğu ölçer.

- **56 kavram** (7 resmî kategoriden 7'şer + yanlış-pozitif riskini ölçen 1 "teknik/
  işlemsel" kova × 7), her biri **isimli** (gerçekçi banka adlandırması, örn.
  `mhIban` / tablo `MusteriHesap` / şema `core`) ve **rastgele** (anlamsız kod, örn.
  `x113` / `tblc90` / `z44`) isim muamelesiyle eşleştirilmiştir (pairing) — aynı
  içerik, iki farklı isim koşulu.
- Skor motoru (`benchmark/scorer.py`) her satır için ana kategori tam eşleşmesi,
  kategori kümesi precision/recall/F1, teknik bayrağı doğruluğu ve güveni hesaplar;
  bunları mod × grup × kategori kırılımında toplar. Ayrıca **isim bağımlılığı**
  metriği üretir: aynı kavram yalnız isim verildiğinde doğru, isim anlamsızken
  yanlış çıkıyorsa bu, modelin içerikten değil isim kalıbından karar verdiğinin
  göstergesidir.
- Bir koşu dakikalar sürebileceğinden arka planda çalışır (`benchmark/jobs.py`);
  arayüz `/api/benchmark/jobs/{id}` ile ilerlemeyi periyodik sorgular. Sonuçlar
  `benchmark_runs/` altına kalıcı yazılır (`.gitignore`'da) — geçmiş denemeler
  Benchmark sekmesinde karşılaştırılabilir, silinebilir.
- Veri setini elle gözden geçirmek için: `GET /api/benchmark/dataset/concepts`
  (her kavramın ground truth'u + gerekçesi + örnek değerleri).

## Dosya Yapısı

```
main.py                  FastAPI: upload / classify / analyze / export / benchmark uçları
config.py                model, anahtar ve pipeline ayarları
classifier/
  categories.py          7 kategori + tanımları + öncelik sırası (tek doğruluk kaynağı)
  rules.py               önek çözümü, tokenizasyon, anahtar kelime sözlüğü, örnek maskeleme
  prompts.py             toplu sınıflandırma + hakem prompt'ları + prompt versiyon hash'i
  llm.py                 OpenAI-uyumlu istemci (retry + güvenli JSON ayıklama)
  pipeline.py            orkestrasyon: kural → önbellek → toplu LLM → hakem (3 mod destekli)
benchmark/
  dataset.py             golden veri seti: 56 kavram × 2 isim grubu = 112 satır
  scorer.py              3 mod × dataset koşusu + çok boyutlu metrikler
  jobs.py                arka plan iş takibi (bellek-içi)
  store.py               koşu geçmişi kalıcılığı (benchmark_runs/, JSON dosya)
tests/                   pytest birim testleri (kural/pipeline/llm/main saf fonksiyonları)
static/                  arayüz (index.html, style.css, app.js) — Excel / Tekil Sorgu / Benchmark
classification_cache.json  otomatik oluşan sonuç önbelleği (model+prompt versiyonuna bağlı)
benchmark_runs/          otomatik oluşan benchmark koşu geçmişi (.gitignore'da)
```

## Excel Formatı

Başlık eşleştirme esnektir ("Kolon Ad", "Kolon Adı", "COLUMN_NAME" hepsi çalışır).
Zorunlu tek sütun **Kolon Ad**; Tablo Ad şiddetle önerilir (bağlam oradan gelir).
