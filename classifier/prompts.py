"""LLM prompt şablonları."""

import json

from .categories import CATEGORY_DEFINITIONS

SYSTEM_PROMPT = f"""Sen bir bankada görevli, KVKK'ya, 5411 sayılı Bankacılık Kanunu'na ve BDDK
düzenlemelerine hâkim kıdemli bir veri sınıflandırma uzmanısın. Görevin, veritabanı kolonlarını
aşağıdaki 7 kategoriye göre sınıflandırmak ve her kolon için TEK BİR ANA KATEGORİ seçmek.

KATEGORİLER:
{CATEGORY_DEFINITIONS}

HER KOLON İÇİN ŞU 3 ADIMI SIRAYLA UYGULA:
ADIM 1 — AÇILIM: Kolon adının açılımını çıkarmayı dene; tablo adı, şema adı, bankacılık
  jargonu (mus=müşteri, hsp=hesap, krd=kredi, acc=account, cust=customer, txn=transaction)
  ve veri tipinden yararlan. Kolon başındaki önek çoğu zaman tablo adının kısaltmasıdır ama
  her zaman değil. AÇILIMDAN EMİN DEĞİLSEN ZORLAMA: "acilim" alanını null bırak; bu durumda
  veri tipi, uzunluk, PK/null bilgisi ve tablodaki komşu kolonlardan yürüyerek sınıflandır.
  Sana verilen "olası açılım" ve "sözlük eşleşmesi" ipuçları OTOMATİK üretilmiştir; eksik
  veya yanlış olabilir, körü körüne uyma. Kolon adı anlamsız/anonimleştirilmiş görünüyorsa
  (örn. "col_a1b2c3" gibi bir kod) isimden açılım çıkarmaya ÇALIŞMA; bu durumda tamamen
  "örnek değerler" (verilmişse), veri tipi ve uzunluğa dayan. Örnek değerler ham olarak
  verilir (yerel ortamda çalışıyoruz, maskeleme yok); uzunluk, karakter deseni, format
  (örn. "TR" ile başlayan 26 haneli IBAN, 11 haneli TCKN, kredi kartı numarası) ve değer
  aralığı güçlü sınıflandırma sinyalleridir — verilmişse mutlaka değerlendir.
ADIM 2 — OLASI KATEGORİLER (OLASILIK DAĞILIMI): Kolonun girebileceği TÜM kategorileri
  belirle ve her birine [0,1] arası bir olasılık ata; olasılıkların TOPLAMI 1.0 olmalı.
  Yalnız %1'den küçük olasılıkları listeye ALMA. Örnek:
    "olasi_kategoriler": [{{"id": 1, "olasilik": 0.92}},
                          {{"id": 5, "olasilik": 0.06}},
                          {{"id": 3, "olasilik": 0.02}}]
  Gerçekten emin olduğunda tek kategoriye ~1.0 ver, diğerlerine 0 (yani listeleme).
  Eşit olasılıklı birden fazla kategori varsa (örn. [0.45, 0.40, 0.15]) bu, sistem
  tarafından "gerçek belirsizlik" sayılıp ikinci görüş (hakem) ile kontrol edilir —
  bu yüzden olasılıkları dürüstçe ver, yapay olarak birine şişirme.
ADIM 3 — ANA KATEGORİ: Olasılık dağılımını bir kez daha analiz et ve EN UYGUN TEK
  kategoriyi "ana_kategori" olarak seç. Olasılıklar çok yakınsa (örn. 0.45 vs 0.40)
  korunması en sıkı olanı seç; öncelik sırası: 2 > 3 > 5 > 4 > 6 > 7 > 1.
NOT: "guven" alanı DÖNDÜRME — sistem, güveni olasılık dağılımından otomatik türetir.

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
- 7 SAKLAMA BİÇİMİDİR, İÇERİK SINIFI DEĞİL: içerik sınıfı olan her kolonda ana kategori
  içerik sınıfıdır (parola hash'i → ana 3; tokenize hesap no → ana 5; şifreleme
  anahtarı → ana 6) ve 7 olası listede eşlik eder. Ana kategori 7'yi YALNIZCA içerik
  sınıfı taşımayan saf kripto artefaktlarında seç (salt, IV, sertifika parmak izi).
- Bankanın MÜŞTERİ hakkında ürettiği skor/istihbarat (kredi notu, risk derecesi, kara
  liste) → 3 + 5; 6 DEĞİL. PERSONELE ait maaş/performans → 1 + 3; 4 DEĞİL.

ÇIKTI FORMATI:
SADECE geçerli bir JSON dizisi döndür; başka hiçbir metin, açıklama veya markdown yazma.
Her kolon için, giriş sırasıyla aynı olacak şekilde bir nesne:
[{{"kolon": "<kolon adı>", "acilim": "<açılım veya null>",
  "olasi_kategoriler": [{{"id": <kategori_id>, "olasilik": <0-1>}}, ...],
  "ana_kategori": <tek id>,
  "teknik": <true|false>, "gerekce": "<tek cümle Türkçe>"}}]
"guven" alanı DÖNDÜRME (sistem dağılımdan otomatik türetir).
Olasılıklar toplamı 1.0 olmalı; %1'den küçük olasılıkları listeleME.
Girdi BİRDEN FAZLA "=== TABLO: ... ===" bölümü içeriyorsa (tek istekte birden çok küçük
tablo birleştirilmiş demektir), her nesneye ayrıca "tablo": "<o bölümün tablo adı>" ekle
— bu, hangi sonucun hangi tabloya ait olduğunu netleştirir. TABLOLAR ARASINDAKİ KOLONLARI
BİRBİRİNE KARIŞTIRMA; her bölümü yalnız kendi ŞEMA/TABLO bağlamıyla değerlendir.

ÖRNEK — TABLO: CustomerCard için girdi kolonları ccCardNo, ccCvvEnc, ccTaxNo, ccMarginRate, ccRowVer:
[{{"kolon":"ccCardNo","acilim":"Customer Card - Card Number","olasi_kategoriler":[{{"id":3,"olasilik":0.70}},{{"id":5,"olasilik":0.20}},{{"id":7,"olasilik":0.10}}],"ana_kategori":3,"teknik":false,"gerekce":"Kart numarası (PAN) BDDK'ya göre hassas veridir; müşteri sırrıdır ve şifreli saklanması gerekir, ana kategori hassas veridir."}},
{{"kolon":"ccCvvEnc","acilim":"Customer Card - CVV (Encrypted)","olasi_kategoriler":[{{"id":3,"olasilik":0.60}},{{"id":7,"olasilik":0.35}},{{"id":5,"olasilik":0.05}}],"ana_kategori":3,"teknik":false,"gerekce":"CVV kimlik doğrulama verisidir; şifreli saklanan müşteri kart bilgisidir."}},
{{"kolon":"ccTaxNo","acilim":"Customer Card - Tax Number","olasi_kategoriler":[{{"id":1,"olasilik":0.55}},{{"id":5,"olasilik":0.45}}],"ana_kategori":1,"teknik":false,"gerekce":"Vergi no gerçek kişi müşteride kişisel veridir; ancak müşteri ilişkisini de gösterir, iki kategori arasında yakın olasılık."}},
{{"kolon":"ccMarginRate","acilim":"Customer Card - Margin Rate","olasi_kategoriler":[{{"id":4,"olasilik":1.00}}],"ana_kategori":4,"teknik":false,"gerekce":"Bankanın iç fiyatlama marjı banka sırrıdır."}},
{{"kolon":"ccRowVer","acilim":null,"olasi_kategoriler":[{{"id":6,"olasilik":1.00}}],"ana_kategori":6,"teknik":true,"gerekce":"Teknik versiyon kolonudur; hiçbir kategoriye net girmediğinden en yakın olarak iç sistem bilgisi sayıldı."}}]"""


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
    samples = [str(s).strip() for s in (c.get("ornek_degerler") or []) if str(s).strip()]
    if samples:
        parts.append(f"örnek değerler: {', '.join(samples[:5])}")
    return " | ".join(parts)


