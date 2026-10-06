import pytest

from techbookocr.models.types import clamp_bbox


@pytest.mark.parametrize("b,expected", [
    ((10.4, 20.6, 50.2, 60.5), (10, 21, 50, 60)),
    ((-5, -5, 50, 50), (0, 0, 50, 50)),
    ((10, 10, 5000, 6000), (10, 10, 100, 200)),
    ((50, 10, 20, 40), None),
    ((10, 50, 40, 20), None),
    ((10, 10, 10, 40), None),
    ((float("nan"), 0, 5, 5), None),
    ((0, 0, float("inf"), 5), None),
    ((300, 300, 400, 400), None),  # entirely outside the page
    ((1, 2, 3), None),
    (("a", 0, 1, 1), None),
    (None, None),
])
def test_clamp_bbox(b, expected):
    assert clamp_bbox(b, (100, 200)) == expected
