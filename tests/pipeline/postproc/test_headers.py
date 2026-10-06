from techbookocr.pipeline.postproc.headers import analyze_headers, consistent_numbers
from techbookocr.pipeline.state import BlockRow, PageRow


def _b(bid, page, ord_, category, text, bbox):
    return BlockRow(id=bid, page=page, ord=ord_, category=category, text_a=text, bbox=bbox)


def test_running_headers_and_page_numbers():
    pages = [PageRow(name=f"{i:04d}", idx=i, height=1400) for i in range(4)]
    blocks = []
    for i, p in enumerate(pages):
        blocks += [_b(10 * i + 1, p.name, 0, "Text", "ЛИТЕЙНЫЕ МАШИНЫ", (100, 20, 600, 60)),
                   _b(10 * i + 2, p.name, 1, "Text", "Обычный абзац", (100, 200, 900, 400)),
                   _b(10 * i + 3, p.name, 2, "Page-footer", str(201 + i), (450, 1340, 550, 1390))]
    info = analyze_headers(pages, blocks)
    assert {b.text_a for b in blocks if b.id in info.drop} == {"ЛИТЕЙНЫЕ МАШИНЫ", "201", "202", "203", "204"}
    assert info.printed == {"0000": "201", "0001": "202", "0002": "203", "0003": "204"}


def test_caption_in_header_kept_and_unique_top_text_kept():
    pages = [PageRow(name=f"{i:04d}", idx=i, height=1400) for i in range(3)]
    blocks = [_b(1, "0000", 0, "Page-header", "Таблица IV.16", (800, 20, 1000, 60)),
              _b(2, "0001", 0, "Text", "Глава 4. Формовка", (100, 20, 600, 60)),
              _b(3, "0002", 0, "Page-header", "202 ЛИТЕЙНЫЕ МАШИНЫ", (100, 20, 900, 60))]
    info = analyze_headers(pages, blocks)
    assert info.recategorize == {1: "Caption"} and info.drop == {3}
    assert info.printed == {"0000": None, "0001": None, "0002": None}  # a lone number is not confirmed


def test_consistent_numbers_rejects_outliers_and_fills_gaps():
    order = [f"p{i}" for i in range(6)]
    assert consistent_numbers(order, {"p0": 10, "p1": 11, "p2": 99, "p3": 13, "p5": 15}) == {
        "p0": "10", "p1": "11", "p2": "12", "p3": "13", "p4": "14", "p5": "15"}


def test_consistent_numbers_duplicate_in_separate_chains():
    """If same number appears in separate consistent chains, keep only longest."""
    order = [f"p{i}" for i in range(6)]
    # Two chains: p0-p1-p2 gives 1,2,3 and p3-p4-p5 gives 1,2,3
    result = consistent_numbers(order, {"p0": 1, "p1": 2, "p2": 3, "p3": 1, "p4": 2, "p5": 3})
    # Both chains are same length, but we keep first occurrence; all values should be set
    assert result["p0"] is not None and result["p3"] is None
    assert result["p1"] is not None and result["p4"] is None


def test_short_generic_text_kept_real_header_dropped():
    """Short generic text like "a)" should be kept; real running headers should be dropped."""
    pages = [PageRow(name=f"{i:04d}", idx=i, height=1400) for i in range(5)]
    blocks = []
    # Add short generic text (Cyrillic "a)") at bottom of 5 pages - should be kept (sig len < 4)
    for i, p in enumerate(pages):
        blocks.append(_b(10*i + 1, p.name, 0, "Text", "а)", (100, 1350, 120, 1390)))  # short, at bottom
    # Add a real header ("Gas pores" in Russian) on some pages with varying page numbers
    blocks += [
        _b(51, "0000", 1, "Page-header", "Газовые раковины 61", (100, 20, 600, 60)),
        _b(52, "0001", 1, "Page-header", "Газовые раковины 63", (100, 20, 600, 60)),  # different number
        _b(53, "0002", 1, "Page-header", "Газовые раковины 63", (100, 20, 600, 60)),
    ]
    info = analyze_headers(pages, blocks)
    # Short "a)" should not be dropped (signature length < 4)
    assert 1 not in info.drop and 11 not in info.drop and 21 not in info.drop
    # Real headers should be dropped
    assert 51 in info.drop and 52 in info.drop and 53 in info.drop


def test_bare_page_number_preferred_over_edge_number():
    """Prefer bare page number (whole text is number) over edge numbers."""
    pages = [PageRow(name="0001", idx=0, height=1400), PageRow(name="0002", idx=1, height=1400)]
    blocks = [
        # Page 0001: bare "60" should be preferred over "4 Molding 60"
        _b(1, "0001", 0, "Text", "4 Формовка 60", (100, 200, 900, 400)),
        _b(2, "0001", 1, "Page-footer", "60", (450, 1350, 550, 1390)),
        # Page 0002: only has edge number
        _b(3, "0002", 0, "Page-footer", "61", (450, 1350, 550, 1390)),
    ]
    info = analyze_headers(pages, blocks)
    # Bare 60 should be selected for page 0001
    assert info.printed["0001"] == "60"
    assert info.printed["0002"] == "61"
