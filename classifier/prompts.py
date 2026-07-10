"""LLM prompt şablonları."""

import hashlib
import json

from . import rules
from .categories import CATEGORY_DEFINITIONS

SYSTEM_PROMPT = f"""Sen bir bankada görevli, KVKK'ya, 5411 sayılı Bankacılık Kanunu'na ve BDDK
düzenlemelerine hâkim kıdemli bir veri sınıflandırma uzmanısın. Görevin, veritabanı kolonlarını
aşağıdaki 7 kategoriye göre sınıflandırmak ve her kolon için TEK BİR ANA KATEGORİ seçmek.

KATEGORİLER:
{CATEGORY_DEFINITIONS}

HER KOLON İÇİN ŞU 4 ADIMI SIRAYLA UYGULA:
ADIM 1 — AÇILIM: Kolon adının açılımını çıkarmayı dene; tablo adı, şema adı, bankacılık
  jargonu (mus=müşteri, hsp=hesap, krd=kredi, acc=account, cust=customer, txn=transaction)
  ve veri tipinden yararlan. Kolon başındaki önek çoğu zaman tablo adının kısaltmasıdır ama
  her zaman değil. AÇILIMDAN EMİN DEĞİLSEN ZORLAMA: "acilim" alanını null bırak; bu durumda
  veri tipi, uzunluk, PK/null bilgisi ve tablodaki komşu kolonlardan yürüyerek sınıflandır.
  Sana verilen "olası açılım" ve "sözlük eşleşmesi" ipuçları OTOMATİK üretilmiştir; eksik
  veya yanlış olabilir, körü körüne uyma. Kolon adı anlamsız/anonimleştirilmiş görünüyorsa
  (örn. "col_a1b2c3" gibi bir kod) isimden açılım çıkarmaya ÇALIŞMA; bu durumda tamamen
  "örnek değerler" (verilmişse), veri tipi ve uzunluğa dayan. Örnek değerler iki tür
  maskeyle gösterilir: rakam ağırlıklı değerlerde baş/son karakterler korunup ortası
  yıldızlanır (örn. "12*******34", IBAN'da "TR**...26"); metinsel değerlerde içerik hiç
  gösterilmez, yalnız desen verilir (büyük harf→X, küçük harf→x, rakam→9; örn. "9 Xx+"
  kan grubu deseni, "xxxx99@xxxxx.xxx" e-posta deseni olabilir). Maskeli hâliyle bile
  uzunluk, karakter deseni ve baş/son karakterler güçlü sınıflandırma sinyalidir —
  verilmişse mutlaka değerlendir.
ADIM 2 — OLASI KATEGORİLER: Kolonun girebileceği TÜM kategorileri belirle
  ("olasi_kategoriler" listesi).
ADIM 3 — ANA KATEGORİ: Olası kategorileri bir kez daha analiz et ve EN UYGUN TEK kategoriyi
  "ana_kategori" olarak seç. Birden fazla kategori eşit derecede uyuyorsa korunması en sıkı
  olanı seç; öncelik sırası: 2 > 3 > 7 > 5 > 4 > 6 > 1.
ADIM 4 — GÜVEN: "guven" alanına KARARININ doğruluğuna olan güvenini yaz (0-1). Teknik bir
  kolonu teknik olarak tanıdıysan güvenin yüksek olabilir; asıl düşük güven, kolonun ne
  tuttuğundan emin olamadığın durumdur.

KARAR KURALLARI:
- Her kolona en az bir olası kategori ve mutlaka bir ana kategori ata. Hiçbir kategori
  açıkça uymuyorsa (satır no, durum kodu, işlem/süreç kodu, versiyon, tarih damgası gibi
  teknik/işlemsel kolonlar) "teknik": true yaz ve EN YAKIN kategoriyi ana kategori seç.
- Kategori 2 olası listede varsa 1'i de ekle. Kategori 2 listesi sınırlı sayıdadır (KVKK
  m.6); listede olmayanı 2 yapma.
- Müşteri tablolarındaki gerçek kişi kimlik/iletişim bilgileri hem 1 hem 5'tir
  (kişinin banka müşterisi olduğunu gösteren her bilgi müşteri sırrıdır).
- Tüzel kişi (şirket) verisi 1 veya 2 OLAMAZ; müşteri bağlamındaysa 5'tir.
- Parola/PIN/kart verisi gibi kimlik doğrulama alanları tipik olarak 3 ve 7'ye girer
  (müşteriye aitse 5, banka sistemine/personeline aitse 6 da eklenir); ana kategori 3'tür.

ÇIKTI FORMATI:
SADECE geçerli bir JSON dizisi döndür; başka hiçbir metin, açıklama veya markdown yazma.
Her kolon için, giriş sırasıyla aynı olacak şekilde bir nesne:
[{{"kolon": "<kolon adı>", "acilim": "<açılım veya null>",
  "olasi_kategoriler": [<id'ler, en az 1>], "ana_kategori": <tek id>,
  "teknik": <true|false>, "guven": <0-1>, "gerekce": "<tek cümle Türkçe>"}}]
Girdi BİRDEN FAZLA "=== TABLO: ... ===" bölümü içeriyorsa (tek istekte birden çok küçük
tablo birleştirilmiş demektir), her nesneye ayrıca "tablo": "<o bölümün tablo adı>" ekle
— bu, hangi sonucun hangi tabloya ait olduğunu netleştirir. TABLOLAR ARASINDAKİ KOLONLARI
BİRBİRİNE KARIŞTIRMA; her bölümü yalnız kendi ŞEMA/TABLO bağlamıyla değerlendir.

ÖRNEK — TABLO: CustomerCard için girdi kolonları ccCardNo, ccCvvEnc, ccTaxNo, ccMarginRate, ccRowVer:
[{{"kolon":"ccCardNo","acilim":"Customer Card - Card Number","olasi_kategoriler":[3,5,7],"ana_kategori":3,"teknik":false,"guven":0.95,"gerekce":"Kart numarası (PAN) BDDK'ya göre hassas veridir; müşteri sırrıdır ve şifreli saklanması gerekir, ana kategori hassas veridir."}},
{{"kolon":"ccCvvEnc","acilim":"Customer Card - CVV (Encrypted)","olasi_kategoriler":[3,5,7],"ana_kategori":3,"teknik":false,"guven":0.95,"gerekce":"CVV kimlik doğrulama verisidir; şifreli saklanan müşteri kart bilgisidir."}},
{{"kolon":"ccTaxNo","acilim":"Customer Card - Tax Number","olasi_kategoriler":[1,5],"ana_kategori":1,"teknik":false,"guven":0.85,"gerekce":"Vergi no gerçek kişi müşteride kişisel veridir; müşteri ilişkisini de gösterir, ana kategori kişisel veridir."}},
{{"kolon":"ccMarginRate","acilim":"Customer Card - Margin Rate","olasi_kategoriler":[4],"ana_kategori":4,"teknik":false,"guven":0.75,"gerekce":"Bankanın iç fiyatlama marjı banka sırrıdır."}},
{{"kolon":"ccRowVer","acilim":null,"olasi_kategoriler":[6],"ana_kategori":6,"teknik":true,"guven":0.85,"gerekce":"Teknik versiyon kolonudur; hiçbir kategoriye net girmediğinden en yakın olarak iç sistem bilgisi sayıldı."}}]"""


