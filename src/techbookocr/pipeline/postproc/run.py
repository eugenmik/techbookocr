"""Book postprocessing: running heads → look-alikes → hyphenation → stitching → table continuations → spelling."""
from __future__ import annotations

from dataclasses import dataclass, field

from techbookocr.pipeline.postproc.floats import reorder_floats
from techbookocr.pipeline.postproc.headers import analyze_headers
from techbookocr.pipeline.postproc.homoglyphs import fix_homoglyphs_text
from techbookocr.pipeline.postproc.hyphenation import book_vocabulary, join_hyphens, make_is_word
from techbookocr.pipeline.postproc.items import Item
from techbookocr.pipeline.postproc.romans import fix_roman_refs
from techbookocr.pipeline.postproc.spell import SpellStats, spell_stats
from techbookocr.pipeline.postproc.stitch import mark_continuations, stitch_pages
from techbookocr.pipeline.postproc.tables import (merge_table_fragments, move_table_footnotes, promote_footnotes,
                                              span_by_geometry, span_single_value, suspect_invented_dashes)

PROSE = frozenset({"Text", "List-item", "Caption", "Footnote", "Page"})
_SPELL = PROSE | {"Title", "Section-header", "Table"}
_HEADERS = ("Page-header", "Page-footer")


@dataclass
class PostResult:
    items: list[Item]
    printed: dict[str, str | None]
    spell: SpellStats | None
    stitched: int = 0
    continued: int = 0
    spans: dict[str, list[str]] = field(default_factory=dict)          # "page:ord" → merged cells
    suspects: list[tuple[str, int, str]] = field(default_factory=list)  # (page, ord, description) for manual checking


def postprocess(pages, blocks, speller, cfg=None, images=None) -> PostResult:
    info = analyze_headers(pages, blocks)
    order = [p.name for p in sorted(pages, key=lambda p: p.idx)]
    pos = {n: i for i, n in enumerate(order)}
    items: list[Item] = []
    for b in sorted(blocks, key=lambda b: (pos[b.page], b.ord)):
        if b.parent is not None or b.id in info.drop:
            continue
        if b.category in _HEADERS and b.id not in info.recategorize:
            continue
        category = info.recategorize.get(b.id, b.category)
        text = b.final if b.final is not None else b.text_a
        if category not in ("Formula", "Picture"):
            text = fix_homoglyphs_text(text)
        items.append(Item(b.id, b.page, b.ord, category, text, b.image, list(b.sketches),
                          b.text_b if b.drafts_status == "done" else None, bbox=b.bbox))
    reorder_floats(items, {p.name: p.height for p in pages})
    move_table_footnotes(items)
    promote_footnotes(items)
    merge_table_fragments(items)
    if cfg is not None and cfg.span_single_value:
        span_single_value(items)
    if cfg is not None and images is not None and cfg.span_geometry:
        span_by_geometry(items, images, cfg)
    fix_roman_refs(items, order)
    vocab = book_vocabulary(it.text for it in items if it.category in PROSE)
    is_word = make_is_word(vocab, speller)
    for it in items:
        if it.category in PROSE:
            it.text = join_hyphens(it.text, is_word, vocab=vocab, speller=speller)
    stitched = stitch_pages(items, order, is_word)
    continued = mark_continuations(items)
    spell = (spell_stats(((it.page, it.text) for it in items if it.category in _SPELL), speller)
             if speller is not None else None)
    spans = {f"{it.page}:{it.ord}": list(it.spans) for it in items if it.spans}
    by_id = {it.id: it for it in items}
    suspects = [(by_id[i].page, by_id[i].ord, d) for i, d in suspect_invented_dashes(items)]
    return PostResult(items, info.printed, spell, stitched, continued, spans, suspects)
