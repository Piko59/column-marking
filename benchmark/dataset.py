"""Golden benchmark veri seti.

Amaç: LLM sınıflandırıcının üç farklı sinyal koşulunda ne kadar isabetli olduğunu
ölçmek —
  1. yalnız İSİM (kolon/tablo/şema adı anlamlı ama örnek değer yok)
  2. yalnız İÇERİK (isim anonimleştirilmiş/anlamsız, yalnız örnek değerler var)
  3. İSİM + İÇERİK birlikte

Bunun için her "kavram" (örn. "TC Kimlik No") TEK YERDE tanımlanır (doğru kategori +
gerçekçi örnek değerler ortak) ve İKİ isim muamelesiyle eşleştirilir:
  - "named"  grubu: gerçekçi banka/kurum adlandırması (ör. mhIban, tablo MusteriHesap,
    şema core) — kullanıcının verdiği örnek: tmTermType, DepAccDBp2, ccID gibi.
  - "random" grubu: isimden hiçbir anlam çıkarılamayan kod (ör. kolon x113, tablo
    tbl9f2, şema z11).
Aynı kavramın named/random sürümü AYNI içeriğe sahiptir — bu eşleştirme (pairing),
"ismi kaldırınca doğruluk ne kadar düşüyor" sorusunu kavram bazında ölçmeyi sağlar.

7 resmî kategori (categories.CATEGORIES) için 7'şer kavram = 49 kavram, + 1 "teknik"
kova (7 kavram) — bu kova YANLIŞ POZİTİF riskini ölçer: sıradan/işlemsel kolonları
(satır versiyonu, oluşturma tarihi, durum kodu...) modelin gereksiz yere hassas/gizli
diye işaretleyip işaretlemediğini test eder. Toplam 56 kavram × 2 isim grubu = 112 satır.

Ground truth (ana_kategori / kategoriler / teknik) her kavram için elle, mevzuat
tanımlarına (classifier/categories.py) referansla belirlenmiştir; her satırda kısa bir
"gerekce" ile belgelenmiştir — bu, sonradan insan denetimi/itirazı için gereklidir.

GROUND TRUTH v2 (Temmuz 2026): BDDK BSEBY m.9/3 dayanağıyla içerik-öncelikli kural
uygulandı — şifreli saklama bir YÜKÜMLÜLÜKTÜR, içerik sınıfı değil. "7" kovasındaki
kavramların ana kategorisi artık içerik sınıfıdır (parola hash → 3, API anahtarı → 6,
tokenize hesap no → 5); yalnız saf kripto artefaktı (sertifika parmak izi) ana=7 kalır.
Kova 3'e kişisel/müşteri eş-etiketleri eklendi (maaş → 1+3, kredi skoru → 3+5 vb.).
Bu sürümle eski benchmark koşuları doğrudan karşılaştırılamaz.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Concept:
    key: str                 # benzersiz kısa kod, örn. "c1_tckn"
    bucket: str               # "1".."7" (categories.CATEGORIES id'si) veya "teknik"
    ana_kategori: int | None  # doğru ana kategori (teknik kovada da dolu — "en yakın")
    kategoriler: list[int]    # doğru olası kategoriler kümesi (ana dahil)
    teknik: bool
    named_schema: str
    named_table: str
    named_column: str
    veri_tipi: str
    uzunluk: str
    sample_values: list[str]  # ham örnek değerler; LLM'e ham olarak gider (yerel/banka içi)
    gerekce: str
    random_schema: str = ""
    random_table: str = ""
    random_column: str = ""


# --- İsimsizleştirme şeması: aynı NAMED tablo/şema her zaman aynı rastgele koda düşer ---
# (tablo bazlı gruplama pipeline'da önemli; eşleştirme somut ve tekrarlanabilir olmalı)
_SCHEMA_MAP = {
    "hr": "z11", "risk": "z22", "yonetim": "z33", "core": "z44",
    "guvenlik": "z55", "sys": "z66",
}
_TABLE_MAP = {
    "Personel": "tbl9f2", "PersonelSaglik": "tblq88", "OperasyonRisk": "tblr3c",
    "StratejiPlan": "tbla41", "MusteriHesap": "tblc90", "MusteriKredi": "tblk17",
    "IcSorusturma": "tbld55", "ErisimYonetimi": "tble62", "GuvenlikKimlik": "tblg74",
    "MusteriKartSifreli": "tblm38", "SistemLog": "tbls09",
}


def _rnd_column(n: int) -> str:
    return f"x{100 + n}"


_RAW: list[Concept] = [
    # ============ 1. KİŞİSEL VERİ — Personel (HR) bağlamı, müşteri değil ============
    Concept("c1_adsoyad", "1", 1, [1], False, "hr", "Personel", "persAdSoyad",
            "varchar", "100",
            ["Ahmet Yılmaz", "Zeynep Kaya", "Mehmet Demir"],
            "Gerçek kişiye ait ad-soyad; personel bağlamında, müşteri ilişkisi yok → yalnız 1."),
    Concept("c1_tckn", "1", 1, [1], False, "hr", "Personel", "persTcKimlikNo",
            "char", "11",
            ["10000000146", "12345678950", "19273465830"],
            "TC kimlik no; KVKK m.3/d kapsamında doğrudan kişisel veri (11 haneli sayısal)."),
    Concept("c1_dogumtarihi", "1", 1, [1], False, "hr", "Personel", "persDogumTarihi",
            "date", "",
            ["1988-07-22", "1975-11-03", "1990-02-14"],
            "Doğum tarihi kişisel veridir."),
    Concept("c1_telefon", "1", 1, [1], False, "hr", "Personel", "persCepTel",
            "varchar", "15",
            ["+905321234567", "+905551112233", "+905469876543"],
            "Cep telefonu numarası doğrudan kişisel veridir."),
    Concept("c1_adres", "1", 1, [1], False, "hr", "Personel", "persIkametAdres",
            "varchar", "250",
            ["Bağdat Cad. No:45 Kadıköy/İstanbul", "Atatürk Blv. No:12 Çankaya/Ankara",
             "Cumhuriyet Mah. 5.Sk No:8 Bornova/İzmir"],
            "İkametgah adresi kişisel veridir."),
    Concept("c1_eposta", "1", 1, [1], False, "hr", "Personel", "persKisiselEposta",
            "varchar", "100",
            ["ahmety85@gmail.com", "zeynepk@hotmail.com", "mdemir90@yahoo.com"],
            "Kişisel e-posta adresi kişisel veridir."),
    Concept("c1_plaka", "1", 1, [1], False, "hr", "Personel", "persAracPlaka",
            "varchar", "10",
            ["34 ABC 123", "06 XYZ 456", "35 DEF 789"],
            "Araç plakası KVKK kapsamında kişisel veri örnekleri arasında sayılır."),

    # ============ 2. ÖZEL NİTELİKLİ — Personel/Sağlık bağlamı (her zaman 1'i de içerir) ============
    Concept("c2_kangrubu", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsKanGrubu",
            "varchar", "5",
            ["0 Rh+", "A Rh-", "AB Rh+"],
            "Kan grubu KVKK m.6 sağlık verisi kapsamında özel nitelikli kişisel veridir."),
    Concept("c2_din", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsDinBilgisi",
            "varchar", "30",
            ["İslam", "Hristiyanlık", "Belirtilmemiş"],
            "Din/mezhep bilgisi KVKK m.6'da sayılı özel nitelikli kişisel veridir."),
    Concept("c2_sendika", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsSendikaUyelik",
            "varchar", "50",
            ["Banka-Sen Üyesi", "Üye Değil", "Finans-İş Üyesi"],
            "Sendika üyeliği KVKK m.6'da sayılı özel nitelikli kişisel veridir."),
    Concept("c2_sabika", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsAdliSicil",
            "varchar", "100",
            ["Kaydı Yok", "Trafik cezası kaydı mevcut", "Kaydı Yok"],
            "Ceza mahkûmiyeti/adli sicil KVKK m.6'da sayılı özel nitelikli kişisel veridir."),
    Concept("c2_biyometrik", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsParmakIzi",
            "varchar", "128",
            ["Qz9JzT4mR8pLxVn2wKq7YbZc1sUeAoIhGtRfDj==",
             "Wk1lQm9uZFR5cGVYWjQ0MjE3ODkwMTIzNDU2Nzg=",
             "Vm9pY2VQcmludF9YWjk4NzY1NDMyMTA5ODc2NTQ="],
            "Parmak izi şablonu KVKK m.6 biyometrik veri kapsamındadır."),
    Concept("c2_engellilik", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsEngellilikDurum",
            "varchar", "50",
            ["Yok", "Ortopedik Engelli %35", "İşitme Engelli %20"],
            "Engellilik durumu sağlık verisi olarak özel nitelikli kişisel veridir."),
    Concept("c2_genetik", "2", 2, [1, 2], False, "hr", "PersonelSaglik", "phsGenetikTest",
            "varchar", "50",
            ["rs1234567:AA", "rs7412392:GT", "rs9876543:CC"],
            "Genetik test sonucu (SNP genotip notasyonu) KVKK m.6 genetik veri kapsamındadır."),

    # ============ 3. HASSAS VERİ — Personel (maaş/performans/güvenlik) + Operasyon Risk ============
    Concept("c3_maas", "3", 3, [1, 3], False, "hr", "Personel", "persNetMaas",
            "decimal", "10,2",
            ["18750.00", "22300.50", "15600.75"],
            "Personel maaşı gerçek kişiye ait ekonomik veridir (1); kurum içi tasnifle hassas (3) kabul edilir — BDDK m.3/o lafzı müşteri verisiyle sınırlıdır, bu bir iç genişletmedir."),
    Concept("c3_performans", "3", 3, [1, 3], False, "hr", "Personel", "persPerformansNotu",
            "decimal", "3,1",
            ["4.2", "3.7", "4.8"],
            "Personel performans notu gerçek kişiye ait veridir (1); kurum içi tasnifle hassas (3) kabul edilir."),
    Concept("c3_guvenlikcevap", "3", 3, [1, 3, 7], False, "hr", "Personel", "persGuvenlikCevap",
            "varchar", "100",
            ["Annemin kızlık soyadı Demir", "İlk evcil hayvanım Boncuk", "Doğduğum şehir Trabzon"],
            "Güvenlik sorusu cevabı kimlik doğrulama verisidir (3); içeriği kişisel bilgidir (1) ve BSEBY m.9/3 gereği şifreli saklanmalıdır (7)."),
    Concept("c3_otp", "3", 3, [3, 7], False, "hr", "Personel", "persOtpKod",
            "char", "6",
            ["482913", "091827", "657320"],
            "Tek kullanımlık şifre (OTP) BDDK hassas veri tanımının çekirdeğidir; şifreli saklanması gerekir (7)."),
    Concept("c3_findeksskor", "3", 3, [3, 5], False, "risk", "OperasyonRisk", "oprFindeksSkor",
            "int", "",
            ["1250", "890", "1580"],
            "Bankanın müşteri hakkında ürettiği kredi skoru: kurum içi hassas (3) + müşteri sırrı (5); 6 değildir."),
    Concept("c3_karaliste", "3", 3, [3, 5], False, "risk", "OperasyonRisk", "oprKaraListe",
            "varchar", "50",
            ["KL-04 Dolandırıcılık Şüphesi", "Kayıt Yok", "KL-11 Sahte Belge"],
            "Müşteri kara liste/istihbarat kaydı: kurum içi hassas (3) + müşteri sırrı (5); 6 değildir."),
    Concept("c3_risknotu", "3", 3, [3, 5], False, "risk", "OperasyonRisk", "oprRiskNotu",
            "varchar", "10",
            ["B2", "AA", "C1"],
            "Müşteri risk derecelendirme notu: kurum içi hassas (3) + müşteri sırrı (5); 6 değildir."),

    # ============ 4. BANKA SIRRI — bankanın kendi iç işleyişi, müşteriye ait değil ============
    Concept("c4_marj", "4", 4, [4], False, "yonetim", "StratejiPlan", "spFaizMarj",
            "decimal", "5,2",
            ["2.75", "3.10", "1.95"],
            "İç fiyatlama/marj parametresi 5411 s.K. m.73 kapsamında banka sırrıdır."),
    Concept("c4_komisyonoran", "4", 4, [4], False, "yonetim", "StratejiPlan", "spIcKomisyonOran",
            "decimal", "5,2",
            ["0.85", "1.20", "0.65"],
            "İç komisyon oranı banka sırrı kapsamındaki fiyatlama parametresidir."),
    Concept("c4_stratejiplan", "4", 4, [4], False, "yonetim", "StratejiPlan", "spYillikPlanOzet",
            "varchar", "500",
            ["2026 büyüme hedefi %12, KOBİ segmentine odaklan",
             "Dijital kanal yatırımı öncelikli, şube sayısı azaltılacak",
             "Kurumsal bankacılıkta pazar payı artışı hedefleniyor"],
            "Kamuya açıklanmamış stratejik plan banka sırrıdır."),
    Concept("c4_teftisraporu", "4", 4, [4], False, "yonetim", "StratejiPlan", "spTeftisBulgu",
            "varchar", "500",
            ["Şube nakit sayım farkı tespit edildi, düzeltici işlem uygulandı",
             "Kredi tahsis sürecinde onay atlanması bulgusu",
             "Bilgi güvenliği politikasına aykırılık tespit edildi"],
            "Teftiş/denetim bulgusu 5411 s.K. m.73 kapsamında banka sırrıdır."),
    Concept("c4_riskmodelparam", "4", 4, [4], False, "yonetim", "StratejiPlan", "spRiskModelParam",
            "decimal", "6,4",
            ["0.0342", "0.0187", "0.0523"],
            "Risk modeli parametresi banka sırrı kapsamındaki iç yönteme ilişkin bilgidir."),
    Concept("c4_iclimit", "4", 4, [4], False, "yonetim", "StratejiPlan", "spIcKrediLimit",
            "decimal", "12,2",
            ["5000000.00", "12000000.00", "3500000.00"],
            "İç kredi limit parametresi bankanın kendi faaliyet esaslarına ilişkin banka sırrıdır."),
    Concept("c4_ucretpolitikasi", "4", 4, [4], False, "yonetim", "StratejiPlan", "spUcretPolitika",
            "varchar", "50",
            ["Kıdem Bandı 3 - %8 Zam", "Kıdem Bandı 5 - %12 Zam", "Kıdem Bandı 1 - %5 Zam"],
            "İnsan kaynakları ücret politikası banka sırrı tanımında açıkça sayılmıştır."),

    # ============ 5. MÜŞTERİ SIRRI — müşteri hesap/işlem verisi ============
    Concept("c5_hesapno", "5", 5, [5], False, "core", "MusteriHesap", "mhHesapNo",
            "varchar", "20",
            ["8012345678", "8098765432", "8055512345"],
            "Müşteri hesap numarası müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_iban", "5", 5, [5], False, "core", "MusteriHesap", "mhIban",
            "varchar", "26",
            ["TR330006100519786457841326", "TR120001200945678901234567", "TR980010300123456789012345"],
            "IBAN müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_bakiye", "5", 5, [5], False, "core", "MusteriHesap", "mhBakiye",
            "decimal", "15,2",
            ["124560.75", "8900.00", "2450000.30"],
            "Hesap bakiyesi müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_ekstre", "5", 5, [5], False, "core", "MusteriHesap", "mhEkstreAciklama",
            "varchar", "200",
            ["15.03.2026 Market alışverişi -450.00 TL", "20.03.2026 Maaş yatışı +18750.00 TL",
             "22.03.2026 Fatura ödemesi -320.50 TL"],
            "Hesap hareketi/ekstre açıklaması müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_eft", "5", 5, [5], False, "core", "MusteriHesap", "mhEftHavaleNo",
            "varchar", "30",
            ["EFT2026031500123", "HVL2026031800456", "EFT2026032100789"],
            "EFT/havale kayıt no müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_krediodeme", "5", 5, [5], False, "core", "MusteriKredi", "mkGeriOdemeTutar",
            "decimal", "12,2",
            ["3450.00", "1200.50", "5670.25"],
            "Kredi geri ödeme tutarı müşteri sırrı tanımında açıkça sayılmıştır."),
    Concept("c5_teminat", "5", 5, [5], False, "core", "MusteriKredi", "mkTeminatBilgi",
            "varchar", "200",
            ["İpotek: Kadıköy 3.Levent 120m2 daire", "Araç Rehni: 34 ABC 123 2022 model",
             "Kefil: Ahmet Yılmaz"],
            "Teminat bilgisi müşteri sırrı tanımında açıkça sayılmıştır."),

    # ============ 6. GİZLİ / ÇOK GİZLİ — erişim/soruşturma/üst yönetim ============
    Concept("c6_sorusturma", "6", 6, [6], False, "guvenlik", "IcSorusturma", "isrDosyaNotu",
            "varchar", "500",
            ["Personel X hakkında yetkisiz erişim şüphesi soruşturması açıldı",
             "Şube müdürü hakkında usulsüzlük iddiası inceleniyor",
             "Bilgi sızıntısı şüphesiyle disiplin süreci başlatıldı"],
            "İç soruşturma dosya notu gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_birlesme", "6", 6, [6], False, "guvenlik", "IcSorusturma", "isrBirlesmeGorusme",
            "varchar", "500",
            ["X Bankası ile görüşmeler ön aşamada, gizlilik sözleşmesi imzalandı",
             "Y Finans A.Ş. hisse devri değerlendiriliyor",
             "Z Katılım Bankası ile stratejik ortaklık görüşmesi"],
            "Birleşme-devralma görüşme notu gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_ustyonetimkarari", "6", 6, [6], False, "guvenlik", "IcSorusturma", "isrUstYonetimKarar",
            "varchar", "500",
            ["Yönetim Kurulu 2026/14 sayılı kararla şube kapatma onayı",
             "YK kararı: yeni CEO ataması 01.04.2026",
             "Kurul kararı: sermaye artırımı onaylandı"],
            "Üst yönetim kararı gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_sizintikaydi", "6", 6, [6], False, "guvenlik", "IcSorusturma", "isrGuvenlikAcigi",
            "varchar", "300",
            ["CVE-2026-1234 kritik SQL injection açığı tespit edildi",
             "Sızma testi bulgusu: yetkisiz API erişimi mümkün",
             "Zafiyet: eski TLS sürümü kullanımı tespit edildi"],
            "Güvenlik açığı/sızma testi kaydı gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_erisim", "6", 6, [6], False, "guvenlik", "ErisimYonetimi", "eryYetkiListesi",
            "varchar", "200",
            ["ADMIN_FULL, DB_WRITE, AUDIT_READ", "READ_ONLY, REPORT_VIEW",
             "DB_ADMIN, USER_MANAGE, CONFIG_WRITE"],
            "Sistem erişim yetki listesi gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_yetkirol", "6", 6, [6], False, "guvenlik", "ErisimYonetimi", "eryRolTanimi",
            "varchar", "100",
            ["ROLE_SUPER_ADMIN", "ROLE_BRANCH_MANAGER", "ROLE_AUDIT_VIEWER"],
            "Yetki-rol tanımı gizli/çok gizli veri tanımında açıkça sayılmıştır."),
    Concept("c6_izingrubu", "6", 6, [6], False, "guvenlik", "ErisimYonetimi", "eryIzinGrubu",
            "varchar", "100",
            ["GRUP_MUHASEBE_ONAY", "GRUP_KREDI_TAHSIS", "GRUP_IT_YONETIM"],
            "Erişim izin grubu tanımı gizli/çok gizli veri tanımında açıkça sayılmıştır."),

    # ============ 7. ŞİFRELİ VERİ — şifreli/hash'lenmiş saklanan alanlar ============
    Concept("c7_sifrehash", "7", 3, [3, 7], False, "guvenlik", "GuvenlikKimlik", "gkParolaHash",
            "varchar", "60",
            ["$2b$12$KIXQ7z8yN3vLPq1RmXe9AOe5tGxHhZ8jKp0mYcVbNwXeQsRtLdKla",
             "$2b$12$T9nRfL2mXpQaZ7Ye3sV4NOWzYb1cKdEfGhIjKlMnOpQrStUvWxYz1",
             "$2b$12$A1b2C3d4E5f6G7h8I9j0KeXyZ9wVuTsRqPoNmLkJiHgFeDcBa1234"],
            "Parola kimlik doğrulama verisidir (içerik: 3); hash'lenmiş saklandığı için 7 eşlik eder — ana kategori içerik sınıfıdır."),
    Concept("c7_pinblok", "7", 3, [3, 7], False, "guvenlik", "GuvenlikKimlik", "gkPinBlok",
            "varchar", "32",
            ["4F2A9C1B8E3D7F60A1B2C3D4E5F60718", "9B3E1A2C4D5F60718293A4B5C6D7E8F0",
             "2C4E6A8B0D1F3547698A0B2C4D6E8F10"],
            "PIN kimlik doğrulama verisidir (içerik: 3); PIN blok olarak şifreli saklanır (7) — ana kategori içerik sınıfıdır."),
    Concept("c7_apikeyhash", "7", 6, [6, 7], False, "guvenlik", "GuvenlikKimlik", "gkApiAnahtarHash",
            "varchar", "64",
            ["sha256:a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f6789",
             "sha256:9876fedc1234abcd9876fedc1234abcd9876fedc1234abcd9876fedc1234ab",
             "sha256:1122aabb3344ccdd1122aabb3344ccdd1122aabb3344ccdd1122aabb3344cc"],
            "API anahtarı banka sisteminin kimlik doğrulama sırrıdır (içerik: 6); hash olarak saklanır (7) — ana kategori içerik sınıfıdır."),
    Concept("c7_sertifikaparmak", "7", 7, [7], False, "guvenlik", "GuvenlikKimlik", "gkSertifikaFingerprint",
            "varchar", "64",
            ["SHA256:AB:CD:EF:12:34:56:78:90:AB:CD:EF:12:34:56:78:90",
             "SHA256:98:76:54:32:10:FE:DC:BA:98:76:54:32:10:FE:DC:BA",
             "SHA256:11:22:33:44:55:66:77:88:99:00:AA:BB:CC:DD:EE:FF"],
            "Sertifika parmak izi içerik sınıfı taşımayan saf kriptografik artefakttır — ana kategorinin 7 olduğu ender durum."),
    Concept("c7_kartnoenc", "7", 3, [3, 5, 7], False, "guvenlik", "MusteriKartSifreli", "mksKartNoSifreli",
            "varchar", "64",
            ["enc:AES256:8f3a9c2b1e7d4f6a0c5b8e2d9f1a3c7b", "enc:AES256:2d5f8a1c3e7b9d0f4a6c8e2b5d9f1a3c",
             "enc:AES256:7c9e1a3b5d7f9012a4c6e8b0d2f4a6c8"],
            "Kart numarası (PAN) kimlik doğrulama verisidir (ana: 3) ve müşteri verisidir (5); şifreli saklandığından 7 eşlik eder."),
    Concept("c7_cvvenc", "7", 3, [3, 5, 7], False, "guvenlik", "MusteriKartSifreli", "mksCvvSifreli",
            "varchar", "32",
            ["enc:9f2a4c6e", "enc:1b3d5f7a", "enc:8e0c2a4d"],
            "CVV kimlik doğrulama verisidir (ana: 3), müşteri kart verisidir (5), şifreli saklanır (7)."),
    Concept("c7_tokenlenmisno", "7", 5, [5, 7], False, "guvenlik", "MusteriKartSifreli", "mksTokenlenmisNo",
            "varchar", "40",
            ["TKN_9f8e7d6c5b4a3210", "TKN_1a2b3c4d5e6f7089", "TKN_00ff11ee22dd33cc"],
            "Tokenize hesap no: içerik müşteri hesabıdır (ana: 5); tokenize saklandığından 7 eşlik eder."),

    # ============ BONUS — TEKNİK/İŞLEMSEL (yanlış pozitif riski ölçümü) ============
    # Bu kova resmi 7 kategoriden biri DEĞİL; skor motoru bunu ayrı ölçer: doğru
    # "teknik": true tespiti mi, yoksa model bu sıradan kolonları gereksiz yere
    # hassas/gizli diye mi işaretliyor. ana_kategori burada prompts.py'nin kendi
    # örneğindeki emsale göre (ccRowVer -> 6) "en yakın" kategori olarak 6 kabul edilir.
    Concept("t_rowver", "teknik", 6, [6], True, "sys", "SistemLog", "slgRowVersion",
            "rowversion", "",
            ["0x0000000000001A2B", "0x0000000000003C4D", "0x0000000000005E6F"],
            "Satır versiyon damgası; sınıflandırılabilir içerik taşımaz, teknik kolondur."),
    Concept("t_createdat", "teknik", 6, [6], True, "sys", "SistemLog", "slgOlusturmaTarihi",
            "datetime", "",
            ["2026-01-15 09:23:11", "2026-02-03 14:05:47", "2026-03-21 08:12:33"],
            "Kayıt oluşturma zaman damgası işlemsel/teknik bir alandır."),
    Concept("t_statuskod", "teknik", 6, [6], True, "sys", "SistemLog", "slgDurumKodu",
            "char", "2",
            ["01", "02", "09"],
            "Durum kodu işlemsel/teknik bir alandır."),
    Concept("t_batchid", "teknik", 6, [6], True, "sys", "SistemLog", "slgBatchNo",
            "varchar", "20",
            ["BATCH_20260315_001", "BATCH_20260316_002", "BATCH_20260317_003"],
            "Batch işlem numarası işlemsel/teknik bir alandır."),
    Concept("t_versiyonno", "teknik", 6, [6], True, "sys", "SistemLog", "slgUygulamaVersiyon",
            "varchar", "10",
            ["3.2.1", "3.2.2", "3.3.0"],
            "Uygulama versiyon numarası işlemsel/teknik bir alandır."),
    Concept("t_siranumarasi", "teknik", 6, [6], True, "sys", "SistemLog", "slgSiraNo",
            "int", "",
            ["1", "2", "3"],
            "Sıra numarası işlemsel/teknik bir alandır."),
    Concept("t_islemtipi", "teknik", 6, [6], True, "sys", "SistemLog", "slgIslemTipi",
            "char", "3",
            ["INS", "UPD", "DEL"],
            "İşlem tipi kodu (INSERT/UPDATE/DELETE) işlemsel/teknik bir alandır."),
]


def _finalize() -> list[Concept]:
    out = []
    for i, c in enumerate(_RAW):
        rnd_schema = _SCHEMA_MAP[c.named_schema]
        rnd_table = _TABLE_MAP[c.named_table]
        rnd_column = _rnd_column(i)
        out.append(
            Concept(
                key=c.key, bucket=c.bucket, ana_kategori=c.ana_kategori,
                kategoriler=c.kategoriler, teknik=c.teknik,
                named_schema=c.named_schema, named_table=c.named_table, named_column=c.named_column,
                veri_tipi=c.veri_tipi, uzunluk=c.uzunluk, sample_values=c.sample_values,
                gerekce=c.gerekce,
                random_schema=rnd_schema, random_table=rnd_table, random_column=rnd_column,
            )
        )
    return out


CONCEPTS: list[Concept] = _finalize()

BUCKETS: list[str] = ["1", "2", "3", "4", "5", "6", "7", "teknik"]


def iter_dataset_items() -> list[dict]:
    """112 satırlık tam veri setini döndürür: her kavramın named + random sürümü.

    Her öğe: {id, concept, bucket, group, row, truth}
      row:   classifier.pipeline.classify_rows'a verilecek ham girdi
      truth: {ana_kategori, kategoriler, teknik, gerekce} — skor motoru bunu kullanır
    """
    items = []
    for c in CONCEPTS:
        truth = {
            "ana_kategori": c.ana_kategori, "kategoriler": c.kategoriler,
            "teknik": c.teknik, "gerekce": c.gerekce,
        }
        items.append({
            "id": f"{c.key}__named", "concept": c.key, "bucket": c.bucket, "group": "named",
            "row": {
                "sema": c.named_schema, "tablo": c.named_table, "kolon": c.named_column,
                "veri_tipi": c.veri_tipi, "uzunluk": c.uzunluk, "nullable": "1", "pk": "0",
                "ornek_degerler": list(c.sample_values),
            },
            "truth": truth,
        })
        items.append({
            "id": f"{c.key}__random", "concept": c.key, "bucket": c.bucket, "group": "random",
            "row": {
                "sema": c.random_schema, "tablo": c.random_table, "kolon": c.random_column,
                "veri_tipi": c.veri_tipi, "uzunluk": c.uzunluk, "nullable": "1", "pk": "0",
                "ornek_degerler": list(c.sample_values),
            },
            "truth": truth,
        })
    return items


def dataset_summary() -> dict:
    items = iter_dataset_items()
    return {
        "total_rows": len(items),
        "concepts": len(CONCEPTS),
        "buckets": BUCKETS,
        "groups": ["named", "random"],
        "rows_per_bucket_per_group": len(CONCEPTS) // len(BUCKETS),
    }
