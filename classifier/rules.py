"""Kural katmanı: kolon adı ayrıştırma, tablo adından önek çözümü ve anahtar kelime ipuçları.

Bu katman kesin karar VERMEZ; LLM prompt'una eklenen ipuçları üretir. Böylece kural
sözlüğü eksik/yanlış olsa bile son karar bağlamı gören modelde kalır.
"""

import re

# --- Ad ayrıştırma -----------------------------------------------------------

def split_tokens(name: str) -> list[str]:
    """camelCase / PascalCase / snake_case adı küçük harfli parçalara böler."""
    if not name:
        return []
    name = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]+", " ", name)
    name = re.sub(r"(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", " ", name)
    name = re.sub(r"(?<=[A-ZÇĞİÖŞÜ])(?=[A-ZÇĞİÖŞÜ][a-zçğıöşü])", " ", name)
    return [t.lower() for t in name.split() if t]


def table_prefix_candidates(table_name: str) -> dict[str, str]:
    """Tablo adından olası kolon öneklerini üretir — yalnızca GÜÇLÜ adaylar.

    Zayıf adaylar (token'ların 2-4 harflik parçaları gibi) bilinçli olarak üretilmez;
    zorlama eşleşmeler LLM'i yanıltıyordu. Sadece:
      - çok kelimeli adın baş harfleri: ApplicationRequest -> 'ar'
      - tam token'lar: Customer -> 'customer'
    """
    tokens = split_tokens(table_name)
    if not tokens:
        return {}
    cands: dict[str, str] = {}
    if len(tokens) > 1:
        cands["".join(t[0] for t in tokens)] = table_name
    for t in tokens:
        if len(t) >= 4:  # 'def', 'log' gibi kısa token'lar rastlantısal eşleşir
            cands[t] = table_name
    return cands


def expand_column(column_name: str, table_name: str) -> dict:
    """Kolon adını tablo bağlamıyla açar: önek eşleşmesi + kalan token'lar."""
    col_lower = column_name.lower()
    matched_prefix, remainder = None, column_name
    for prefix, source in sorted(
        table_prefix_candidates(table_name).items(), key=lambda kv: -len(kv[0])
    ):
        if col_lower.startswith(prefix) and len(column_name) > len(prefix):
            matched_prefix, remainder = prefix, column_name[len(prefix):]
            break
    tokens = split_tokens(remainder)
    note = ""
    if matched_prefix:
        note = f"'{matched_prefix}' öneki '{table_name}' tablosunun kısaltması olabilir"
    return {"prefix": matched_prefix, "tokens": tokens, "note": note}


