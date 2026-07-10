"""7 gizlilik kategorisinin tek doğruluk kaynağı (backend + prompt + UI aynı listeyi kullanır).

Tanımlar Türk bankacılık mevzuatına dayanır:
- KVKK m.3/d ve m.6 (kişisel veri / özel nitelikli kişisel veri)
- 5411 sayılı Bankacılık Kanunu m.73 (banka sırrı / müşteri sırrı)
- Sır Niteliğindeki Bilgilerin Paylaşılması Hakkında Yönetmelik (BDDK, RG 4.6.2021/31501)
- Bankaların Bilgi Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında Yönetmelik
  (BDDK, "hassas veri" tanımı ve şifreli saklama yükümlülükleri)
"""

CATEGORIES = {
    1: "Kişisel Veri",
    2: "Özel Nitelikli Kişisel Veri",
    3: "Hassas Veri",
    4: "Banka Sırrı",
    5: "Müşteri Sırrı",
    6: "Gizli / Çok Gizli Veri",
    7: "Şifreli Veri",
}

# Eşit uyum durumunda en sıkı korunması gereken kategori kazanır (bkz. prompts.py
# ADIM 3 ve JUDGE_SYSTEM_PROMPT ile aynı sıra). pipeline._sanitize buradan okur;
# tek doğruluk kaynağı burasıdır.
CATEGORY_PRIORITY: list[int] = [2, 3, 7, 5, 4, 6, 1]

CATEGORY_DEFINITIONS = """\
1. Kişisel Veri (KVKK m.3/d)
   Kimliği belirli veya belirlenebilir GERÇEK KİŞİYE ilişkin her türlü bilgi.
   Örnekler: ad-soyad, TC kimlik no, vergi no (gerçek kişi), pasaport no, doğum tarihi/yeri,
   anne-baba adı, telefon, e-posta, adres, IP adresi, araç plakası, imza, fotoğraf, ses kaydı,
   müşteri numarası, cinsiyet, medeni durum, uyruk, eğitim, meslek, aile bilgileri.
   SINIR: Tüzel kişilere (şirketlere) ait veriler kişisel veri DEĞİLDİR (ama 5'e girebilir).

2. Özel Nitelikli Kişisel Veri (KVKK m.6/1)
   Kanunda SINIRLI SAYIDA sayılmıştır, kıyas yoluyla GENİŞLETİLEMEZ:
   ırk, etnik köken, siyasi düşünce, felsefi inanç, din, mezhep veya diğer inançlar,
   kılık ve kıyafet, dernek/vakıf/sendika üyeliği, sağlık verileri (kan grubu, engellilik,
   hastalık, ilaç), cinsel hayat, ceza mahkûmiyeti ve güvenlik tedbirleri (sabıka),
   biyometrik veriler (parmak izi, yüz/retina tanıma, ses biyometrisi), genetik veriler.
   KURAL: 2'ye giren her veri aynı zamanda 1'dir. Listede olmayanlar (örn. maaş, finansal
   durum) ne kadar mahrem olursa olsun 2 DEĞİLDİR.

3. Hassas Veri (BDDK Bilgi Sistemleri Yönetmeliği m.3)
   Başta kimlik doğrulamada kullanılan veriler olmak üzere, üçüncü kişilerce ele geçirilmesi
   hâlinde dolandırıcılığa ya da müşteri adına sahte işlem yapılmasına imkân verebilecek veriler:
   parola, PIN, OTP/tek kullanımlık şifre, güvenlik sorusu-cevabı, kart numarası (PAN),
   CVV/CVC, kart son kullanma tarihi, telefon bankacılığı şifresi.
   Ek olarak kurum içi hassas kabul edilenler: maaş/gelir, kredi notu/skoru, risk
   derecelendirmesi, kara liste/istihbarat kaydı.

4. Banka Sırrı (5411 s. BK m.73; Sır Yönetmeliği m.4; BDDK Genelgesi 2022/1)
   BANKANIN KENDİSİNE ait, öğrenilmesi hâlinde rekabet gücünü veya güvenliğini zedeleyecek
   bilgiler: henüz kamuya açıklanmamış mali veriler, strateji ve iş planları, kredi verme/
   mevduat toplama gibi temel faaliyetlere ilişkin yönetim esasları, bankanın uyguladığı
   teknik yöntemler, iç fiyatlama/marj/komisyon parametreleri, risk modelleri ve
   parametreleri, iç limitler, denetim ve teftiş raporları, iç kontrol bulguları, insan
   kaynakları verileri (kadro planı, ücret politikası), banka potansiyeline ilişkin bilgiler.
   KURAL: Veri müşteriye değil bankanın kendi işleyişine aitse 4'tür.

5. Müşteri Sırrı (5411 s. BK m.73/3; Sır Yönetmeliği m.4)
   Bankacılık faaliyetlerine özgü olarak müşteri ilişkisi kurulduktan sonra oluşan, gerçek VE
   tüzel kişilere ait her türlü veri ile kişinin banka müşterisi olduğunu gösteren HER TÜRLÜ bilgi:
   müşteri no, hesap no, IBAN, bakiye, hesap hareketleri/ekstre, kredi başvuru ve geri ödeme
   bilgileri, kart bilgileri, teminatlar, mevduat/yatırım/portföy, EFT-havale kayıtları,
   çek-senet, müşteri talimatları, müşteri segmenti/limiti.
   KURAL: Müşteri gerçek kişiyse bu veriler çoğunlukla 1 ile BİRLİKTE işaretlenir;
   tüzel kişi müşteri verisi yalnız 5'tir.

6. Gizli / Çok Gizli Veri (kurumsal gizlilik tasnifi)
   Erişimi "bilmesi gereken" ilkesiyle en dar tutulması gereken, yetkisiz açıklanması kuruma
   ciddi/hayati zarar verecek bilgiler: kimlik doğrulama sırları ve kriptografik anahtarlar,
   güvenlik açığı ve sızma testi kayıtları, iç soruşturma/disiplin dosyaları, birleşme-devralma
   çalışmaları, üst yönetim kararları, yetki-rol tanımları ve erişim listeleri.

7. Şifreli Veri (BDDK şifreli saklama yükümlülükleri)
   Veritabanında şifrelenmiş/hash'lenmiş/tokenize/maskeli SAKLANAN ya da mevzuat gereği öyle
   saklanması GEREKEN alanlar: parola hash'i (salted-hash), PIN blok, şifreli kart numarası,
   CVV, API anahtarı, token, secret, sertifika/özel anahtar, şifreleme anahtarı.
   KURAL: 7 saklama biçimiyle ilgilidir; içeriğine göre ayrıca 3/5/6 ile birlikte işaretlenir.
"""
