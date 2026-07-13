"""Bankacılığa özel REFERANS ÖRNEK BANKASI + dinamik few-shot retrieval.

Amaç: Prompt'a giren few-shot örneklerini statik tek bir örnekten çıkarıp, her kolona
o kolona EN BENZER örnekleri koyacak dinamik bir yapıya taşımak. Havuz iki kaynaktan
beslenir:
  1. CURATED_EXAMPLES — bu dosyada elle, mevzuata (classifier/categories.py) referansla
     yazılmış banka veri sınıflandırma örnekleri. İnsan onayı beklemeden İLK GÜNDEN dolu.
  2. decisions.approved_records() — insan onayladıkça/düzelttikçe biriken kararlar.
     Havuz büyüdükçe kapsama otomatik genişler.

Retrieval token-Jaccard benzerliğine dayanır (rules.split_tokens ile aynı ayrıştırma):
kolon adları parçalanır (mhIbanNo → {mh, iban, no}), örnek havuzundaki adlarla kesişim/
birleşim oranı hesaplanır. Prompt bütçesi config.FEWSHOT_K ile SABİT — havuz binlerce
kayda büyüse de çağrı başına örnek maliyeti değişmez (şişme yapısal olarak engellenir).

Not: Örnekler "yol gösterici, bağlayıcı değil" çerçevesinde verilir (bkz.
prompts.render_decision_examples); model benzer ama bağlamı farklı bir kolonda kendi
kararını verir.
"""

import re

import config

from . import decisions
from .categories import CATEGORIES
from .rules import split_tokens

