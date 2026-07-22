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
# 7 bilinçli olarak İÇERİK sınıflarının (3/5/4/6) ARKASINDA: BDDK BSEBY m.9/3'e göre
# şifreli saklama, hassas/sır verinin bir YÜKÜMLÜLÜĞÜdür — kendi başına içerik sınıfı
# değildir. Ana kategori içerik sınıfından seçilir; 7 saklama-biçimi bayrağı olarak
# eşlik eder ve ancak içerik sınıfı taşımayan saf kripto artefaktlarında ana olur.
CATEGORY_PRIORITY: list[int] = [2, 3, 5, 4, 6, 7, 1]

CATEGORY_DEFINITIONS = """\
1. Kişisel Veri (KVKK m.3/d)
   Kimliği belirli veya belirlenebilir GERÇEK KİŞİYE ilişkin her türlü bilgi.
   Örnekler: ad-soyad, TC kimlik no, vergi no (gerçek kişi), pasaport no, doğum tarihi/yeri,
   anne-baba adı, telefon, e-posta, adres, IP adresi, araç plakası, imza, fotoğraf, ses kaydı,
   müşteri numarası, cinsiyet, medeni durum, uyruk, eğitim, meslek, aile bilgileri, ekonomik
   veriler (kişinin maaşı, geliri, mal varlığı).
   SINIR: Tüzel kişilere (şirketlere) ait veriler kişisel veri DEĞİLDİR (ama 5'e girebilir).
   Kişisel veri, kişi PERSONEL de olsa MÜŞTERİ de olsa kişisel veridir.
   ANA KATEGORİ: Kişi banka MÜŞTERİSİ ise bu veri aynı zamanda müşteri sırrıdır; ana kategori
   5, 1 eşlik eder (lex specialis — bkz. 5 KURAL). Müşteri OLMAYAN kişide (personel) ana 1.

2. Özel Nitelikli Kişisel Veri (KVKK m.6/1 — 7499 s.K. ile değişik hâli)
   Kanunda SINIRLI SAYIDA sayılmıştır, kıyas yoluyla GENİŞLETİLEMEZ:
   ırk, etnik köken, siyasi düşünce, felsefi inanç, din, mezhep veya diğer inançlar,
   kılık ve kıyafet, dernek/vakıf/sendika üyeliği, sağlık verileri (kan grubu, engellilik,
   hastalık, ilaç), cinsel hayat, ceza mahkûmiyeti ve güvenlik tedbirleri (sabıka),
   biyometrik veriler (parmak izi, yüz/retina tanıma, ses biyometrisi), genetik veriler.
   KURAL: 2'ye giren her veri aynı zamanda 1'dir. Listede olmayanlar (örn. maaş, finansal
   durum) ne kadar mahrem olursa olsun 2 DEĞİLDİR.

3. Hassas Veri (BDDK Bilgi Sistemleri Yönetmeliği m.3/o — RG 15.3.2020/31069)
   ÇEKİRDEK (mevzuat lafzı): "Kimlik doğrulamada kullanılan veriler başta olmak üzere;
   müşteriye ait olan, çeşitli sebeplerle bankaca muhafaza edilen ve üçüncü kişilerce ele
   geçirilmesi hâlinde ... dolandırıcılık ya da müşteriler adına sahte işlem yapılmasına
   imkân verebilecek nitelikteki veriler": parola, PIN, OTP/tek kullanımlık şifre, güvenlik
   sorusu-cevabı, kart numarası (PAN), CVV/CVC, kart son kullanma tarihi, telefon
   bankacılığı şifresi, erişim token'ları.
   KURUM İÇİ GENİŞLETME (mevzuat lafzında yok; kurumsal tasnif kararı): maaş/gelir,
   kredi notu/skoru, risk derecelendirmesi, kara liste/istihbarat kaydı da bu kategoriye
   dahil edilir.
   KURAL: Bankanın MÜŞTERİ HAKKINDA ürettiği değerlendirmeler (kredi notu/skoru, risk
   derecesi, kara liste kaydı) 3'tür ve müşteri verisi olduğundan 5 de eklenir; bunlar
   6 (kurumsal gizli) DEĞİLDİR. PERSONELE ait maaş/performans 3 + 1'dir (gerçek kişiye
   ait ekonomik veri); 4 değildir (4, kişiye değil kurum geneline ait politika içindir).
   KURAL: 3'e giren veriler BDDK BSEBY m.9/3 gereği şifreli saklanmalıdır — bu yüzden
   çoğu zaman 7 de eşlik eder.

4. Banka Sırrı (5411 s. BK m.73; Sır Yönetmeliği m.4; BDDK Genelgesi 2022/1)
   MÜŞTERİ SIRRI NİTELİĞİ TAŞIMAYIP YALNIZCA BANKANIN KENDİSİNE ait, öğrenilmesi hâlinde
   rekabet gücünü veya güvenliğini zedeleyecek bilgiler: henüz kamuya açıklanmamış mali
   veriler, strateji ve iş planları, kredi verme/mevduat toplama gibi temel faaliyetlere
   ilişkin yönetim esasları, bankanın uyguladığı teknik yöntemler, iç fiyatlama/marj/
   komisyon parametreleri, risk modelleri ve parametreleri, iç limitler, denetim ve teftiş
   raporları, iç kontrol bulguları, kurum geneline ait insan kaynakları politikaları
   (kadro planı, ücret POLİTİKASI — tek bir kişinin maaşı değil), banka potansiyeline
   ilişkin bilgiler.
   KURAL: Veri müşteriye değil bankanın kendi işleyişine aitse 4'tür. Tek bir çalışana/
   kişiye ait veri 4 değil 1(+3)'tür.

5. Müşteri Sırrı (5411 s. BK m.73/3; Sır Yönetmeliği m.4)
   Bankacılık faaliyetlerine özgü olarak müşteri ilişkisi kurulduktan sonra oluşan, gerçek VE
   tüzel kişilere ait her türlü veri ile kişinin banka müşterisi olduğunu gösteren HER TÜRLÜ bilgi:
   müşteri no, hesap no, IBAN, bakiye, hesap hareketleri/ekstre, kredi başvuru ve geri ödeme
   bilgileri, kart bilgileri, teminatlar, mevduat/yatırım/portföy, EFT-havale kayıtları,
   çek-senet, müşteri talimatları, müşteri segmenti/limiti.
   KURAL: Müşteri gerçek kişiyse bu veriler 1 ile BİRLİKTE işaretlenir ve ANA KATEGORİ 5 olur:
   5411 s.K. m.73 ÖZEL kanun, KVKK GENEL kanundur; çakışmada özel kanun önceliklidir (lex
   specialis) ve müşteri sırrı daha sıkı rejimdir (açık rızayla dahi 3. kişilere aktarılamaz).
   Tüzel kişi müşteri verisi yalnız 5'tir.

6. Gizli / Çok Gizli Veri (kurumsal gizlilik tasnifi)
   Erişimi "bilmesi gereken" ilkesiyle en dar tutulması gereken, yetkisiz açıklanması kuruma
   ciddi/hayati zarar verecek BANKA İÇİ bilgiler: sistem kimlik doğrulama sırları ve
   kriptografik anahtarlar, güvenlik açığı ve sızma testi kayıtları, iç soruşturma/disiplin
   dosyaları, birleşme-devralma çalışmaları, üst yönetim kararları, yetki-rol tanımları ve
   erişim listeleri.
   SINIR: Müşteri hakkındaki değerlendirmeler (kredi notu, kara liste) buraya DEĞİL 3+5'e
   girer; 6 kurumun kendi iç güvenlik/yönetim bilgisi içindir.

7. Şifreli Veri (BDDK BSEBY m.9/3: şifreli saklama yükümlülüğü)
   Bir SAKLAMA BİÇİMİ kategorisidir — İÇERİK SINIFI DEĞİLDİR (şifreli saklama, BSEBY m.9/3'te
   hassas/sır verinin YÜKÜMLÜLÜĞÜ olarak düzenlenir). Veritabanında şifrelenmiş/hash'lenmiş/
   tokenize/maskeli SAKLANAN alanlarda, içerik sınıfının YANINDA eşlik eden bir bayraktır;
   tek başına ana kategori olmaz.
   İÇERİK SINIFI TAŞIYAN ŞİFRELİ ALANLARDA ANA KATEGORİ İÇERİKTİR, 7 yalnız eşlik eder:
     • parola/PIN hash'i, OTP, güvenlik sorusu cevabı → ana 3 (+7)
     • şifreli kart numarası / CVV → ana 3 (+5, +7)
     • tokenize hesap/müşteri no → ana 5 (+7)
     • şifreleme anahtarı, API secret, özel anahtar, sistem/servis parolası → ana 6 (+7)
   ANA kategori 7 YALNIZCA hiçbir içerik sınıfı taşımayan SAF kriptografik artefaktlarda
   seçilir: salt, IV (initialization vector), nonce, sertifika parmak izi (fingerprint).
   DİKKAT-1: "anahtar/secret/key" gibi görünen bir alan otomatik 7 DEĞİLDİR. Bir SİSTEM
   SIRRIYSA (şifreleme anahtarı, API secret, özel anahtar) ana kategori 6'dır; şifreli
   saklanması onu 7 YAPMAZ, yalnız 7'yi yanına ekler.
   DİKKAT-2: Şifreli/hash'li/tokenize saklanan bir alan TEKNİK bir kolon DEĞİLDİR — 7 (ve
   varsa içerik sınıfı) taşır; "teknik": false olur. "teknik": true yalnız sınıflandırılabilir
   içeriği OLMAYAN işlemsel kolonlar içindir (satır versiyonu, zaman damgası, durum kodu).
"""
