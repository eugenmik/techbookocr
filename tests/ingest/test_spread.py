import random

import pytest
from PIL import Image, ImageDraw

from techbookocr.ingest.spread import find_gutter, split_spread


def _text_page(w: int, h: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for y in range(int(h * 0.08), int(h * 0.92), 28):
        x = int(w * 0.08)
        while x < w * 0.92:
            word = rnd.randint(20, 70)
            d.rectangle([x, y, min(x + word, int(w * 0.92)), y + 14], fill="black")
            x += word + rnd.randint(8, 14)
    return img


def _spread(gap_fill: str = "white") -> tuple[Image.Image, int]:
    left, right = _text_page(1100, 1600, 1), _text_page(1100, 1600, 2)
    img = Image.new("RGB", (2260, 1600), "white")
    img.paste(left, (0, 0))
    img.paste(right, (1160, 0))
    if gap_fill != "white":
        ImageDraw.Draw(img).rectangle([1110, 0, 1150, 1600], fill=gap_fill)
    return img, 1130


def test_white_gutter_found():
    img, gx = _spread()
    x = find_gutter(img)
    assert x is not None and abs(x - gx) < 40


def test_dark_shadow_gutter_found():
    img, gx = _spread(gap_fill=(40, 40, 40))
    x = find_gutter(img)
    assert x is not None and abs(x - gx) < 40


def test_wide_single_table_not_split():
    # landscape insert: a table with ruling lines and text across the center
    img = Image.new("RGB", (2400, 1600), "white")
    d = ImageDraw.Draw(img)
    for y in range(100, 1500, 60):
        d.line([100, y, 2300, y], fill="black", width=3)
    for x in range(100, 2301, 200):
        d.line([x, 100, x, 1480], fill="black", width=3)
    for y in range(115, 1480, 60):
        for x in range(120, 2280, 200):
            d.rectangle([x, y, x + 120, y + 14], fill="black")
    assert find_gutter(img) is None
    assert [s for s, _ in split_spread(img, "auto")] == [""]


def test_portrait_page_not_split():
    img = _text_page(1100, 1600, 3)
    assert [s for s, _ in split_spread(img, "auto")] == [""]


def test_split_produces_two_halves():
    img, _ = _spread()
    parts = split_spread(img, "auto")
    assert [s for s, _ in parts] == ["L", "R"]
    assert sum(p.size[0] for _, p in parts) == img.size[0]


def test_never_mode():
    img, _ = _spread()
    assert [s for s, _ in split_spread(img, "never")] == [""]


@pytest.mark.books
@pytest.mark.parametrize("max_dpi", [150, 300])
@pytest.mark.parametrize(
    "fixture,index",
    [("saf_path", 19), ("saf_path", 20), ("saf_path", 100),
     ("gir_path", 20), ("gir_path", 150), ("gir_path", 300)],
)
def test_real_book_spreads_split(request, fixture, index, max_dpi):
    from techbookocr.ingest.djvu import DjvuDocument

    with DjvuDocument(request.getfixturevalue(fixture)) as doc:
        img, _ = doc.render(index, max_dpi=max_dpi)
    x = find_gutter(img)
    w = img.size[0]
    assert x is not None and 0.40 * w < x < 0.60 * w, (x, w)


@pytest.mark.books
def test_resolution_invariance(gir_path):
    from techbookocr.ingest.djvu import DjvuDocument

    with DjvuDocument(gir_path) as doc:
        img_300, _ = doc.render(150, max_dpi=300)
        img_150, _ = doc.render(150, max_dpi=150)
    x_300 = find_gutter(img_300)
    x_150 = find_gutter(img_150)
    assert x_300 is not None and x_150 is not None
    assert abs(x_300 / img_300.size[0] - x_150 / img_150.size[0]) < 0.02


@pytest.mark.books
def test_voronin_portrait_page_not_split(vor_path):
    from techbookocr.ingest.djvu import DjvuDocument

    with DjvuDocument(vor_path) as doc:
        img, _ = doc.render(60, max_dpi=150)
    assert len(split_spread(img, "auto")) == 1