# Her örnek: kolon adı + veri tipi + doğru kategoriler/ana kategori + kısa gerekçe.
# gerekce, modele SADECE kategoriyi değil o kategoriye NEDEN girdiğini de öğretir.
# ana_kategori önceliği ve "2 içeren 1'i de içerir / kart PAN ana 3 / tüzel kişi 1-2 olamaz"
# gibi kurallar categories.py ve prompts.SYSTEM_PROMPT ile birebir tutarlıdır.
CURATED_EXAMPLES: list[dict] = [
    # --- 1. Kişisel Veri (gerçek kişi) ---
    # Not: Ayırt edici formatı olan örneklere temsili "ornek_degerler" eklenir — bunlar
    # içerik-imzası retrieval'ında kullanılır (kriptik adlı ama değerleri format olarak
    # eşleşen kolonlar da doğru örneğe ulaşsın diye). Değerler LLM'e GİTMEZ, yalnız
    # retrieval sinyalidir.
    {"kolon": "tcKimlikNo", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "ornek_degerler": ["12345678901", "98765432109", "45678912303"],
     "gerekce": "11 haneli TC kimlik no gerçek kişiyi belirler; kişisel veridir."},
    {"kolon": "adSoyad", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "ornek_degerler": ["Ahmet Yılmaz", "Ayşe Kaya", "Mehmet Demir"],
     "gerekce": "Ad-soyad gerçek kişiyi doğrudan belirler; kişisel veridir."},
    {"kolon": "dogumTarihi", "veri_tipi": "date", "kategoriler": [1], "ana_kategori": 1,
     "ornek_degerler": ["1985-04-12", "1990-11-03", "1978-07-29"],
     "gerekce": "Doğum tarihi kişiyi belirlenebilir kılar; kişisel veridir."},
    {"kolon": "cepTelefonNo", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "ornek_degerler": ["05321234567", "05439876543", "05051112233"],
     "gerekce": "Telefon numarası iletişim bilgisidir; kişisel veridir."},
    {"kolon": "ePostaAdresi", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "ornek_degerler": ["ahmet.yilmaz@example.com", "ayse@firma.com.tr"],
     "gerekce": "E-posta adresi kişisel iletişim verisidir."},
    {"kolon": "ikametAdresi", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "gerekce": "Adres gerçek kişiye ait kişisel veridir."},
    {"kolon": "anneKizlikSoyadi", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "gerekce": "Anne kızlık soyadı kişisel veridir (aynı zamanda güvenlik sorusu olabilir)."},
    {"kolon": "aracPlakaNo", "veri_tipi": "varchar", "kategoriler": [1], "ana_kategori": 1,
     "gerekce": "Araç plakası kişiye bağlanabilen kişisel veridir."},
    {"kolon": "musteriNo", "veri_tipi": "varchar", "kategoriler": [1, 5], "ana_kategori": 1,
     "ornek_degerler": ["100234567", "100987654"],
     "gerekce": "Müşteri no gerçek kişiyi belirler (kişisel) ve banka müşterisi olduğunu gösterir (müşteri sırrı)."},

    # --- 2. Özel Nitelikli Kişisel Veri (2 içeren her zaman 1'i de içerir) ---
    {"kolon": "kanGrubu", "veri_tipi": "varchar", "kategoriler": [1, 2], "ana_kategori": 2,
     "ornek_degerler": ["A Rh+", "0 Rh-", "AB Rh+"],
     "gerekce": "Kan grubu sağlık verisidir; KVKK m.6 özel nitelikli, aynı zamanda kişiseldir."},
    {"kolon": "saglikRaporKodu", "veri_tipi": "varchar", "kategoriler": [1, 2], "ana_kategori": 2,
     "gerekce": "Sağlık bilgisi özel nitelikli kişisel veridir."},
    {"kolon": "dinBilgisi", "veri_tipi": "varchar", "kategoriler": [1, 2], "ana_kategori": 2,
     "gerekce": "Din/inanç KVKK m.6 özel nitelikli kişisel veridir."},
    {"kolon": "sabikaKaydi", "veri_tipi": "varchar", "kategoriler": [1, 2], "ana_kategori": 2,
     "gerekce": "Ceza mahkûmiyeti/sabıka özel nitelikli kişisel veridir."},
    {"kolon": "parmakIziSablonu", "veri_tipi": "varbinary", "kategoriler": [1, 2], "ana_kategori": 2,
     "gerekce": "Parmak izi biyometrik veridir; özel nitelikli kişisel veridir."},
    {"kolon": "sendikaUyeligi", "veri_tipi": "varchar", "kategoriler": [1, 2], "ana_kategori": 2,
     "gerekce": "Sendika üyeliği KVKK m.6 özel nitelikli kişisel veridir."},

    # --- 3. Hassas Veri ---
    {"kolon": "maasTutari", "veri_tipi": "decimal", "kategoriler": [3], "ana_kategori": 3,
     "ornek_degerler": ["12500.00", "9800.50", "31250.75"],
     "gerekce": "Maaş/gelir kurum içi hassas kabul edilen veridir."},
    {"kolon": "krediNotSkoru", "veri_tipi": "int", "kategoriler": [3], "ana_kategori": 3,
     "gerekce": "Kredi notu/skoru hassas veridir."},
    {"kolon": "riskDerecesi", "veri_tipi": "varchar", "kategoriler": [3], "ana_kategori": 3,
     "gerekce": "Risk derecelendirmesi hassas veridir."},
    {"kolon": "otpKodu", "veri_tipi": "varchar", "kategoriler": [3, 7], "ana_kategori": 3,
     "ornek_degerler": ["482913", "006754", "719280"],
     "gerekce": "OTP tek kullanımlık kimlik doğrulama verisidir; hassas, şifreli saklanır."},
    {"kolon": "guvenlikSoruCevap", "veri_tipi": "varchar", "kategoriler": [3, 7], "ana_kategori": 3,
     "gerekce": "Güvenlik sorusu-cevabı kimlik doğrulamada kullanılır; hassas veridir."},
    {"kolon": "karaListeDurumu", "veri_tipi": "bit", "kategoriler": [3], "ana_kategori": 3,
     "gerekce": "Kara liste/istihbarat kaydı hassas veridir."},

    # --- 4. Banka Sırrı (bankanın kendi işleyişi) ---
    {"kolon": "faizMarjOrani", "veri_tipi": "decimal", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "İç fiyatlama/marj parametresi bankanın kendisine ait banka sırrıdır."},
    {"kolon": "komisyonParametre", "veri_tipi": "decimal", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "Komisyon parametresi bankaya ait banka sırrıdır."},
    {"kolon": "teftisRaporNo", "veri_tipi": "varchar", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "Teftiş/denetim raporu banka sırrıdır."},
    {"kolon": "stratejiPlanId", "veri_tipi": "int", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "Strateji ve iş planı bankaya ait banka sırrıdır."},
    {"kolon": "icLimitTutari", "veri_tipi": "decimal", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "Bankanın iç limitleri banka sırrıdır."},
    {"kolon": "riskModelParametre", "veri_tipi": "varchar", "kategoriler": [4], "ana_kategori": 4,
     "gerekce": "Risk modeli parametreleri bankaya ait banka sırrıdır."},

    # --- 5. Müşteri Sırrı ---
    {"kolon": "ibanNo", "veri_tipi": "varchar", "kategoriler": [5], "ana_kategori": 5,
     "ornek_degerler": ["TR330006100519786457841326", "TR120001009999901234567890"],
     "gerekce": "IBAN müşteri hesap bilgisidir; müşteri sırrıdır (TR+24 hane formatı)."},
    {"kolon": "hesapNo", "veri_tipi": "varchar", "kategoriler": [5], "ana_kategori": 5,
     "ornek_degerler": ["00012345678", "00098765432"],
     "gerekce": "Hesap numarası müşteri ilişkisini gösterir; müşteri sırrıdır."},
    {"kolon": "hesapBakiye", "veri_tipi": "decimal", "kategoriler": [5], "ana_kategori": 5,
     "ornek_degerler": ["15234.75", "980000.00", "-1250.40"],
     "gerekce": "Bakiye müşteriye özgü finansal veridir; müşteri sırrıdır."},
    {"kolon": "kartNo", "veri_tipi": "varchar", "kategoriler": [3, 5, 7], "ana_kategori": 3,
     "ornek_degerler": ["4508034567890123", "5406678912340987"],
     "gerekce": "Kart numarası (PAN) hassas veridir; müşteri sırrı ve şifreli saklanır, ana kategori 3."},
    {"kolon": "ekstreHareket", "veri_tipi": "varchar", "kategoriler": [5], "ana_kategori": 5,
     "gerekce": "Hesap hareketi/ekstre müşteri sırrıdır."},
    {"kolon": "teminatTutari", "veri_tipi": "decimal", "kategoriler": [5], "ana_kategori": 5,
     "gerekce": "Teminat bilgisi müşteri sırrıdır."},
    {"kolon": "mevduatBakiyesi", "veri_tipi": "decimal", "kategoriler": [5], "ana_kategori": 5,
     "gerekce": "Mevduat/yatırım bilgisi müşteri sırrıdır."},
    {"kolon": "musteriSegmentKodu", "veri_tipi": "varchar", "kategoriler": [5], "ana_kategori": 5,
     "gerekce": "Müşteri segmenti/limiti müşteri sırrıdır."},
    {"kolon": "tuzelVergiNo", "veri_tipi": "varchar", "kategoriler": [5], "ana_kategori": 5,
     "ornek_degerler": ["1234567890", "9876543210"],
     "gerekce": "Tüzel kişi (şirket) vergi no kişisel veri (1/2) OLAMAZ; müşteri bağlamında müşteri sırrıdır."},

    # --- 6. Gizli / Çok Gizli ---
    {"kolon": "erisimRolKodu", "veri_tipi": "varchar", "kategoriler": [6], "ana_kategori": 6,
     "gerekce": "Yetki/rol tanımı bilmesi gereken ilkesiyle korunan gizli veridir."},
    {"kolon": "icSorusturmaNo", "veri_tipi": "varchar", "kategoriler": [6], "ana_kategori": 6,
     "gerekce": "İç soruşturma/disiplin dosyası çok gizli veridir."},
    {"kolon": "sizmaTestiBulgu", "veri_tipi": "varchar", "kategoriler": [6], "ana_kategori": 6,
     "gerekce": "Güvenlik açığı/sızma testi kaydı çok gizli veridir."},
    {"kolon": "sifrelemeAnahtari", "veri_tipi": "varbinary", "kategoriler": [6, 7], "ana_kategori": 6,
     "gerekce": "Kriptografik anahtar çok gizlidir; şifreli saklanır (7 ile birlikte)."},
    {"kolon": "apiGizliAnahtar", "veri_tipi": "varchar", "kategoriler": [6, 7], "ana_kategori": 6,
     "gerekce": "API secret/gizli anahtar çok gizlidir; şifreli/tokenize saklanır."},

    # --- 7. Şifreli Veri (saklama biçimi) ---
    {"kolon": "parolaHash", "veri_tipi": "varchar", "kategoriler": [3, 7], "ana_kategori": 3,
     "ornek_degerler": ["$2b$12$eImiTXuWVxfM37uY4JANjQ", "5f4dcc3b5aa765d61d8327deb882cf99"],
     "gerekce": "Parola kimlik doğrulama verisidir (hassas); salted-hash olarak şifreli saklanır."},
    {"kolon": "pinBlok", "veri_tipi": "varchar", "kategoriler": [3, 7], "ana_kategori": 3,
     "gerekce": "PIN kimlik doğrulama verisidir; PIN blok olarak şifreli saklanır."},
    {"kolon": "cvvSifreli", "veri_tipi": "varchar", "kategoriler": [3, 5, 7], "ana_kategori": 3,
     "gerekce": "CVV kimlik doğrulama verisidir; müşteri kart bilgisi, şifreli saklanır."},
    {"kolon": "erisimTokeni", "veri_tipi": "varchar", "kategoriler": [7], "ana_kategori": 7,
     "gerekce": "Erişim token'ı tokenize/şifreli saklanan veridir."},
    {"kolon": "sertifikaOzelAnahtar", "veri_tipi": "varbinary", "kategoriler": [6, 7], "ana_kategori": 6,
     "gerekce": "Sertifika özel anahtarı çok gizlidir; şifreli saklanır."},

    # --- Teknik / işlemsel (yanlış pozitif önleme: en yakın kategori + teknik bayrağı) ---
    {"kolon": "satirVersiyon", "veri_tipi": "rowversion", "kategoriler": [6], "ana_kategori": 6,
     "teknik": True,
     "gerekce": "Teknik satır versiyonu; hiçbir kategoriye net girmez, en yakın iç sistem bilgisi."},
    {"kolon": "olusturmaZamani", "veri_tipi": "datetime", "kategoriler": [6], "ana_kategori": 6,
     "teknik": True,
     "gerekce": "Teknik oluşturma zaman damgası; işlemsel meta veridir."},
    {"kolon": "kayitDurumKodu", "veri_tipi": "int", "kategoriler": [6], "ana_kategori": 6,
     "teknik": True,
     "gerekce": "Teknik durum/statü kodu; içeriksel bir kişisel/müşteri verisi değildir."},
    {"kolon": "islemSiraNo", "veri_tipi": "bigint", "kategoriler": [6], "ana_kategori": 6,
     "teknik": True,
     "gerekce": "Teknik sıra/otomatik artan kimlik; işlemsel meta veridir."},
]


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    if not inter:
        return 0.0
    return len(inter) / len(a | b)


