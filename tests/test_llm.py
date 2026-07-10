import pytest

from classifier.llm import extract_json


class TestExtractJson:
    def test_plain_json_array(self):
        assert extract_json('[{"kolon": "a"}]') == [{"kolon": "a"}]

    def test_plain_json_object(self):
        assert extract_json('{"acilim": "x"}') == {"acilim": "x"}

    def test_markdown_code_fence_stripped(self):
        text = '```json\n[{"kolon": "a"}]\n```'
        assert extract_json(text) == [{"kolon": "a"}]

    def test_leading_and_trailing_prose(self):
        text = 'İşte sonuç:\n[{"kolon": "a", "guven": 0.9}]\nUmarım yardımcı olur.'
        assert extract_json(text) == [{"kolon": "a", "guven": 0.9}]

    def test_braces_inside_string_values_do_not_break_balance(self):
        text = '[{"kolon": "a", "gerekce": "içerir { ve } karakterler"}]'
        parsed = extract_json(text)
        assert parsed[0]["gerekce"] == "içerir { ve } karakterler"

    def test_escaped_quote_inside_string_does_not_break_parsing(self):
        # Başında düz metin var ki fonksiyon zorunlu olarak tarama (fallback) koluna
        # girsin; aksi hâlde tüm metin zaten geçerli JSON olduğu için doğrudan
        # json.loads yolunu kullanır ve tarayıcının escape mantığı hiç çalışmaz.
        text = 'Cevap: ' + r'[{"kolon": "a", "gerekce": "test \"tırnak\" içerir"}]'
        parsed = extract_json(text)
        assert 'tırnak' in parsed[0]["gerekce"]

    def test_nested_array_inside_object_does_not_shadow_outer_object(self):
        # Hakem çıktısı tipik biçimi: gerekçe metni + son satırda nesne; nesnenin
        # içindeki "olasi_kategoriler" dizisi dış nesneden ÖNCE yanlışlıkla
        # eşleşmemeli (bkz. llm.extract_json docstring'i).
        text = (
            "Bu kolon muhtemelen bir hesap numarasıdır çünkü tablo adı Account içeriyor.\n"
            'Sonuç: {"acilim": "Account No", "olasi_kategoriler": [5], "ana_kategori": 5, '
            '"teknik": false, "guven": 0.8, "gerekce": "test"}'
        )
        parsed = extract_json(text)
        assert isinstance(parsed, dict)
        assert parsed["ana_kategori"] == 5
        assert parsed["olasi_kategoriler"] == [5]

    def test_no_json_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_json("bu metinde hiç JSON yok")

    def test_truncated_json_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_json('[{"kolon": "a", "guven":')
