import pytest

import config
from classifier import llm, prompts
from classifier.pipeline import (
    _anonymize,
    _cache_key,
    _classify_multi_group,
    _error_result,
    _pack_into_superbatches,
    _sanitize,
    classify_rows,
)


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


def _col(kolon):
    return {"kolon": kolon}


class TestPackIntoSuperbatches:
    def test_combines_small_groups_within_limit(self):
        pending = {
            ("s", "t1"): [(0, _col("a"))],
            ("s", "t2"): [(1, _col("b"))],
        }
        sb = _pack_into_superbatches(pending, batch_size=5)
        assert len(sb) == 1
        assert len(sb[0]) == 2  # iki grup tek süper-batch'te birleşti

    def test_splits_into_new_superbatch_when_limit_exceeded(self):
        pending = {
            ("s", "t1"): [(0, _col("a")), (1, _col("b")), (2, _col("c"))],
            ("s", "t2"): [(3, _col("d"))],
        }
        sb = _pack_into_superbatches(pending, batch_size=3)
        assert len(sb) == 2  # t1 tek başına dolduruyor; t2 ayrı süper-batch

    def test_oversized_single_group_chunked_alone_not_merged(self):
        items = [(i, _col(f"c{i}")) for i in range(7)]
        pending = {("s", "big"): items}
        sb = _pack_into_superbatches(pending, batch_size=3)
        assert len(sb) == 3  # 7 kolon / 3'lük parçalar -> 3,3,1
        assert all(len(group) == 1 for group in sb)  # her parça tek tablo, birleştirme yok
        sizes = sorted(len(items) for group in sb for _, items in group)
        assert sizes == [1, 3, 3]

    def test_empty_pending_returns_empty(self):
        assert _pack_into_superbatches({}, batch_size=25) == []

    def test_all_items_preserved_across_superbatches(self):
        pending = {
            ("s", "t1"): [(0, _col("a")), (1, _col("b"))],
            ("s", "t2"): [(2, _col("c"))],
            ("s", "t3"): [(3, _col("d")), (4, _col("e")), (5, _col("f"))],
        }
        sb = _pack_into_superbatches(pending, batch_size=4)
        all_idxs = sorted(idx for group in sb for _, items in group for idx, _ in items)
        assert all_idxs == [0, 1, 2, 3, 4, 5]


class TestBuildMultiTablePrompt:
    def test_renders_a_section_per_table(self):
        prompt = prompts.build_multi_table_prompt([
            ("dbo", "Personel", [{"kolon": "persAdSoyad", "veri_tipi": "varchar", "uzunluk": "100"}]),
            ("risk", "OperasyonRisk", [{"kolon": "oprFindeksSkor", "veri_tipi": "int", "uzunluk": ""}]),
        ])
        assert "=== TABLO: Personel (ŞEMA: dbo) ===" in prompt
        assert "=== TABLO: OperasyonRisk (ŞEMA: risk) ===" in prompt
        assert "persAdSoyad" in prompt
        assert "oprFindeksSkor" in prompt

    def test_column_numbering_is_global_across_tables(self):
        prompt = prompts.build_multi_table_prompt([
            ("s", "t1", [{"kolon": "a"}, {"kolon": "b"}]),
            ("s", "t2", [{"kolon": "c"}]),
        ])
        assert "1. a" in prompt
        assert "2. b" in prompt
        assert "3. c" in prompt  # t2'nin ilk kolonu 1'e değil 3'e devam ediyor

    def test_instructs_model_to_echo_table_field(self):
        prompt = prompts.build_multi_table_prompt([("s", "t1", [{"kolon": "a"}])])
        assert '"tablo"' in prompt


class TestClassifyMultiGroup:
    @pytest.mark.asyncio
    async def test_disambiguates_same_column_name_across_tables_by_table_field(self, monkeypatch):
        # İki farklı tabloda AYNI isimde kolon var ("id"); model her ikisini de farklı
        # kategoriyle dönüyor ve "tablo" alanıyla hangisinin hangisi olduğunu belirtiyor.
        async def fake_chat(system, user, temperature=None):
            import json
            return json.dumps([
                {"tablo": "TabloA", "kolon": "id", "olasi_kategoriler": [5], "ana_kategori": 5,
                 "teknik": False, "guven": 0.9, "gerekce": "A"},
                {"tablo": "TabloB", "kolon": "id", "olasi_kategoriler": [4], "ana_kategori": 4,
                 "teknik": False, "guven": 0.9, "gerekce": "B"},
            ])

        monkeypatch.setattr(llm, "chat", fake_chat)
        table_groups = [
            ("s", "TabloA", [{"kolon": "id", "veri_tipi": "int"}]),
            ("s", "TabloB", [{"kolon": "id", "veri_tipi": "int"}]),
        ]
        results = await _classify_multi_group(table_groups)
        assert len(results) == 2
        assert results[0]["ana_kategori"] == 5  # TabloA.id
        assert results[1]["ana_kategori"] == 4  # TabloB.id

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error_for_every_column(self, monkeypatch):
        async def failing_chat(system, user, temperature=None):
            raise RuntimeError("boom")

        monkeypatch.setattr(llm, "chat", failing_chat)
        table_groups = [("s", "t1", [{"kolon": "a"}, {"kolon": "b"}])]
        results = await _classify_multi_group(table_groups)
        assert len(results) == 2
        assert all(r["kaynak"] == "hata" for r in results)