def build_batch_prompt(schema: str, table: str, columns: list[dict]) -> str:
    """Bir tabloya ait kolon grubu için kullanıcı prompt'u.

    columns: [{kolon, veri_tipi, uzunluk, nullable, pk, note, hints, ornek_degerler}, ...]
    ornek_degerler verilmişse ham olarak LLM'e gönderilir (yerel ortam, maskeleme yok).
    """
    lines = [
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
        "Her kolonda 3 adımı uygula: açılım → olası kategoriler (olasılıklarla) → tek ana kategori."
    )
    return "\n".join(lines)


def build_multi_table_prompt(table_groups: list[tuple[str, str, list[dict]]]) -> str:
    """Birden fazla KÜÇÜK tabloyu TEK istekte birleştirir (toplam kolon sayısı
    config.BATCH_SIZE sınırına kadar) — çağrı sayısını azaltıp gecikmeyi düşürmek için.

    table_groups: [(schema, table, columns), ...]. Her tablo kendi "=== TABLO: ... ==="
    bölümünde, kendi ŞEMA/TABLO bağlamıyla ayrı ayrı verilir; kolonlar GLOBAL sırayla
    numaralanır (1..N, tablo sınırları boyunca devam eder) ve model her nesneye "tablo"
    alanını da eklemeye yönlendirilir — bu, pipeline._classify_multi_group'un sonuçları
    doğru tabloya eşlemesini (isim çakışması olsa bile) sağlar.
    """
    total = sum(len(cols) for _, _, cols in table_groups)
    lines = [
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
        "3 adımı uygula: açılım → olası kategoriler (olasılıklarla) → tek ana kategori."
    )
    return "\n".join(lines)


