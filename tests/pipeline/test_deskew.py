import numpy as np
from PIL import Image, ImageDraw

from techbookocr.pipeline.crops import deskew_photo


def _fill(img: Image.Image) -> float:
    m = np.asarray(img.convert("L")) < 235
    ys, xs = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    return m.sum() / ((ys[-1] - ys[0] + 1) * (xs[-1] - xs[0] + 1))


def _photo(angle: float) -> Image.Image:
    rng = np.random.default_rng(0)
    photo = Image.fromarray(rng.integers(40, 200, (300, 400, 3), dtype=np.uint8))  # "photo": dark, no white
    canvas = Image.new("RGB", (560, 480), "white")
    canvas.paste(photo.rotate(angle, expand=True, fillcolor=(255, 255, 255)), (40, 30))
    return canvas


def test_tilted_photo_is_straightened():
    for angle in (3.0, -4.0):
        src = _photo(angle)
        out = deskew_photo(src)
        assert out is not src and _fill(src) < 0.95 and _fill(out) > 0.97
        assert abs(out.width - 400) <= 8 and abs(out.height - 300) <= 8


def test_straight_photo_and_line_drawing_untouched():
    straight = _photo(0.0)
    assert deskew_photo(straight) is straight
    drawing = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(drawing)
    d.line((20, 40, 380, 70), fill="black", width=3)
    d.ellipse((100, 100, 250, 250), outline="black", width=3)  # line-art sketch: little fill
    assert deskew_photo(drawing) is drawing
    assert deskew_photo(_photo(20.0)).size == _photo(20.0).size  # strong rotation is not scan skew


def test_light_rectangular_photo_straightened_but_cutout_object_kept():
    light = Image.new("RGB", (400, 300), (225, 225, 225))  # light photo: almost white inside, but with a frame
    ImageDraw.Draw(light).rectangle((0, 0, 399, 299), outline=(120, 120, 120), width=4)
    canvas = Image.new("RGB", (560, 480), "white")
    canvas.paste(light.rotate(3, expand=True, fillcolor=(255, 255, 255)), (40, 30))
    assert deskew_photo(canvas, ink=235) is not canvas
    gear = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(gear).ellipse((50, 50, 350, 350), fill=(90, 90, 90))  # an object on a white background
    assert deskew_photo(gear) is gear


def test_thin_tilted_stroke_untouched():
    line = Image.new("RGB", (800, 120), "white")
    ImageDraw.Draw(line).line((10, 30, 790, 85), fill="black", width=3)
    assert deskew_photo(line) is line
