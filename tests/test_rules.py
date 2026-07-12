from classifier.rules import (
    analyze_column,
    expand_column,
    keyword_hints,
    split_tokens,
    table_prefix_candidates,
)


class TestSplitTokens:
    def test_camel_case(self):
        assert split_tokens("customerFirstName") == ["customer", "first", "name"]

    def test_pascal_case(self):
        assert split_tokens("CustomerFirstName") == ["customer", "first", "name"]

    def test_snake_case(self):
        assert split_tokens("customer_first_name") == ["customer", "first", "name"]

    def test_consecutive_uppercase_acronym(self):
        # "IBANNo" -> "IBAN" bloğu ile "No" ayrılmalı
        assert split_tokens("IBANNo") == ["iban", "no"]

    def test_turkish_chars_preserved(self):
        assert split_tokens("müşteriAdı") == ["müşteri", "adı"]

    def test_empty_input(self):
        assert split_tokens("") == []
        assert split_tokens(None) == []

    def test_digits_kept_with_prior_lowercase(self):
        assert split_tokens("col1Name") == ["col1", "name"]


class TestTablePrefixCandidates:
    def test_multi_word_table_produces_initials(self):
        cands = table_prefix_candidates("ApplicationRequest")
        assert cands.get("ar") == "ApplicationRequest"

    def test_full_tokens_included_if_long_enough(self):
        cands = table_prefix_candidates("CustomerCard")
        assert "customer" in cands
        assert "card" in cands

    def test_short_tokens_excluded(self):
        # 3 harfli token'lar (örn. "log") rastlantısal eşleşmeyi önlemek için hariç
        cands = table_prefix_candidates("LogEntry")
        assert "log" not in cands

    def test_empty_table_name(self):
        assert table_prefix_candidates("") == {}


class TestExpandColumn:
    def test_prefix_match_produces_note(self):
        result = expand_column("ccCardNo", "CustomerCard")
        assert result["prefix"] == "cc"
        assert "CustomerCard" in result["note"]

    def test_no_prefix_match_no_note(self):
        result = expand_column("randomColumn", "SomeOtherTable")
        assert result["prefix"] is None
        assert result["note"] == ""

    def test_prefix_must_leave_remainder(self):
        # Kolon adı öneğin tamamına eşitse (kalan yoksa) eşleşme sayılmaz
        result = expand_column("cc", "CustomerCard")
        assert result["prefix"] is None


class TestKeywordHints:
    def test_direct_hit(self):
        hits = keyword_hints(["tckn"])
        assert hits["tckn"] == [1]

    def test_joined_token_hit(self):
        # "hesap" + "no" ayrı token; ayrıca birleşik "hesapno" sözlükte var
        hits = keyword_hints(["hesap", "no"])
        assert hits.get("hesapno") == [5]

    def test_no_hits(self):
        assert keyword_hints(["xyz123nonsense"]) == {}

    def test_multi_category_hint(self):
        assert keyword_hints(["sifre"]) == {"sifre": [6, 7]}


class TestAnalyzeColumn:
    def test_full_pipeline_with_prefix_and_hint(self):
        result = analyze_column("ccCardNo", "CustomerCard")
        assert result["note"]
        assert "no" in result["tokens"] or "card" in result["tokens"]

    def test_falls_back_to_full_column_tokens_without_prefix(self):
        result = analyze_column("salary", "Payroll")
        assert "salary" in result["tokens"]
        assert result["hints"].get("salary") == [3]
