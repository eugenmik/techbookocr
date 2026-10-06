from PIL import Image, ImageDraw

from techbookocr.pipeline.crops import PageImages, crop_block, line_height, pad_box, save_image


def _lines(h_line, gap=20, n=4, width=400):
    img = Image.new("RGB", (width, n * (h_line + gap) + gap), "white")
    d = ImageDraw.Draw(img)
    for i in range(n):
        y = gap + i * (h_line + gap)
        d.rectangle([20, y, width - 20, y + h_line - 1], fill="black")
    return img


def test_pad_box_clamps():
    assert pad_box((5, 5, 95, 95), (100, 100), 12) == (0, 0, 100, 100)
    assert pad_box((20, 30, 40, 50), (100, 100), 8) == (12, 22, 48, 58)


def test_line_height():
    assert line_height(_lines(10)) == 10
    assert line_height(_lines(40)) == 40
    assert line_height(Image.new("RGB", (50, 50), "white")) is None


def test_line_height_ignores_table_rules():
    img = _lines(10, width=600)
    d = ImageDraw.Draw(img)
    for x in (5, 300, 594):
        d.line([x, 0, x, img.height], fill="black", width=3)
    assert line_height(img) == 10


def test_crop_block_upscales_small_text():
    page = _lines(10)
    crop = crop_block(page, (0, 0, page.width, page.height), pad=0, min_line_px=32)
    assert crop.size == (round(page.width * 3.2), round(page.height * 3.2))
    big = _lines(40)
    assert crop_block(big, (0, 0, big.width, big.height), pad=0).size == big.size


def test_crop_block_upscale_capped():
    page = _lines(4)
    crop = crop_block(page, (0, 0, page.width, page.height), pad=0, min_line_px=32, max_upscale=4.0)
    assert crop.size == (page.width * 4, page.height * 4)


def test_save_image_atomic_and_page_cache(tmp_path):
    save_image(Image.new("RGB", (10, 10), "red"), tmp_path / "images" / "p0001_fig1.png")
    assert (tmp_path / "images" / "p0001_fig1.png").exists()
    assert not list((tmp_path / "images").glob("*.tmp"))
    imgs = PageImages(tmp_path, {"0001": "images/p0001_fig1.png"})
    a = imgs.get("0001")
    assert a.size == (10, 10) and imgs.get("0001") is a


def test_save_image_webp_by_suffix(tmp_path):
    """Format by extension: .webp is lossy WebP (noticeably smaller than PNG), .png is as before."""
    import numpy as np

    rng = np.random.default_rng(0)
    img = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))  # noise is the worst case for the codec
    save_image(img, tmp_path / "f.webp")
    save_image(img, tmp_path / "f.png")
    with Image.open(tmp_path / "f.webp") as im:
        assert im.format == "WEBP" and im.size == (400, 300)
    assert (tmp_path / "f.webp").stat().st_size < (tmp_path / "f.png").stat().st_size
    save_image(Image.new("P", (10, 10)), tmp_path / "pal.webp")  # unsupported mode -> RGB
    with Image.open(tmp_path / "pal.webp") as im:
        assert im.format == "WEBP"


def test_save_image_webp_quality_param(tmp_path):
    """quality= controls lossy WebP: q20 is noticeably smaller than q90, both are valid."""
    import numpy as np

    rng = np.random.default_rng(0)
    img = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))
    save_image(img, tmp_path / "low.webp", quality=20)
    save_image(img, tmp_path / "high.webp", quality=90)
    assert (tmp_path / "low.webp").stat().st_size < (tmp_path / "high.webp").stat().st_size
    for name in ("low.webp", "high.webp"):
        with Image.open(tmp_path / name) as im:
            assert im.format == "WEBP" and im.size == (400, 300)


def test_crop_block_respects_max_pixels():
    """Large crop should downscale if it exceeds max_pixels."""
    # 2500x3500 crop = 8.75 MP, max_pixels=6M → scale = sqrt(6/8.75) ≈ 0.828
    page = Image.new("RGB", (2500, 3500), "white")
    crop = crop_block(page, (0, 0, 2500, 3500), pad=0, min_line_px=32, max_pixels=6_000_000)
    pixels = crop.width * crop.height
    assert pixels <= 6_000_000, f"crop {crop.size} = {pixels} pixels > 6M"


def test_crop_block_upscale_respects_max_pixels():
    """Upscaling should not exceed max_pixels limit."""
    page = _lines(10, width=2500, n=500)  # 2500x10500, thin text
    crop = crop_block(page, (0, 0, 2500, 10500), pad=0, min_line_px=32, max_pixels=6_000_000)
    pixels = crop.width * crop.height
    assert pixels <= 6_000_000, f"upscaled crop {crop.size} = {pixels} pixels > 6M"


def test_crop_block_single_resize_never_exceeds_max_pixels():
    """Verify no intermediate resize exceeds max_pixels (monkeypatch Image.resize)."""
    resize_calls = []
    original_resize = Image.Image.resize

    def tracked_resize(self, size, *args, **kwargs):
        pixels = size[0] * size[1]
        resize_calls.append((size, pixels))
        return original_resize(self, size, *args, **kwargs)

    Image.Image.resize = tracked_resize
    try:
        # Big crop (8.75 MP) that needs upscaling but exceeds max_pixels
        page = Image.new("RGB", (2500, 3500), "white")
        crop = crop_block(page, (0, 0, 2500, 3500), pad=0, min_line_px=32, max_pixels=6_000_000)

        # Should have exactly one resize call
        assert len(resize_calls) == 1, f"expected 1 resize, got {len(resize_calls)}: {resize_calls}"

        # That single resize should not exceed max_pixels
        size, pixels = resize_calls[0]
        assert pixels <= 6_000_000, f"resize to {size} = {pixels} pixels exceeds 6M"

        # Result should also not exceed max_pixels
        result_pixels = crop.width * crop.height
        assert result_pixels <= 6_000_000, f"final crop {crop.size} = {result_pixels} pixels > 6M"
    finally:
        Image.Image.resize = original_resize


def test_crop_block_mask_paints_white():
    import numpy as np
    from PIL import Image
    from techbookocr.pipeline.crops import crop_block
    page = Image.new("RGB", (400, 300), (0, 0, 0))
    crop = crop_block(page, (100, 100, 300, 200), 0, min_line_px=1, mask=((150, 120, 250, 180),))
    a = np.asarray(crop)
    assert a[30, 100].tolist() == [255, 255, 255] and a[5, 5].tolist() == [0, 0, 0]
    assert np.asarray(page)[150, 200].tolist() == [0, 0, 0]  # the source page is untouched