# --- İsim benzerliği: token-Jaccard + karakter n-gram (kısaltmalara dayanıklı) ---
# Token-Jaccard, "iban" gibi ORTAK TAM TOKEN'ları yakalar ama "cust"/"customer",
# "mus"/"musteri", "hsp"/"hesap" gibi ÖNEK/ALT-DİZİ kısaltmalarını kaçırır (token
# kümeleri kesişmez). Karakter trigramları bu örtüşmeyi yakalar: custno={cus,ust,stn,tno}
# ile customerno={cus,ust,sto,...} → cus,ust ortak. İki sinyalin MAKSİMUMU alınır;
# böylece hangi biçim eşleşirse eşleşsin isim ekseni skoru düşmez.

def _clean(name: str) -> str:
    """Ada karakter n-gramı için: küçük harf, yalnız harf/rakam."""
    return re.sub(r"[^0-9a-zçğıöşü]+", "", (name or "").lower())


def _char_ngrams(name: str, n: int = 3) -> set:
    s = _clean(name)
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _dice(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return (2 * inter) / (len(a) + len(b)) if inter else 0.0


def _name_similarity(tok_a: set, ng_a: set, tok_b: set, ng_b: set) -> float:
    return max(_jaccard(tok_a, tok_b), _dice(ng_a, ng_b))


# --- İçerik benzerliği: örnek değerlerin FORMAT İMZASI ---
# Kolon adı kriptik/anonim olsa bile (örn. "x113"), örnek değerlerin biçimi güçlü bir
# sinyaldir: 26 haneli TR-önekli → IBAN, 11 hane rakam → TCKN/telefon, "@" içeren →
# e-posta. İmza yalnız RETRIEVAL içindir; ham değerler zaten prompt'a ayrıca gider.

_LEN_BANDS = (4, 8, 12, 20, 30)


def _len_band(x: float) -> int:
    for i, b in enumerate(_LEN_BANDS):
        if x <= b:
            return i
    return len(_LEN_BANDS)


def _value_signature(values: list | None) -> dict | None:
    vals = [str(v).strip() for v in (values or []) if str(v).strip()]
    if not vals:
        return None
    n = len(vals)
    avg_len = sum(len(v) for v in vals) / n
    digit = sum(sum(c.isdigit() for c in v) / max(len(v), 1) for v in vals) / n
    alpha = sum(sum(c.isalpha() for c in v) / max(len(v), 1) for v in vals) / n
    at = sum("@" in v for v in vals) / n
    tr_iban = sum(
        v.replace(" ", "").upper().startswith("TR")
        and sum(c.isdigit() for c in v) >= 16
        for v in vals
    ) / n
    return {"len": avg_len, "digit": digit, "alpha": alpha, "at": at, "tr": tr_iban}


def _content_similarity(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    score = 0.0
    band_diff = abs(_len_band(a["len"]) - _len_band(b["len"]))
    if band_diff == 0:
        score += 0.35
    elif band_diff == 1:
        score += 0.15
    score += 0.30 * (1 - min(1.0, abs(a["digit"] - b["digit"])))
    score += 0.15 * (1 - min(1.0, abs(a["alpha"] - b["alpha"])))
    if a["at"] > 0.5 and b["at"] > 0.5:  # ikisi de e-posta biçiminde
        score += 0.20
    if a["tr"] > 0.5 and b["tr"] > 0.5:  # ikisi de IBAN biçiminde
        score += 0.30
    return min(1.0, score)


def _shape(rec: dict, kaynak: str) -> dict:
    """Curated veya insan kararını ortak few-shot örnek biçimine çevirir."""
    cats = [int(c) for c in (rec.get("kategoriler") or []) if int(c) in CATEGORIES]
    ana = rec.get("ana_kategori")
    ana = int(ana) if str(ana).isdigit() and int(ana) in CATEGORIES else (cats[0] if cats else None)
    return {
        "kolon": rec.get("kolon", ""),
        "veri_tipi": rec.get("veri_tipi", ""),
        "kategoriler": cats,
        "kategori_adlari": [CATEGORIES[c] for c in cats],
        "ana_kategori": ana,
        "ana_kategori_adi": CATEGORIES.get(ana, ""),
        "teknik": bool(rec.get("teknik")),
        "gerekce": str(rec.get("gerekce") or "")[:200],
        "ornek_degerler": rec.get("ornek_degerler") or [],  # yalnız içerik-imzası retrieval'ı için
        "kaynak": kaynak,  # "referans" | "onayla" | "duzelt"
    }


def _pool() -> list[dict]:
    """Curated referanslar + insan onaylı kararlar (tek havuz).

    Aynı (kolon, veri_tipi) imzasına sahip bir insan kararı varsa curated örneğin
    yerini alır — insan onayı otoriterdir."""
    human = [_shape(r, r.get("action", "onayla")) for r in decisions.approved_records()]
    human_keys = {(e["kolon"].strip().lower(), e["veri_tipi"].strip().lower()) for e in human}
    pool = list(human)
    for ex in CURATED_EXAMPLES:
        key = (ex["kolon"].strip().lower(), str(ex.get("veri_tipi", "")).strip().lower())
        if key not in human_keys:
            pool.append(_shape(ex, "referans"))
    return pool


# İçerik-imzası eksenine güven tavanı: yalnız formattan (isim olmadan) çıkarılan benzerlik
# hiçbir zaman tam kesinlik saymaz — güçlü bir isim eşleşmesi her zaman öne geçebilsin diye.
_CONTENT_WEIGHT = 0.9


def _rank(cols: list[dict]) -> list[tuple[float, dict]]:
    """Havuzdaki her örneği, verilen kolon grubuna EN YÜKSEK benzerliğiyle skorlar.

    Skor = maks(isim_benzerliği, _CONTENT_WEIGHT × içerik_imzası_benzerliği). İsim ekseni
    token-Jaccard ile karakter-trigramın maksimumudur (kısaltmalara dayanıklı); içerik
    ekseni örnek değerlerin format imzasıdır (kriptik/anonim adlarda devreye girer).
    Veri tipi de uyuşuyorsa küçük bir bonus eklenir."""
    batch = [
        {
            "tokens": set(split_tokens(c.get("kolon", ""))),
            "ngrams": _char_ngrams(c.get("kolon", "")),
            "dtype": str(c.get("veri_tipi", "")).strip().lower(),
            "sig": _value_signature(c.get("ornek_degerler")),
        }
        for c in cols
    ]
    scored: list[tuple[float, dict]] = []
    for ex in _pool():
        ex_tokens = set(split_tokens(ex["kolon"]))
        ex_ngrams = _char_ngrams(ex["kolon"])
        ex_type = str(ex.get("veri_tipi", "")).strip().lower()
        ex_sig = _value_signature(ex.get("ornek_degerler"))
        best = 0.0
        for c in batch:
            name_s = _name_similarity(ex_tokens, ex_ngrams, c["tokens"], c["ngrams"])
            content_s = _CONTENT_WEIGHT * _content_similarity(ex_sig, c["sig"])
            s = max(name_s, content_s)
            if s and ex_type and ex_type == c["dtype"]:
                s = min(1.0, s + 0.05)  # veri tipi de uyuşuyorsa küçük bonus
            if s > best:
                best = s
        if best > 0:
            scored.append((round(best, 3), ex))
    scored.sort(key=lambda t: -t[0])
    return scored


def retrieve(cols: list[dict], k: int | None = None, min_sim: float | None = None) -> list[dict]:
    """Prompt'a girecek few-shot örnekleri: gruba en benzer, eşiği geçen ≤ k örnek."""
    k = config.FEWSHOT_K if k is None else k
    threshold = config.FEWSHOT_MIN_SIM if min_sim is None else min_sim
    if k <= 0:
        return []
    return [ex for sim, ex in _rank(cols) if sim >= threshold][:k]


def nearest_for_column(
    col: dict, k: int = 3, min_sim: float | None = None
) -> list[dict]:
    """Tek bir kolon için en yakın örnekler — arayüzde "çağrılan en yakın kolonlar"
    olarak gösterilir. Her örneğe benzerlik skoru ("benzerlik") eklenir."""
    threshold = config.FEWSHOT_MIN_SIM if min_sim is None else min_sim
    out = []
    for sim, ex in _rank([col]):
        if sim < threshold:
            break
        # ornek_degerler yalnız içerik-imzası retrieval'ı içindir (curated'da temsili/
        # sahte değerler) — UI'ya sızmasın diye display kopyasından çıkarılır.
        out.append({k2: v for k2, v in ex.items() if k2 != "ornek_degerler"} | {"benzerlik": sim})
        if len(out) >= k:
            break
    return out
