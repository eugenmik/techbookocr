from techbookocr.pipeline.assemble import render_book
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.run import PostResult
from techbookocr.pipeline.postproc.spell import SpellStats
from techbookocr.pipeline.quality import quality_stats, render_quality
from techbookocr.pipeline.state import BlockRow, PageRow


def test_quality_report():
    pages = [PageRow(name="0001", idx=0, printed="12"),
             PageRow(name="0002", idx=1, layout_status="failed", layout_error="looping")]
    blocks = [
        BlockRow(id=1, page="0001", ord=0, category="Text", kind="text", decision="accept"),
        BlockRow(id=2, page="0001", ord=1, category="Table", kind="table", decision="arbiter",
                 arbiter_status="rejected", arbiter_note="cer 0.312 > 0.15", final_source="fallback_a",
                 sketches=[{"path": "x", "bbox": [0, 0, 1, 1]}]),
        BlockRow(id=3, page="0001", ord=2, category="Text", kind="text", decision="arbiter", arbiter_status="done",
                 fixes=[{"was": "обоим", "now": "обеим"}]),
        BlockRow(id=4, page="0002", ord=0, category="Page", kind="page", decision="arbiter", arbiter_status="failed",
                 arbiter_error="looping", final_source="fallback_b", drafts_status="failed", b_error="truncated"),
        BlockRow(id=5, page="0001", ord=3, category="Picture"),
        BlockRow(id=6, page="0001", ord=4, category="Table", kind="table", decision="arbiter", arbiter_status="done",
                 arbiter_note="unverified: низкое качество"),
        BlockRow(id=7, page="0002", ord=1, category="Text", kind="text", decision="arbiter", arbiter_status="done",
                 arbiter_note="kept: fallback_a"),
    ]
    spell = SpellStats(checked=200, unknown=5, top=[("чгун", 3, ["0001"])])
    stats = quality_stats(pages, blocks, spell)
    assert stats["draftable"] == 6 and stats["arbitrated"] == 5 and round(stats["arbitration_share"], 2) == 0.83
    assert stats["arbiter_rejected"] == 1 and stats["arbiter_failed"] == 1 and stats["misprint_fixes"] == 1
    assert stats["layout_failed"] == 1 and stats["sketches"] == 1 and stats["spell_unknown"] == 5
    assert stats["unverified"] == 1 and stats["kept"] == 1 and stats["fixes_unparsable"] == 0
    md = render_quality("Книга", pages, blocks, stats, spell,
                        ["0001, block 1: 2 sketches, 1 <img> slots: sketches placed after the table"], {"layout": 20.0})
    assert md.startswith("# Recognition quality: Книга\n")
    assert "| Arbitrated share | 83.3% (5 of 6) |" in md
    assert "- 0002: looping" in md
    assert "- 0001 (p. 12), block 1 (table): rejected, cer 0.312 > 0.15 → fallback_a" in md
    assert "- 0002, block 0 (page): failed, looping → fallback_b" in md
    assert "- 0002, block 0 (Page): draft B: truncated" in md
    assert "| 0001 (p. 12) | обоим | обеим |" in md
    assert "| чгун | 3 | 0001 |" in md and "| Out-of-dictionary words | 2.5% (5 of 200) |" in md
    assert "| layout | 20 | 10.0 |" in md
    assert "- 0001, block 1: 2 sketches, 1 <img> slots: sketches placed after the table" in md
    assert "## Needs manual review" in md
    assert "0001 (p. 12), block 4 (table): unverified: низкое качество" in md
    assert "0002, block 1 (text): kept: fallback_a" in md


def test_quality_extraction_report():
    """Text-layer book: extract statistics and the lists of pending model work."""
    pages = [PageRow(name="0001", idx=0, layout_status="done", printed="5"),
             PageRow(name="0002", idx=1, layout_status="pending"),   # vision: waits for --models
             PageRow(name="0003", idx=2, layout_status="done")]
    blocks = [
        BlockRow(id=1, page="0001", ord=0, category="Text", kind="text", origin="layer",
                 final="txt", final_source="layer"),
        BlockRow(id=2, page="0001", ord=1, category="Table", kind="table", origin="layer",
                 decision="arbiter", arbiter_status="pending"),
        BlockRow(id=3, page="0003", ord=0, category="Text", kind="text", origin="layer",
                 final="txt", final_source="layer"),
        BlockRow(id=4, page="0002", ord=0, category="Text", kind="text", origin="dots"),
    ]
    stats = quality_stats(pages, blocks, None)
    assert stats["layer_pages"] == 2 and stats["vision_pending"] == 1
    assert stats["tables_pending"] == 1
    md = render_quality("Книга", pages, blocks, stats, None, [], {})
    assert "## Text-layer extraction" in md
    assert "0002" in md.split("Pages awaiting OCR")[1].split("\n")[1]  # page is in the waiting list
    assert "0001 (p. 5), block 1" in md                                # the table awaits the arbiter


def test_book_meta_extraction():
    from techbookocr.pipeline.assemble import book_meta
    meta = book_meta("Книга", "src.pdf", [PageRow(name="0001", idx=0)], {"0001": "1"}, "en",
                     "cascade", {"layout": "dots"}, {}, extraction={"layer_pages": 9, "tables": 2})
    assert meta["extraction"]["layer_pages"] == 9
    assert "extraction" in meta


def test_stitch_with_footnotes():
    """Defs of a page whose last paragraph is stitched stay in that page, before the paragraph."""
    pages = [PageRow(name="0001", idx=0), PageRow(name="0002", idx=1)]
    items = [
        Item(1, "0001", 0, "Text", "Первый абзац*."),
        Item(2, "0001", 1, "Footnote", "* Сноска."),
        Item(3, "0001", 2, "Text", "Второй абзац продолжается"),
        Item(4, "0002", 0, "Text", "на следующей странице.", join_to=3),
    ]
    md, _ = render_book(PostResult(items=items, printed={}, spell=None), pages)
    assert "[^1]: Сноска.\n\nВторой абзац продолжается <!-- page: ? scan: 0002 --> на следующей странице." in md


def test_quality_lists_spans_and_suspects():
    pages = [PageRow(name="0018R", idx=0, printed="39"), PageRow(name="0021L", idx=1)]
    md = render_quality("Книга", pages, [], quality_stats(pages, [], None), None, [], {},
                        spans={"0018R:3": ['row "высота": 500 — one value spanning 2 columns']},
                        suspects=[("0021L", 3, 'row "Развес литья, кг": 2 dashes next to value "10—500"')])
    assert "## Merged cells" in md and '0018R (p. 39), block 3: row "высота"' in md
    assert "2 dashes" in md and "0021L, block 3" in md


def test_quality_fixes_unparsable_block():
    pages = [PageRow(name="0001", idx=0)]
    blocks = [BlockRow(id=1, page="0001", ord=2, category="Text", kind="text", decision="arbiter",
                       arbiter_status="done", arbiter_note="fixes unparsable: bad json")]
    stats = quality_stats(pages, blocks, None)
    assert stats["fixes_unparsable"] == 1 and stats["unverified"] == 0 and stats["kept"] == 0
    md = render_quality("Книга", pages, blocks, stats, None, [], {})
    assert "## Needs manual review\n\n- 0001, block 2 (text): fixes unparsable: bad json\n" in md
