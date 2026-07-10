import pytest

import config
from classifier import prompts
from classifier.pipeline import _anonymize, _cache_key, _error_result, _sanitize, classify_rows


class TestCacheKey:
    def test_composes_schema_table_column_type(self):
        row = {"sema": "dbo", "tablo": "Customer", "kolon": "Ad", "veri_tipi": "varchar"}
        assert _cache_key(row) == f"{config.QWEN_MODEL}|{prompts.PROMPT_VERSION}|dbo|customer|ad|varchar"

    def test_missing_fields_default_to_empty(self):
        row = {"kolon": "Ad"}
        assert _cache_key(row) == f"{config.QWEN_MODEL}|{prompts.PROMPT_VERSION}|||ad|"

    def test_case_and_whitespace_insensitive(self):
        a = _cache_key({"sema": " DBO ", "tablo": "Customer", "kolon": "Ad", "veri_tipi": "varchar"})
        b = _cache_key({"sema": "dbo", "tablo": "Customer", "kolon": "Ad", "veri_tipi": "varchar"})
        assert a == b

    def test_key_changes_when_model_changes(self, monkeypatch):
        row = {"sema": "dbo", "tablo": "Customer", "kolon": "Ad", "veri_tipi": "varchar"}
        before = _cache_key(row)
        monkeypatch.setattr(config, "QWEN_MODEL", "some-other-model")
        after = _cache_key(row)
        assert before != after

    def test_key_changes_when_prompt_changes(self, monkeypatch):
        row = {"sema": "dbo", "tablo": "Customer", "kolon": "Ad", "veri_tipi": "varchar"}
        before = _cache_key(row)
        monkeypatch.setattr(prompts, "PROMPT_VERSION", "deadbeef0000")
        after = _cache_key(row)
        assert before != after


class TestErrorResult:
    def test_shape(self):
        res = _error_result("colX", "boom")
        assert res["kolon"] == "colX"
        assert res["kategoriler"] == []
        assert res["ana_kategori"] is None
        assert res["guven"] == 0.0
        assert res["kaynak"] == "hata"
        assert "boom" in res["gerekce"]


class TestSanitize:
    def test_category_2_always_implies_1(self):
        result = _sanitize({"olasi_kategoriler": [2], "ana_kategori": 2, "guven": 0.9}, "col", "llm")
        assert result["kategoriler"] == [1, 2]

    def test_ana_kategori_fallback_uses_priority_not_min_id(self):
        # ana_kategori verilmemiş; olası kategoriler [1, 5] -> öncelik sırasında (2>3>7>5>4>6>1)
        # 5, 1'den önce geldiği için 5 seçilmeli (cats[0]=1 DEĞİL)
        result = _sanitize({"olasi_kategoriler": [1, 5], "guven": 0.8}, "col", "llm")
        assert result["ana_kategori"] == 5

    def test_ana_kategori_priority_picks_2_over_everything(self):
        result = _sanitize({"olasi_kategoriler": [1, 2, 6], "guven": 0.8}, "col", "llm")
        assert result["ana_kategori"] == 2

    def test_invalid_ana_kategori_falls_back_to_priority(self):
        result = _sanitize(
            {"olasi_kategoriler": [4, 7], "ana_kategori": 99, "guven": 0.8}, "col", "llm"
        )
        assert result["ana_kategori"] == 7  # 7 > 4 önceliğinde

    def test_ana_kategori_not_in_list_gets_added(self):
        result = _sanitize({"olasi_kategoriler": [4], "ana_kategori": 6, "guven": 0.8}, "col", "llm")
        assert result["ana_kategori"] == 6
        assert 6 in result["kategoriler"]

    def test_confidence_clamped_to_0_1(self):
        assert _sanitize({"olasi_kategoriler": [1], "guven": 5}, "c", "llm")["guven"] == 1.0
        assert _sanitize({"olasi_kategoriler": [1], "guven": -3}, "c", "llm")["guven"] == 0.0

    def test_confidence_non_numeric_defaults_to_zero(self):
        assert _sanitize({"olasi_kategoriler": [1], "guven": "yüksek"}, "c", "llm")["guven"] == 0.0

    def test_acilim_null_variants_become_empty_string(self):
        for val in (None, "null", "None"):
            result = _sanitize({"olasi_kategoriler": [1], "acilim": val, "guven": 0.5}, "c", "llm")
            assert result["acilim"] == ""

    def test_invalid_category_ids_filtered_out(self):
        result = _sanitize({"olasi_kategoriler": [1, 99, "abc"], "guven": 0.5}, "c", "llm")
        assert result["kategoriler"] == [1]

    def test_no_categories_means_no_ana_kategori(self):
        result = _sanitize({"olasi_kategoriler": [], "guven": 0.5}, "c", "llm")
        assert result["ana_kategori"] is None
        assert result["kategoriler"] == []

    def test_gerekce_and_acilim_truncated(self):
        result = _sanitize(
            {"olasi_kategoriler": [1], "acilim": "a" * 300, "gerekce": "b" * 600, "guven": 0.5},
            "c", "llm",
        )
        assert len(result["acilim"]) == 200
        assert len(result["gerekce"]) == 500

    def test_kaynak_passthrough(self):
        result = _sanitize({"olasi_kategoriler": [1], "guven": 0.5}, "c", "llm+hakem")
        assert result["kaynak"] == "llm+hakem"

    def test_kategoriler_key_accepted_as_alias(self):
        # LLM bazen "olasi_kategoriler" yerine "kategoriler" anahtarıyla dönebilir
        result = _sanitize({"kategoriler": [3], "guven": 0.5}, "c", "llm")
        assert result["kategoriler"] == [3]


class TestAnonymize:
    def test_deterministic_for_same_input(self):
        assert _anonymize("col", "musteriAdi") == _anonymize("col", "musteriAdi")

    def test_different_kind_prefix_differs(self):
        a, b = _anonymize("col", "x"), _anonymize("tbl", "x")
        assert a.startswith("col_") and b.startswith("tbl_")
        assert a != b

    def test_empty_value_passthrough(self):
        assert _anonymize("col", "") == ""

    def test_does_not_leak_original_value(self):
        result = _anonymize("col", "musteriAdiSoyadi")
        assert "musteri" not in result.lower()
        assert "soyadi" not in result.lower()


class TestClassifyRowsModeValidation:
    @pytest.mark.asyncio
    async def test_invalid_mode_raises_before_any_llm_call(self):
        # Ağ çağrısı yapılmadan, en baştaki doğrulamada patlamalı
        with pytest.raises(ValueError):
            await classify_rows([{"kolon": "x"}], mode="bogus-mode")
