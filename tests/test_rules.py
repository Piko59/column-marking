from classifier.rules import (
    analyze_column,
    expand_column,
    keyword_hints,
    mask_sample,
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


class TestMaskSample:
    def test_empty_value(self):
        assert mask_sample("") == ""

    def test_medium_numeric_keeps_first_and_last_char(self):
        assert mask_sample("123456") == "1****6"

    def test_long_numeric_keeps_two_chars_each_side(self):
        v = "TR330006100519786457841326"  # örnek IBAN biçimi (rakam ağırlıklı)
        result = mask_sample(v)
        assert result.startswith("TR")
        assert result.endswith("26")
        assert len(result) == len(v)

    def test_length_always_preserved(self):
        v = "12345678901"  # TCKN uzunluğu
        assert len(mask_sample(v)) == len(v)

    def test_strips_whitespace_before_masking(self):
        assert mask_sample("  12  ") == "**"

    # --- metinsel değerler: içerik hiç sızmaz, yalnız desen ---
    def test_textual_value_fully_patterned(self):
        # Kısa/az seçenekli metinlerde baş-son karakter bile sızdırılmaz
        # (eski davranış "İ***m" idi; "İslam" tahmin edilebiliyordu)
        assert mask_sample("İslam") == "Xxxxx"

    def test_textual_pattern_preserves_structure(self):
        assert mask_sample("0 Rh+") == "9 Xx+"

    def test_short_textual_patterned(self):
        assert mask_sample("ab") == "xx"

    def test_email_pattern_keeps_at_and_dots(self):
        result = mask_sample("ahmety85@gmail.com")
        assert "@" in result and "." in result
        assert "gmail" not in result and "ahmety" not in result

    def test_name_not_leaked(self):
        result = mask_sample("Ahmet Yılmaz")
        assert "Ah" not in result and "az" not in result
        assert result == "Xxxxx Xxxxxx"


class TestAnalyzeColumn:
    def test_full_pipeline_with_prefix_and_hint(self):
        result = analyze_column("ccCardNo", "CustomerCard")
        assert result["note"]
        assert "no" in result["tokens"] or "card" in result["tokens"]

    def test_falls_back_to_full_column_tokens_without_prefix(self):
        result = analyze_column("salary", "Payroll")
        assert "salary" in result["tokens"]
        assert result["hints"].get("salary") == [3]