def _render_column_line(i: int, c: dict) -> str:
    """Tek bir kolonun prompt satırını üretir (build_batch_prompt ve
    build_multi_table_prompt arasında paylaşılır)."""
    parts = [f"{i}. {c['kolon']}"]
    dtype = c.get("veri_tipi") or ""
    if dtype:
        length = c.get("uzunluk")
        parts.append(f"tip={dtype}{f'({length})' if length not in (None, '') else ''}")
    if str(c.get("pk", "")) == "1":
        parts.append("PK")
    if str(c.get("nullable", "")) == "0":
        parts.append("NOT NULL")
    if c.get("note"):
        parts.append(f"olası açılım (otomatik, hatalı olabilir): {c['note']}")
    if c.get("hints"):
        parts.append(f"sözlük eşleşmesi (otomatik, hatalı olabilir): {json.dumps(c['hints'], ensure_ascii=False)}")
    samples = [rules.mask_sample(s) for s in (c.get("ornek_degerler") or []) if str(s).strip()]
    if samples:
        parts.append(f"örnek değerler (maskeli): {', '.join(samples[:5])}")
    return " | ".join(parts)


def render_decision_examples(examples: list[dict] | None) -> list[str]:
    """İnsan onaylı benzer kararları few-shot bloğu olarak üretir (boşsa hiç üretmez).

    Bilinçli olarak "yol gösterici, bağlayıcı değil" çerçevesinde verilir: insan
    kararının güven=1.0 ağırlığı yalnız BİREBİR imza eşleşmesinde (karar sözlüğü,
    pipeline'da LLM'den önce) uygulanır; benzer-ama-farklı kolonda model kendi
    kararını verir. Örnek sayısı config.FEWSHOT_K ile sınırlı — prompt şişmez.
    """
    if not examples:
        return []
    lines = [
        "İNSAN ONAYLI ÖNCEKİ KARARLAR (benzer kolon adları için yol gösterici — "
        "bağlayıcı DEĞİL; kolonun tablosu/bağlamı farklıysa kendi kararını ver):",
    ]
    for ex in examples:
        label = "onaylandı" if ex.get("action") == "onayla" else "insan düzeltti"
        dtype = f" ({ex['veri_tipi']})" if ex.get("veri_tipi") else ""
        lines.append(
            f"- {ex.get('kolon', '?')}{dtype}: olası kategoriler={ex.get('kategoriler')}, "
            f"ana kategori={ex.get('ana_kategori')} [{label}]"
        )
    lines.append("")
    return lines


