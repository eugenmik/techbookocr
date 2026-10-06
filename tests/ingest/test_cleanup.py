from PIL import Image, ImageDraw

from techbookocr.ingest.cleanup import crop_dark_borders, deskew, estimate_skew


def _lines_page() -> Image.Image:
    img = Image.new("RGB", (1200, 1600), "white")
    d = ImageDraw.Draw(img)
    for y in range(150, 1450, 30):
        d.rectangle([120, y, 1080, y + 12], fill="black")
    return img


def test_estimate_skew_recovers_rotation():
    skewed = _lines_page().rotate(1.5, fillcolor="white")
    angle = estimate_skew(skewed)
    assert abs(angle + 1.5) < 0.2


def test_straight_page_not_rotated():
    img = _lines_page()
    out, angle = deskew(img)
    assert angle == 0.0
    assert out is img


def test_deskew_rotates_skewed_page():
    skewed = _lines_page().rotate(-2.0, fillcolor="white")
    _, angle = deskew(skewed)
    assert abs(angle - 2.0) < 0.2


def test_crop_dark_borders():
    img = Image.new("RGB", (1000, 1400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 39, 1399], fill="black")  # 40px on the left
    d.rectangle([0, 0, 999, 24], fill="black")  # 25px on top
    d.rectangle([300, 500, 700, 520], fill="black")  # leave the text alone
    out = crop_dark_borders(img)
    assert out.size == (960, 1375)


def test_crop_limited_for_dark_page():
    img = Image.new("RGB", (1000, 1000), "black")
    out = crop_dark_borders(img)
    assert out.size[0] >= 700 and out.size[1] >= 700
