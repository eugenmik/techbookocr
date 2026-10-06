from techbookocr.pipeline.postproc.homoglyphs import cyrillic_context, fix_homoglyphs_text, is_chemical


def test_codes_fixed_but_real_latin_kept():
    src = ("Сита 173M1 и 175M.10.000 из стали Л16X; сталь содержит Mn и Fe, предел 400 MPa, "
           "твёрдость HB 200, газы CO2 и окалина Fe3O4, чугyн.")
    out = fix_homoglyphs_text(src)
    assert "173М1" in out and "175М.10.000" in out and "Л16Х" in out and "чугун" in out
    for kept in ("Mn", "Fe,", "MPa", "HB 200", "CO2", "Fe3O4"):
        assert kept in out, kept
    assert "M" not in out.replace("Mn", "").replace("MPa", "")


def test_math_html_and_english_untouched():
    assert fix_homoglyphs_text("Model 173M1 is used with 400 MPa") == "Model 173M1 is used with 400 MPa"
    src = 'в формуле $M_1 = 173M1$ и шифре 173M1 <td class="M1">Сито 173M1</td>'
    out = fix_homoglyphs_text(src)
    assert "$M_1 = 173M1$" in out and 'class="M1"' in out
    assert out.count("173М1") == 2


def test_helpers():
    assert is_chemical("CO2") and is_chemical("Fe3O4") and is_chemical("SiO2")
    assert not is_chemical("173M1") and not is_chemical("M1") and not is_chemical("K02A")
    assert cyrillic_context("Чугун марки СЧ20 $x_{abc}$") and not cyrillic_context("Steel grade 45")


def test_protected_metallurgical_notation():
    """Materials-science designations are never converted to Cyrillic."""
    src = "Зона Ac1 и Ac3, точка Acm; сталь Ar1, A3, температура Ms и Mf; твёрдость HRC45, HRC 50."
    out = fix_homoglyphs_text(src)
    # All protected notations should remain unchanged
    for protected in ("Ac1", "Ac3", "Acm", "Ar1", "A3", "Ms", "Mf", "HRC45", "HRC"):
        assert protected in out, f"Protected notation {protected} was incorrectly converted"
    # Should not have Cyrillic A, C, etc. from these tokens
    assert "Ас1" not in out and "А3" not in out