def build_batch_prompt(
    schema: str, table: str, columns: list[dict], examples: list[dict] | None = None
) -> str:
    """Bir tabloya ait kolon grubu için kullanıcı prompt'u.

    columns: [{kolon, veri_tipi, uzunluk, nullable, pk, note, hints, ornek_degerler}, ...]
    ornek_degerler verilmişse LLM'e gitmeden önce maskelenir (bkz. rules.mask_sample).
    examples: decisions.similar_decisions çıktısı — insan onaylı few-shot örnekleri.
    """
    lines = render_decision_examples(examples) + [
        f"ŞEMA: {schema or '-'}",
        f"TABLO: {table or '-'}",
        "",
        "KOLONLAR:",
    ]
    for i, c in enumerate(columns, 1):
        lines.append(_render_column_line(i, c))
    lines.append("")
    lines.append(
        f"Bu {len(columns)} kolonun tamamını sınıflandır ve aynı sırayla JSON dizisi döndür. "
        "Her kolonda 4 adımı uygula: açılım → olası kategoriler → tek ana kategori → güven."
    )
    return "\n".join(lines)


def build_multi_table_prompt(
    table_groups: list[tuple[str, str, list[dict]]], examples: list[dict] | None = None
) -> str:
    """Birden fazla KÜÇÜK tabloyu TEK istekte birleştirir (toplam kolon sayısı
    config.BATCH_SIZE sınırına kadar) — çağrı sayısını azaltıp gecikmeyi düşürmek için.

    table_groups: [(schema, table, columns), ...]. Her tablo kendi "=== TABLO: ... ==="
    bölümünde, kendi ŞEMA/TABLO bağlamıyla ayrı ayrı verilir; kolonlar GLOBAL sırayla
    numaralanır (1..N, tablo sınırları boyunca devam eder) ve model her nesneye "tablo"
    alanını da eklemeye yönlendirilir — bu, pipeline._classify_multi_group'un sonuçları
    doğru tabloya eşlemesini (isim çakışması olsa bile) sağlar.
    """
    total = sum(len(cols) for _, _, cols in table_groups)
    lines = render_decision_examples(examples) + [
        f"Bu istekte {len(table_groups)} farklı tabloya ait kolon grubu var (toplam {total} "
        "kolon). Her bölümü YALNIZ kendi ŞEMA/TABLO bağlamıyla değerlendir; tablolar "
        "arasındaki kolonları birbirine karıştırma.",
        "",
    ]
    n = 0
    for schema, table, columns in table_groups:
        lines.append(f"=== TABLO: {table or '-'} (ŞEMA: {schema or '-'}) ===")
        for c in columns:
            n += 1
            lines.append(_render_column_line(n, c))
        lines.append("")
    lines.append(
        f"Toplam {n} kolonun tamamını sınıflandır ve aynı sırayla JSON dizisi döndür; her "
        'nesneye hangi tabloya ait olduğunu belirten "tablo" alanını da ekle. Her kolonda '
        "4 adımı uygula: açılım → olası kategoriler → tek ana kategori → güven."
    )
    return "\n".join(lines)


