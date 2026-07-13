"""classifier/examples.py — curated referans örnek bankası + few-shot retrieval testleri."""

import pytest

import config
from classifier import decisions, examples
from classifier.categories import CATEGORIES, CATEGORY_PRIORITY


@pytest.fixture(autouse=True)
def isolated_decisions(tmp_path, monkeypatch):
    """Her test boş karar sözlüğüyle başlar — havuz yalnız curated örneklerden oluşur."""
    monkeypatch.setattr(config, "DECISIONS_FILE", str(tmp_path / "decisions.json"))
    monkeypatch.setattr(decisions, "_decisions", {})
    monkeypatch.setattr(decisions, "_loaded", False)


class TestCuratedBankIntegrity:
    def test_all_examples_have_valid_categories(self):
        for ex in examples.CURATED_EXAMPLES:
            assert ex["kategoriler"], f"{ex['kolon']} kategorisiz"
            for c in ex["kategoriler"]:
                assert c in CATEGORIES, f"{ex['kolon']} geçersiz kategori {c}"
            assert ex["ana_kategori"] in ex["kategoriler"], \
                f"{ex['kolon']} ana kategori listesinde değil"

    def test_category_2_always_implies_1(self):
        # Mevzuat kuralı: 2 içeren her örnek 1'i de içerir.
        for ex in examples.CURATED_EXAMPLES:
            if 2 in ex["kategoriler"]:
                assert 1 in ex["kategoriler"], f"{ex['kolon']} 2 var ama 1 yok"

    def test_every_category_has_at_least_one_example(self):
        covered = {c for ex in examples.CURATED_EXAMPLES for c in ex["kategoriler"]}
        for c in CATEGORY_PRIORITY:
            assert c in covered, f"Kategori {c} için curated örnek yok"

    def test_has_technical_examples(self):
        assert any(ex.get("teknik") for ex in examples.CURATED_EXAMPLES)


class TestRetrieval:
    def test_retrieves_similar_curated_example(self):
        # klaIbanNo → curated "ibanNo" örneğine benzer (token {iban,no} ortak).
        found = examples.retrieve([{"kolon": "klaIbanNo", "veri_tipi": "varchar"}])
        kolonlar = {e["kolon"] for e in found}
        assert "ibanNo" in kolonlar
        assert all(e["kaynak"] == "referans" for e in found)

    def test_unrelated_column_returns_nothing(self):
        # Hiçbir curated örnekle token paylaşmayan uydurma ad → eşik altı, boş.
        assert examples.retrieve([{"kolon": "xqz9", "veri_tipi": "int"}]) == []

    def test_respects_k_budget(self):
        found = examples.retrieve(
            [{"kolon": "tcKimlikNo", "veri_tipi": "varchar"}], k=2
        )
        assert len(found) <= 2

    def test_human_decision_overrides_curated_same_signature(self, monkeypatch):
        # Aynı imzalı (ibanNo/varchar) insan kararı curated örneğin yerini alır.
        decisions.save_decision(
            {"kolon": "ibanNo", "veri_tipi": "varchar"}, "duzelt",
            ana_kategori=5, kategoriler=[5],
        )
        found = examples.retrieve([{"kolon": "ibanNo", "veri_tipi": "varchar"}])
        iban = [e for e in found if e["kolon"] == "ibanNo"]
        assert len(iban) == 1
        assert iban[0]["kaynak"] == "duzelt"  # curated değil, insan kararı

    def test_char_ngram_matches_prefix_abbreviation(self):
        # Token kesişmese de karakter n-gramı önek kısaltmasını yakalar:
        # "musteriSegment" (tam token yok) → musteriSegmentKodu benzerliği n-gramdan gelir.
        found = examples.retrieve([{"kolon": "custMusteriSeg", "veri_tipi": "varchar"}])
        assert any(e["kolon"] == "musteriSegmentKodu" for e in found)

    def test_content_signature_matches_cryptic_name_by_iban_values(self):
        # KRİPTİK ad (x113) ama IBAN biçimli değerler → içerik ekseninden ibanNo bulunur.
        near = examples.nearest_for_column(
            {"kolon": "x113", "veri_tipi": "varchar",
             "ornek_degerler": ["TR330006100519786457841326", "TR120001009999901234567890"]}
        )
        assert near and near[0]["kolon"] == "ibanNo"
        assert near[0]["benzerlik"] > 0.5  # yalnız içerikten güçlü eşleşme

    def test_content_axis_ignored_without_values(self):
        # Değer yoksa içerik ekseni devreye girmez; alakasız kriptik ad boş döner.
        assert examples.nearest_for_column({"kolon": "zzz9", "veri_tipi": "int"}) == []

    def test_email_values_reach_email_example(self):
        near = examples.nearest_for_column(
            {"kolon": "col_q", "veri_tipi": "varchar",
             "ornek_degerler": ["ali@x.com", "veli.demir@firma.com.tr"]}
        )
        assert any(e["kolon"] == "ePostaAdresi" for e in near)

    def test_nearest_for_column_carries_similarity(self):
        near = examples.nearest_for_column({"kolon": "musteriHesapNo", "veri_tipi": "varchar"})
        assert near
        assert all("benzerlik" in e for e in near)
        # Skorlar azalan sırada
        sims = [e["benzerlik"] for e in near]
        assert sims == sorted(sims, reverse=True)
