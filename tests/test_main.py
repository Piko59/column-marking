import pytest
from fastapi import HTTPException

from main import _cell, _map_headers, _norm_header


class TestNormHeader:
    def test_lowercases_and_strips_turkish_accents(self):
        assert _norm_header("Kolon Adı") == "kolonadi"
        assert _norm_header("ŞEMA") == "sema"

    def test_none_becomes_empty(self):
        assert _norm_header(None) == ""


class TestMapHeaders:
    def test_turkish_headers(self):
        headers = ["Sunucu Ad", "Veri Tabanı Ad", "Şema Ad", "Tablo Ad", "Kolon Ad",
                   "Kolon Sıra No", "Kolon Veri Tipi", "Uzunluk", "Kuruş",
                   "Null Flag", "PK Flag"]
        mapping = _map_headers(headers)
        assert mapping[headers.index("Kolon Ad")] == "kolon"
        assert mapping[headers.index("Tablo Ad")] == "tablo"
        assert mapping[headers.index("Şema Ad")] == "sema"

    def test_english_headers(self):
        headers = ["SERVER", "DATABASE", "SCHEMA", "TABLE_NAME", "COLUMN_NAME", "DATATYPE"]
        mapping = _map_headers(headers)
        assert mapping[4] == "kolon"
        assert mapping[3] == "tablo"
        assert mapping[2] == "sema"

    def test_alternate_column_header_spelling(self):
        # README: "Kolon Ad", "Kolon Adı", "COLUMN_NAME" hepsi çalışmalı
        for label in ("Kolon Ad", "Kolon Adı", "COLUMN_NAME", "column_name"):
            mapping = _map_headers([label])
            assert mapping[0] == "kolon"

    def test_missing_column_header_raises(self):
        with pytest.raises(HTTPException) as exc:
            _map_headers(["Sunucu", "Veri Tabanı", "Şema"])
        assert exc.value.status_code == 400

    def test_first_matching_column_wins_when_duplicates(self):
        # Aynı alan için birden fazla aday sütun varsa ilk eşleşen bağlanır
        mapping = _map_headers(["Kolon Ad", "Kolon Adı (2)"])
        assert mapping == {0: "kolon"}

    def test_sira_no_does_not_collide_with_sema(self):
        # "sira" kelimesi "sema"nın alt dizgisi değil ama regresyon için garanti altına al
        mapping = _map_headers(["Şema Ad", "Kolon Sıra No", "Kolon Ad"])
        assert mapping[0] == "sema"
        assert mapping[1] == "sira"
        assert mapping[2] == "kolon"


class TestCell:
    def test_none_becomes_empty_string(self):
        assert _cell(None) == ""

    def test_integer_float_loses_decimal(self):
        assert _cell(26.0) == "26"

    def test_non_integer_float_keeps_value(self):
        assert _cell(26.5) == "26.5"

    def test_string_is_stripped(self):
        assert _cell("  varchar  ") == "varchar"

    def test_int_passthrough(self):
        assert _cell(1) == "1"