JUDGE_SYSTEM_PROMPT = f"""Sen bankacılık veri sınıflandırmasında son sözü söyleyen kıdemli bir
denetçisin. Sana bir veritabanı kolonu ve düşük güvenle yapılmış ilk sınıflandırma denemesi
verilecek. Görevin adım adım düşünüp NİHAİ kararı vermek.

KATEGORİLER:
{CATEGORY_DEFINITIONS}

KURALLAR:
- Önce kolon adının olası açılımını düşün (tablo adı, bankacılık jargonu). Emin değilsen
  açılım uydurma (acilim=null); veri tipi ve bağlamdan yürü.
- Olası kategorileri belirle, sonra bir kez daha analiz ederek EN UYGUN TEK ana kategoriyi
  seç. Eşitlik hâlinde öncelik: 2 > 3 > 7 > 5 > 4 > 6 > 1.
- Teknik/işlemsel kolonsa "teknik": true yaz ve en yakın kategoriyi ana kategori yap.
- Kategori 2 varsa 1'i de ekle; tüzel kişi verisi 1/2 olamaz; müşteri bilgisi 5'tir.
- Kolon adı anlamsız/anonimleştirilmiş görünüyorsa (örn. "col_a1b2c3") isimden açılım
  çıkarmaya çalışma; "örnek değerler" verilmişse (maskeli olsa bile uzunluk/karakter
  sınıfı/baştaki-sondaki karakterler güçlü sinyaldir) ve veri tipine dayan.

Önce kolonun ne tutuyor olabileceğine dair 2-3 cümlelik akıl yürütme yap, sonra SON SATIRDA
sadece şu JSON'u yaz:
{{"acilim": "<açılım veya null>", "olasi_kategoriler": [<id'ler, en az 1>],
"ana_kategori": <tek id>, "teknik": <true|false>, "guven": <0-1>, "gerekce": "<tek cümle>"}}"""


def build_judge_prompt(schema: str, table: str, col: dict, first_pass: dict) -> str:
    samples = [rules.mask_sample(s) for s in (col.get("ornek_degerler") or []) if str(s).strip()]
    sample_line = f"Örnek değerler (maskeli): {', '.join(samples[:5])}\n" if samples else ""
    return (
        f"ŞEMA: {schema or '-'}\nTABLO: {table or '-'}\n"
        f"KOLON: {col['kolon']} | tip={col.get('veri_tipi') or '?'}"
        f" | PK={col.get('pk', '?')} | nullable={col.get('nullable', '?')}\n"
        f"Olası açılım (otomatik): {col.get('note') or '-'}\n"
        f"Sözlük eşleşmesi (otomatik): {json.dumps(col.get('hints') or {}, ensure_ascii=False)}\n"
        f"{sample_line}\n"
        f"İlk deneme: olası kategoriler={first_pass.get('kategoriler')}, "
        f"ana kategori={first_pass.get('ana_kategori')}, "
        f"guven={first_pass.get('guven')}, gerekce={first_pass.get('gerekce')!r}\n\n"
        "Nihai kararını ver."
    )


# SYSTEM_PROMPT veya JUDGE_SYSTEM_PROMPT metni değiştiğinde bu hash otomatik değişir.
# pipeline._cache_key bunu model adıyla birlikte önbellek anahtarına ekler; aksi hâlde
# prompt güncellendiğinde eski (artık geçersiz) LLM kararları sessizce önbellekte kalırdı.
PROMPT_VERSION = hashlib.sha256(
    (SYSTEM_PROMPT + JUDGE_SYSTEM_PROMPT).encode("utf-8")
).hexdigest()[:12]