# --- Anahtar kelime ipuçları -------------------------------------------------
# token (tam eşleşme) -> kategori id listesi
KEYWORD_HINTS: dict[str, list[int]] = {
    # Kişisel veri
    "tckn": [1], "tcno": [1], "tc": [1], "kimlik": [1], "identity": [1], "citizen": [1],
    "ad": [1], "adi": [1], "soyad": [1], "soyadi": [1], "name": [1], "surname": [1],
    "firstname": [1], "lastname": [1], "fullname": [1], "midname": [1],
    "dogum": [1], "birth": [1], "birthdate": [1], "birthplace": [1], "age": [1], "yas": [1],
    "tel": [1], "telefon": [1], "phone": [1], "gsm": [1], "mobile": [1], "fax": [1],
    "email": [1], "eposta": [1], "mail": [1],
    "adres": [1], "address": [1], "addr": [1], "city": [1], "sehir": [1], "il": [1],
    "ilce": [1], "district": [1], "zip": [1], "postcode": [1],
    "musterino": [1], "custno": [1], "customerno": [1], "customerid": [1], "custid": [1],
    "vergino": [1], "taxno": [1], "taxid": [1], "vkn": [1],
    "anne": [1], "baba": [1], "mother": [1], "father": [1], "maiden": [1],
    "imza": [1], "signature": [1], "photo": [1], "foto": [1], "ip": [1],
    "passport": [1], "pasaport": [1], "plaka": [1], "plate": [1],
    "medeni": [1], "marital": [1], "gender": [1], "cinsiyet": [1], "sex": [1],
    "nationality": [1], "uyruk": [1],
    # Özel nitelikli
    "saglik": [1, 2], "health": [1, 2], "engel": [1, 2], "disability": [1, 2],
    "din": [1, 2], "religion": [1, 2], "mezhep": [1, 2],
    "irk": [1, 2], "race": [1, 2], "etnik": [1, 2], "ethnic": [1, 2],
    "sendika": [1, 2], "union": [1, 2], "parti": [1, 2],
    "biyometrik": [1, 2], "biometric": [1, 2], "parmak": [1, 2], "fingerprint": [1, 2],
    "genetik": [1, 2], "genetic": [1, 2], "kan": [1, 2], "blood": [1, 2],
    "sabika": [1, 2], "mahkum": [1, 2], "criminal": [1, 2], "conviction": [1, 2],
    # Hassas
    "maas": [3], "salary": [3], "ucret": [3], "wage": [3], "gelir": [1, 3], "income": [1, 3],
    "skor": [3], "score": [3], "rating": [3], "not": [3],
    "karaliste": [3], "blacklist": [3], "istihbarat": [3], "intelligence": [3],
    "performans": [3], "performance": [3], "disiplin": [3],
    # Banka sırrı
    "marj": [4], "margin": [4], "strateji": [4], "strategy": [4],
    "teftis": [4], "audit": [4], "denetim": [4], "riskmodel": [4],
    "provizyonparam": [4], "limitparam": [4],
    # Müşteri sırrı
    "hesapno": [5], "accountno": [5], "accno": [5], "iban": [5],
    "bakiye": [5], "balance": [5], "islem": [5], "transaction": [5], "txn": [5],
    "hareket": [5], "ekstre": [5], "statement": [5],
    "kredi": [5], "credit": [5], "loan": [5], "mortgage": [5], "teminat": [5],
    "collateral": [5], "kart": [5], "card": [5], "cardno": [5], "pan": [5, 7],
    "havale": [5], "eft": [5], "swift": [5], "transfer": [5],
    "portfoy": [5], "portfolio": [5], "yatirim": [5], "investment": [5],
    "mevduat": [5], "deposit": [5], "faiz": [5], "interest": [5],
    # Gizli / çok gizli
    "yetki": [6], "role": [6], "auth": [6], "permission": [6], "izin": [6],
    "sorusturma": [6], "investigation": [6], "config": [6], "secretkey": [6, 7],
    # Şifreli
    "sifre": [6, 7], "password": [6, 7], "pwd": [6, 7], "pass": [6, 7], "parola": [6, 7],
    "pin": [6, 7], "cvv": [5, 7], "cvc": [5, 7], "hash": [7], "encrypted": [7],
    "sifreli": [7], "crypt": [7], "token": [7], "secret": [6, 7], "apikey": [6, 7],
    "key": [7], "cert": [7], "sertifika": [7], "otp": [7], "salt": [7],
}


def keyword_hints(tokens: list[str]) -> dict[str, list[int]]:
    """Token listesinde sözlük eşleşmelerini döndürür: {token: [kategori_id, ...]}."""
    hits: dict[str, list[int]] = {}
    joined = "".join(tokens)
    for tok in set(tokens) | ({joined} if len(tokens) > 1 else set()):
        if tok in KEYWORD_HINTS:
            hits[tok] = KEYWORD_HINTS[tok]
    return hits


def analyze_column(column_name: str, table_name: str) -> dict:
    """Tek kolon için tüm kural çıktıları: açılım notu + ipuçları."""
    exp = expand_column(column_name, table_name)
    tokens = exp["tokens"] or split_tokens(column_name)
    return {
        "note": exp["note"],
        "tokens": tokens,
        "hints": keyword_hints(tokens),
    }
