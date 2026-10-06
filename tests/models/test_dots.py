import json

from PIL import Image

from techbookocr.config import ModelSpec
from techbookocr.models.adapters.dots import DotsAdapter, fit_pixels, parse_dots, smart_resize

RAW = json.dumps([
    {"bbox": [0, 0, 1624, 2436], "category": "Text", "text": "Чугун марки СЧ20"},
    {"bbox": [812, 1218, 1624, 2436], "category": "Picture"},
    {"bbox": [0, 0, 28, 28], "category": "Weird", "text": "x"},
])


def test_smart_resize_matches_reference():
    assert smart_resize(2449, 1633) == (2436, 1624)


def test_parse_maps_bbox_to_original():
    blocks = parse_dots(RAW, orig_size=(2000, 3000), sent_size=(1633, 2449))
    x1, y1, x2, y2 = blocks[0].bbox
    assert (x1, y1) == (0, 0) and abs(x2 - 2000) <= 1 and abs(y2 - 3000) <= 1
    assert blocks[1].category == "Picture" and blocks[1].text == ""
    assert blocks[2].category == "Text"
    assert [b.order for b in blocks] == [0, 1, 2]


def test_truncated_json_salvaged():
    blocks = parse_dots(RAW[:-30], orig_size=(2000, 3000), sent_size=(1633, 2449))
    assert [b.category for b in blocks] == ["Text", "Picture"]
    assert blocks[0].text == "Чугун марки СЧ20"


def test_garbage_becomes_single_text_block():
    blocks = parse_dots("не JSON вовсе", orig_size=(10, 10), sent_size=(10, 10))
    assert [(b.category, b.text) for b in blocks] == [("Text", "не JSON вовсе")]


def test_fit_pixels():
    img = fit_pixels(Image.new("RGB", (2000, 3000)), 4_000_000)
    w, h = img.size
    assert w * h <= 4_000_000 and abs(w / h - 2000 / 3000) < 0.01
    small = Image.new("RGB", (100, 100))
    assert fit_pixels(small, 4_000_000) is small


def test_prompt_has_image_prefix():
    a = DotsAdapter(ModelSpec(key="d", adapter="dots", image="i", model="dots"), None, "http://x")
    assert a.prompt().startswith("<|img|><|imgpad|><|endofimg|>Please output the layout information from the PDF image")


def test_single_object_no_crash():
    """Controller fix (a): single object should not crash and return 1 Text block."""
    raw = json.dumps({"bbox": [0, 0, 1624, 2436], "category": "Text", "text": "a"})
    blocks = parse_dots(raw, orig_size=(2000, 3000), sent_size=(1633, 2449))
    assert len(blocks) == 1 and blocks[0].category == "Text" and blocks[0].text == "a"


def test_array_of_numbers_no_crash():
    """Controller fix (b): array of numbers should not crash and return Text block of raw."""
    raw = json.dumps([1, 2])
    blocks = parse_dots(raw, orig_size=(10, 10), sent_size=(10, 10))
    # No dict cells, so falls back to single Text block with raw
    assert len(blocks) == 1 and blocks[0].category == "Text"


def test_bbox_with_fewer_than_4_numbers_no_crash():
    """Controller fix (c): bbox with <4 numbers should not crash, set bbox=None."""
    raw = json.dumps([
        {"bbox": [0, 0], "category": "Text", "text": "short"},
        {"bbox": [0, 0, 100], "category": "Text", "text": "three"},
        {"bbox": None, "category": "Text", "text": "null"},
    ])
    blocks = parse_dots(raw, orig_size=(100, 100), sent_size=(100, 100))
    assert len(blocks) == 3
    assert all(b.text for b in blocks)
    # All should have bbox=None due to invalid bbox values
    assert all(b.bbox is None for b in blocks)


def test_server_cap_used_for_bbox_mapping():
    # 3000x2000 sent; a 1_000_000 server cap resizes it, so bbox must map through that cap
    raw = json.dumps([{"bbox": [0, 0, 600, 400], "category": "Text", "text": "a"}])
    big = parse_dots(raw, (3000, 2000), (3000, 2000), server_max_pixels=4_000_000)[0].bbox
    small = parse_dots(raw, (3000, 2000), (3000, 2000), server_max_pixels=1_000_000)[0].bbox
    assert big != small


def test_client_target_must_be_below_server_cap():
    import pytest

    spec = ModelSpec(key="d", adapter="dots", image="i", model="dots", params={"max_pixels": 4_000_000})
    with pytest.raises(ValueError, match="server_max_pixels"):
        DotsAdapter(spec, None, "http://x")
    ok = DotsAdapter(ModelSpec(key="d", adapter="dots", image="i", model="dots"), None, "http://x")
    assert ok.params["max_pixels"] < ok.params["server_max_pixels"]


def test_dots_bbox_clamped():
    raw = json.dumps([{"bbox": [-50, -50, 99999, 99999], "category": "Text", "text": "a"},
                      {"bbox": [500, 500, 100, 100], "category": "Text", "text": "b"}])
    blocks = parse_dots(raw, (1000, 1000), (1000, 1000))
    assert blocks[0].bbox == (0, 0, 1000, 1000) and blocks[1].bbox is None
