from techbookocr.eval.normalize import extract_numbers, fix_homoglyphs, normalize_text


def test_homoglyphs_only_in_cyrillic_words():
    assert fix_homoglyphs("MOCKBA и Москва") == "MOCKBA и Москва"  # word entirely in Latin letters: leave it alone
    assert fix_homoglyphs("пpимеcь FeO") == "примесь FeO"


def test_normalize_dashes_quotes_times():
    assert normalize_text("Отливка «Фланец»  15–25 и 500×400") == 'Отливка "Фланец" 15-25 и 500x400'
    assert normalize_text("500 х 400") == "500 x 400"  # Cyrillic kha between numbers
    assert normalize_text("2{,}2 W") == "2,2 W"


def test_normalize_keeps_decimal_comma_and_yo():
    assert normalize_text("0,18% жёлоб") == "0,18% жёлоб"


def test_extract_numbers():
    assert extract_numbers("при 12—15%-ном расходе, t = 1350°C, d = 0,5") == ["12", "15", "1350", "0,5"]


def test_curly_quotes():
    assert normalize_text("“A” ‘b’ „C“") == '"A" \'b\' "C"'


def test_inequality_text_survives_and_entities():
    from techbookocr.eval.normalize import strip_html
    s = "при t < 500 °C и s > 300 МПа"
    assert normalize_text(strip_html(s)) == s
    assert normalize_text("a &lt; b") == normalize_text("a < b") == "a < b"
    assert normalize_text(strip_html("x<sup>2</sup>H<sub>2</sub>O a<br/>b")) == "x2H2O a b"


def test_super_subscripts_and_exponents_consistent():
    assert normalize_text("см³ H₂O 10⁻³") == "см3 H2O 10-3"
    assert extract_numbers("10^{-3}") == extract_numbers("10⁻³") == ["10", "3"]
    assert extract_numbers("H_{2}O x^3") == extract_numbers("H₂O x³")


def test_thousands_separators():
    assert extract_numbers("1 350 000") == extract_numbers("1350000") == ["1350000"]
    assert extract_numbers("1 350 м") == ["1350"]
    assert extract_numbers("15 25 и 7 8") == ["15", "25", "7", "8"]


def test_times_only_between_bare_numbers():
    assert normalize_text("500 х 400") == "500 x 400"
    assert normalize_text("500×400") == "500x400"
    assert normalize_text("500 х 400 х 300") == "500 x 400 x 300"
    steel = "сталь 12\u042518\u041d10\u0422"  # Cyrillic Kha, En, Te
    assert normalize_text(steel) == steel


def test_leading_minus():
    assert extract_numbers("−40 °C") == ["-40"]
    assert extract_numbers("-40") == ["-40"]
    assert extract_numbers("t (-5) и 15-25") == ["-5", "15", "25"]
