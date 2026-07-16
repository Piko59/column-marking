"""classifier/decisions.py — insan inceleme kararları sözlüğü testleri."""

import pytest

import config
from classifier import decisions, llm
from classifier.pipeline import classify_rows


@pytest.fixture(autouse=True)
def isolated_decisions(tmp_path, monkeypatch):
    """Her test kendi geçici karar dosyasıyla ve boş bellek durumuyla başlar."""
    monkeypatch.setattr(config, "DECISIONS_FILE", str(tmp_path / "decisions.json"))
    monkeypatch.setattr(decisions, "_decisions", {})
    monkeypatch.setattr(decisions, "_loaded", False)


ROW = {"sema": "dbo", "tablo": "Customer", "kolon": "custTckn", "veri_tipi": "char"}


class TestDecisionKey:
    def test_key_is_column_and_type_only(self):
        # Tablo/şema anahtara girmez: sözlüğün kaldıracı kolon imzasının
        # tablolar arası genellemesidir
        other_table = {**ROW, "tablo": "Basvuru", "sema": "core"}
        assert decisions.decision_key(ROW) == decisions.decision_key(other_table)

    def test_key_normalized(self):
        assert decisions.decision_key({"kolon": " CustTckn ", "veri_tipi": "CHAR"}) == \
            decisions.decision_key(ROW)


class TestSaveAndLookup:
    def test_onayla_returned_by_lookup(self):
        decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1, 5])
        rec = decisions.lookup(ROW)
        assert rec is not None
        assert rec["ana_kategori"] == 1
        assert rec["kategoriler"] == [1, 5]

    def test_notr_never_affects_lookup(self):
        # Nötr kararın tek etkisi denetim kaydıdır; sınıflandırmaya etkisi yoktur
        decisions.save_decision(ROW, "notr")
        assert decisions.lookup(ROW) is None
        assert decisions.stats()["notr"] == 1

    def test_duzelt_requires_valid_ana(self):
        with pytest.raises(ValueError):
            decisions.save_decision(ROW, "duzelt", ana_kategori=None, kategoriler=[1])
        with pytest.raises(ValueError):
            decisions.save_decision(ROW, "duzelt", ana_kategori=99, kategoriler=[1])

    def test_invalid_action_rejected(self):
        with pytest.raises(ValueError):
            decisions.save_decision(ROW, "belki")

    def test_ana_added_to_categories_if_missing(self):
        decisions.save_decision(ROW, "duzelt", ana_kategori=3, kategoriler=[5])
        assert decisions.lookup(ROW)["kategoriler"] == [3, 5]

    def test_last_decision_wins(self):
        decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1])
        decisions.save_decision(ROW, "notr")
        assert decisions.lookup(ROW) is None  # nötr üzerine yazdı, etki kalktı

    def test_persistence_roundtrip(self, monkeypatch):
        decisions.save_decision(ROW, "duzelt", ana_kategori=5, kategoriler=[1, 5],
                                orijinal={"ana_kategori": 1, "kategoriler": [1], "guven": 0.9})
        # Belleği sıfırla; dosyadan yeniden yüklenmeli
        monkeypatch.setattr(decisions, "_decisions", {})
        monkeypatch.setattr(decisions, "_loaded", False)
        rec = decisions.lookup(ROW)
        assert rec["ana_kategori"] == 5
        assert rec["orijinal"]["guven"] == 0.9


class TestAsResult:
    def test_shape_matches_pipeline_schema(self):
        rec = decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1, 5])
        res = decisions.as_result(rec, "custTckn")
        assert res["kaynak"] == "sozluk"
        assert res["guven"] == 1.0
        assert res["ana_kategori"] == 1
        assert res["kategori_adlari"] == ["Kişisel Veri", "Müşteri Sırrı"]


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_decided_row_bypasses_llm(self, monkeypatch):
        decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1, 5])

        async def explode(*a, **kw):
            raise AssertionError("Karar sözlüğündeki satır için LLM çağrılmamalı")

        monkeypatch.setattr(llm, "chat", explode)
        results = await classify_rows([ROW], use_judge=True)
        assert results[0]["kaynak"] == "sozluk"
        assert results[0]["ana_kategori"] == 1

    @pytest.mark.asyncio
    async def test_notr_row_still_goes_to_llm(self, monkeypatch):
        decisions.save_decision(ROW, "notr")
        called = {"n": 0}

        async def fake_chat(system, user, temperature=None):
            called["n"] += 1
            import json
            return json.dumps([{"kolon": "custTckn", "olasi_kategoriler": [1],
                                "ana_kategori": 1, "teknik": False, "guven": 0.9,
                                "gerekce": "t"}])

        monkeypatch.setattr(llm, "chat", fake_chat)
        results = await classify_rows([ROW], use_judge=False)
        assert called["n"] == 1  # nötr kayıt LLM'i atlatmaz
        assert results[0]["kaynak"] == "llm"

    @pytest.mark.asyncio
    async def test_use_decisions_false_ignores_dictionary_in_name_content(self, monkeypatch):
        # Benchmark, name_content modunu use_decisions=False ile koşar: karar sözlüğü
        # birebir imza eşleşmesinde bile devreye GİRMEMELİ — yoksa benchmark modelin
        # yeteneğini değil, insanın önceden verdiği cevabı ölçer.
        decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1, 5])
        called = {"n": 0}

        async def fake_chat(system, user, temperature=None):
            called["n"] += 1
            import json
            return json.dumps([{"kolon": "custTckn",
                                "olasi_kategoriler": [{"id": 1, "olasilik": 0.9},
                                                      {"id": 5, "olasilik": 0.1}],
                                "ana_kategori": 1, "teknik": False, "gerekce": "t"}])

        monkeypatch.setattr(llm, "chat", fake_chat)
        results = await classify_rows(
            [ROW], use_judge=False, mode="name_content", use_decisions=False
        )
        assert called["n"] == 1, "Sözlük imzası eşleşse bile LLM çağrılmalıydı"
        assert results[0]["kaynak"] == "llm"

    @pytest.mark.asyncio
    async def test_benchmark_modes_ignore_dictionary(self, monkeypatch):
        # content_only/name_only modları ölçüm içindir; insan kararı karışmamalı
        decisions.save_decision(ROW, "onayla", ana_kategori=1, kategoriler=[1])
        called = {"n": 0}

        async def fake_chat(system, user, temperature=None):
            called["n"] += 1
            import json
            return json.dumps([{"kolon": "x", "olasi_kategoriler": [1], "ana_kategori": 1,
                                "teknik": False, "guven": 0.9, "gerekce": "t"}])

        monkeypatch.setattr(llm, "chat", fake_chat)
        await classify_rows([ROW], use_judge=False, mode="name_only")
        assert called["n"] == 1
