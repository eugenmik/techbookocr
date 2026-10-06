from techbookocr.eval.teds import teds

GOLD = (
    "<table><tr><td rowspan='2'>Нагрузка</td><td>d</td><td>H</td></tr>"
    "<tr><td>3</td><td>40—250</td></tr></table>"
)


def test_identical_is_one():
    assert teds(GOLD, GOLD) == 1.0


def test_content_error_reduces_score():
    pred = GOLD.replace("40—250", "40—260")
    s = teds(pred, GOLD)
    assert 0.8 < s < 1.0
    assert teds(pred, GOLD, structure_only=True) == 1.0


def test_lost_rowspan_penalized():
    pred = GOLD.replace(" rowspan='2'", "")
    assert teds(pred, GOLD) < 1.0


def test_garbage_is_zero():
    assert teds("no table here", GOLD) == 0.0


def test_malformed_rowspan_degrades_gracefully():
    """Test that invalid rowspan (e.g., non-numeric) doesn't raise."""
    pred = GOLD.replace("rowspan='2'", "rowspan='x'")
    # Should not raise, should degrade to a score
    s = teds(pred, GOLD)
    assert 0.0 <= s <= 1.0


def test_malformed_rowspan_equals_rowspan_removed():
    bad = GOLD.replace("rowspan='2'", "rowspan='x'")
    assert teds(bad, GOLD) == teds(GOLD.replace(" rowspan='2'", ""), GOLD)


def test_br_in_cell_is_space():
    a = "<table><tr><td>a<br>b</td></tr></table>"
    assert teds(a, "<table><tr><td>a b</td></tr></table>") == 1.0
