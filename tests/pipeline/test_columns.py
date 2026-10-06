import numpy as np
from PIL import Image, ImageDraw

from techbookocr.pipeline.columns import column_rules, value_spans


def sheet(rule_x=(200, 400), text=((60, 40, 120, 60), (250, 40, 350, 60))) -> Image.Image:
    img = Image.new("L", (600, 120), 255)
    d = ImageDraw.Draw(img)
    for x in rule_x:
        d.line((x, 0, x, 119), fill=0, width=3)
    for box in text:
        d.rectangle(box, fill=40)
    return img


def test_column_rules_found():
    assert column_rules(sheet()) == [200, 400]


def test_no_rules_when_absent():
    assert column_rules(Image.new("L", (600, 120), 255)) == []


def test_value_span_crossing_a_rule():
    """A value printed centered between rulings overlaps ruling 200."""
    img = sheet(text=((150, 40, 260, 60),))
    spans = value_spans(img, [200, 400], (0, 30, 600, 70))
    assert spans == [(150, 260)]