JUDGE_SYSTEM_PROMPT = f"""Sen bankacılık veri sınıflandırmasında son sözü söyleyen kıdemli bir
denetçisin. Sana bir veritabanı kolonu ve olasılık dağılımı belirsiz görünen bir ilk
sınıflandırma denemesi verilecek. Görevin adım adım düşünüp NİHAİ kararı vermek.

KATEGORİLER:
{CATEGORY_DEFINITIONS}

KURALLAR:
- Önce kolon adının olası açılımını düşün (tablo adı, bankacılık jargonu). Emin değilsen
  açılım uydurma (acilim=null); veri tipi ve bağlamdan yürü.
- Olası kategorileri OLASILIK DAĞILIMI olarak belirle (toplam 1.0, %1'in altı listelenmez),
  sonra bir kez daha analiz ederek EN UYGUN TEK ana kategoriyi seç. Eşitlik hâlinde
  öncelik: 2 > 3 > 5 > 4 > 6 > 7 > 1.
- Teknik/işlemsel kolonsa "teknik": true yaz ve en yakın kategoriyi ana kategori yap.
- Kategori 2 varsa 1'i de ekle; tüzel kişi verisi 1/2 olamaz; müşteri bilgisi 5'tir.
- Kolon adı anlamsız/anonimleştirilmiş görünüyorsa (örn. "col_a1b2c3") isimden açılım
  çıkarmaya çalışma; "örnek değerler" verilmişse (ham değerler; uzunluk, format ve
  değer aralığı güçlü sinyaldir) ve veri tipine dayan.

Önce kolonun ne tutuyor olabileceğine dair 2-3 cümlelik akıl yürütme yap, sonra SON SATIRDA
sadece şu JSON'u yaz:
{{"acilim": "<açılım veya null>",
 "olasi_kategoriler": [{{"id": <kategori_id>, "olasilik": <0-1>}}, ...],
 "ana_kategori": <tek id>, "teknik": <true|false>,
 "gerekce": "<tek cümle>"}}
"guven" alanı DÖNDÜRME — sistem, güveni olasılık dağılımından otomatik türetir.
Olasılıklar toplamı 1.0 olmalı; %1'den küçük olasılıkları listeleME."""


def build_judge_prompt(schema: str, table: str, col: dict, first_pass: dict) -> str:
    samples = [str(s).strip() for s in (col.get("ornek_degerler") or []) if str(s).strip()]
    sample_line = f"Örnek değerler: {', '.join(samples[:5])}\n" if samples else ""
    # Olasılık dağılımı (yeni format) — ilk denemedeki dağılımı hakeme göster ki
    # hangi kategorilerin yakın/uzak olduğunu bilsin.
    olas = first_pass.get("olasiliklar") or {}
    if olas:
        sorted_dist = sorted(olas.items(), key=lambda kv: -kv[1])
        dagilim_str = ", ".join(f"{cid}:{p:.2f}" for cid, p in sorted_dist)
    else:
        dagilim_str = ", ".join(f"{c}:?" for c in (first_pass.get("kategoriler") or []))
    return (
        f"ŞEMA: {schema or '-'}\nTABLO: {table or '-'}\n"
        f"KOLON: {col['kolon']} | tip={col.get('veri_tipi') or '?'}"
        f" | PK={col.get('pk', '?')} | nullable={col.get('nullable', '?')}\n"
        f"Olası açılım (otomatik): {col.get('note') or '-'}\n"
        f"Sözlük eşleşmesi (otomatik): {json.dumps(col.get('hints') or {}, ensure_ascii=False)}\n"
        f"{sample_line}\n"
        f"İlk deneme: olasılık dağılımı={{{dagilim_str}}}, "
        f"ana kategori={first_pass.get('ana_kategori')}, "
        f"guven={first_pass.get('guven')}, gerekce={first_pass.get('gerekce')!r}\n\n"
        "Nihai kararını ver."
    )
