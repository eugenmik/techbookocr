"""Misprint fix journal (techbookocr.fixes): parsing quality.md, locating in book.md, toggling."""
import json

import pytest

# Fragments of real reports: Cantor (current format), Girshovich (old **reverted** mark),
# Safronov (Russian headings).
CANTOR_Q = """# Recognition quality: cantor

| Metric | Value |
|---|---|
| Misprint fixes | 2 |
| Out-of-dictionary words | 6.2% (5557 of 89171) |

## Failed blocks

- none

## Misprint and print-defect fixes

| Page | Was | Now |
|---|---|---|
| 0007 | London & Scandinavian Metallurgical | London &amp; Scandinavian Metallurgical |
| 0046 (p. 34) | Specific load (t/mm) | Specific load (t mm) |

## Merged cells

- none
"""
GIR_ROWS = """## Misprint and print-defect fixes

| Page | Was | Now |
|---|---|---|
| 0121R (p. 243) | 10% Mo | 10% Мо |
| 0151R (p. 303) | 2б | ~~26~~ **reverted** |
| 0215L (p. 430) | ≥150 | ~~>150~~ reverted: changes operator |
"""
SAF_Q = """| Исправления опечаток | 94 |

## Исправления опечаток и дефектов печати

| Страница | Было | Стало |
|---|---|---|
| 0075R (с. 153) | Каток — 2 шт. | Кагок — 2 шт. |
| 0106R (с. 215) | 2 500 |  |
"""


def test_parse_current_format():
    from techbookocr.fixes.journal import parse_quality_fixes
    fx = parse_quality_fixes(CANTOR_Q)
    assert [(f.id, f.scan, f.page, f.was, f.now, f.state, f.decided_by) for f in fx] == [
        ("0007-1", "0007", None, "London & Scandinavian Metallurgical", "London &amp; Scandinavian Metallurgical",
         "applied", "model"),
        ("0046-1", "0046", "34", "Specific load (t/mm)", "Specific load (t mm)", "applied", "model")]


def test_parse_old_formats_and_russian_heading():
    from techbookocr.fixes.journal import parse_quality_fixes
    g = parse_quality_fixes(GIR_ROWS)
    assert [(f.id, f.state, f.reason, f.decided_by, f.now) for f in g] == [
        ("0121R-1", "applied", None, "model", "10% Мо"),
        ("0151R-1", "reverted", None, "rule", "26"),
        ("0215L-1", "reverted", "changes operator", "rule", ">150")]
    s = parse_quality_fixes(SAF_Q)
    assert [(f.scan, f.page, f.was, f.now) for f in s] == [("0075R", "153", "Каток — 2 шт.", "Кагок — 2 шт."),
                                                            ("0106R", "215", "2 500", "")]


def test_pipe_in_cell_roundtrip():
    """A cell with "|" (escaped as "\\|") and HTML: parsing and regeneration keep the text."""
    from techbookocr.fixes.journal import Journal, parse_quality_fixes, render_fixes_section
    q = ("## Misprint and print-defect fixes\n\n| Page | Was | Now |\n|---|---|---|\n"
         "| 0010 | <td>a\\|b</td> | <td>a\\|c</td> |\n| 0011 | 5.0<sub>2</sub> | 5.0<sub>3</sub> |\n")
    fx = parse_quality_fixes(q)
    assert fx[0].was == "<td>a|b</td>" and fx[0].now == "<td>a|c</td>" and fx[1].was == "5.0<sub>2</sub>"
    assert render_fixes_section(q, Journal(fx)) == q


def test_render_section_states_and_summary_only_touch_fix_section():
    from techbookocr.fixes.journal import Journal, parse_quality_fixes, render_fixes_section
    fx = parse_quality_fixes(CANTOR_Q)
    fx[1].state, fx[1].reason, fx[1].decided_by = "reverted", "rejected by user", "user"
    fx[0].suggested, fx[0].reason = True, "replaces dictionary word"
    out = render_fixes_section(CANTOR_Q, Journal(fx))
    assert "| 0007 | London & Scandinavian Metallurgical | London &amp; Scandinavian Metallurgical " \
           "(review: replaces dictionary word) |" in out
    assert "| 0046 (p. 34) | Specific load (t/mm) | ~~Specific load (t mm)~~ reverted: rejected by user |" in out
    assert "| Misprint fixes | 1 (reverted: 1) |" in out
    assert out.split("## Merged cells")[1] == CANTOR_Q.split("## Merged cells")[1]
    assert out.split("## Misprint")[0].replace("| Misprint fixes | 1 (reverted: 1) |", "| Misprint fixes | 2 |") \
        == CANTOR_Q.split("## Misprint")[0]
    nf = Journal([fx[0]]); fx[0].state, fx[0].suggested = "not_found", False
    assert "(not found in book.md)" in render_fixes_section(CANTOR_Q, nf)


def test_journal_roundtrip_counts_and_broken(tmp_path):
    from techbookocr.fixes.journal import Journal, JournalError, parse_quality_fixes, read_journal, save_journal
    p = tmp_path / "fixes.json"
    assert read_journal(p) is None
    j = Journal(parse_quality_fixes(GIR_ROWS))
    j.fixes[0].suggested = True
    save_journal(p, j)
    back = read_journal(p)
    assert back == j and back.get("0215L-1").reason == "changes operator"
    assert back.counts() == {"applied": 0, "reverted": 2, "suggested": 1, "not_found": 0}
    with pytest.raises(KeyError):
        back.get("nope")
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(JournalError):
        read_journal(p)
    p.write_text(json.dumps({"version": 1, "fixes": [{"id": 1}]}), encoding="utf-8")
    with pytest.raises(JournalError):
        read_journal(p)


BOOK = """---
title: cantor
---
<!-- page: 33 scan: 0045 -->

Rolls are cooled.

<!-- page: 34 scan: 0046 -->

<table><thead><tr><td>Cast gauge (mm)</td><td>Roll speed (m/min)</td><td>Specific load (t mm)</td></tr></thead></table>

The load continues
<!-- page: 35 scan: 0047 -->

on the next page: 10% Mo and 5% Mo here.
"""


def _book(tmp_path, md=BOOK, quality=CANTOR_Q):
    d = tmp_path / "lib" / "cantor"
    d.mkdir(parents=True)
    (d / "book.md").write_text(md, encoding="utf-8")
    (d / "quality.md").write_text(quality, encoding="utf-8")
    return d


def _fix(**kw):
    from techbookocr.fixes.journal import Fix
    base = dict(id="0046-1", scan="0046", page="34", block=None, kind=None, was="Specific load (t/mm)",
                now="Specific load (t mm)", state="applied")
    return Fix(**{**base, **kw})


def test_find_in_page_section_and_context():
    from techbookocr.fixes.locate import context, find
    f = _fix()
    a, b = find(BOOK, f, f.now)
    assert BOOK[a:b] == "Specific load (t mm)"
    before, after = context(BOOK, a, b)
    assert before.endswith("<td>Roll speed (m/min)</td><td>") and after.startswith("</td></tr></thead>")
    assert find(BOOK, _fix(scan="0047"), "Specific load (t mm)") is None     # wrong page (and there is no next one)


def test_find_in_next_section():
    """A paragraph is joined across pages: the fix from scan 0046 stands in section 0047."""
    from techbookocr.fixes.locate import find
    f = _fix(was="on the nxt page", now="on the next page")
    a, b = find(BOOK, f, f.now)
    assert BOOK[a:b] == "on the next page"


def test_ambiguous_without_context_is_not_found():
    from techbookocr.fixes.locate import find
    f = _fix(scan="0047", was="Mo", now="Мо")
    assert find(BOOK, f, "Mo") is None                                    # two "Mo" on the page
    f.before, f.after = "and 5% ", " here"
    a, b = find(BOOK, f, "Mo")
    assert BOOK[a - 7:b + 5] == "and 5% Mo here"


def test_token_boundaries():
    from techbookocr.fixes.locate import find
    md = "<!-- page: 1 scan: 0001 -->\n\n<td>0.1009</td><td>.1089</td>\n"
    f = _fix(scan="0001", was="0.1009", now=".1089")
    a, b = find(md, f, ".1089")
    assert md[a - 9:b] == "</td><td>.1089" and md[a - 1] == ">"


def test_set_fix_roundtrip_is_byte_identical(tmp_path):
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.locate import context, find
    from techbookocr.fixes.review import set_fix
    d = _book(tmp_path)
    f = _fix()
    a, b = find(BOOK, f, f.now)
    f.before, f.after = context(BOOK, a, b)
    save_journal(d / "fixes.json", Journal([f]))
    root = d.parent
    j = set_fix(d, "0046-1", False, library_root=root)
    md = (d / "book.md").read_text(encoding="utf-8")
    assert "Specific load (t/mm)" in md and "Specific load (t mm)" not in md
    g = j.get("0046-1")
    assert (g.state, g.decided_by, g.reason, g.suggested) == ("reverted", "user", "rejected by user", False)
    assert read_journal(d / "fixes.json").get("0046-1").state == "reverted"
    assert "~~Specific load (t mm)~~ reverted: rejected by user" in (d / "quality.md").read_text(encoding="utf-8")
    rej = json.loads((root / "rejected-fixes.json").read_text(encoding="utf-8"))
    assert rej["pairs"] == [{"was": "Specific load (t/mm)", "now": "Specific load (t mm)", "books": ["cantor"]}]
    set_fix(d, "0046-1", True, library_root=root)
    assert (d / "book.md").read_text(encoding="utf-8") == BOOK
    assert json.loads((root / "rejected-fixes.json").read_text(encoding="utf-8"))["pairs"] == []


def test_keep_fix_clears_suggestion_only(tmp_path):
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import keep_fix
    d = _book(tmp_path)
    save_journal(d / "fixes.json", Journal([_fix(suggested=True, reason="replaces dictionary word")]))
    keep_fix(d, "0046-1", library_root=d.parent)
    g = read_journal(d / "fixes.json").get("0046-1")
    assert (g.state, g.suggested, g.decided_by, g.reason) == ("applied", False, "user", "replaces dictionary word")
    assert (d / "book.md").read_text(encoding="utf-8") == BOOK
    assert not (d.parent / "rejected-fixes.json").exists()


def test_heal_after_crash_between_book_and_journal(tmp_path):
    """The book is already reverted, the journal still says applied (the process died between writes): state is healed from the text."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import heal
    d = _book(tmp_path, md=BOOK.replace("Specific load (t mm)", "Specific load (t/mm)"))
    save_journal(d / "fixes.json", Journal([_fix()]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True and j.get("0046-1").state == "reverted"
    assert read_journal(d / "fixes.json").get("0046-1").state == "reverted"


def test_manual_edit_marks_not_found(tmp_path):
    """The user rewrote the cell in Obsidian: neither "was" nor "now" is there, so not_found and toggling refuses."""
    from techbookocr.fixes.journal import Journal, save_journal
    from techbookocr.fixes.review import FixError, set_fix
    md = BOOK.replace("Specific load (t mm)", "Specific load, t per mm")
    d = _book(tmp_path, md=md)
    save_journal(d / "fixes.json", Journal([_fix()]))
    with pytest.raises(FixError, match="not found"):
        set_fix(d, "0046-1", False, library_root=d.parent)
    assert (d / "book.md").read_text(encoding="utf-8") == md


def test_rejected_list_books_and_broken_file(tmp_path):
    from techbookocr.fixes.rejected import add_rejection, denied_pairs, remove_rejection
    root = tmp_path
    add_rejection(root, "Каток", "Кагок", "saf")
    add_rejection(root, "Каток", "Кагок", "gir")
    add_rejection(root, "Каток", "Кагок", "saf")                       # a repeat does not duplicate the book
    assert denied_pairs(root) == frozenset({("Каток", "Кагок")})
    remove_rejection(root, "Каток", "Кагок", "saf")
    assert denied_pairs(root) == frozenset({("Каток", "Кагок")})
    remove_rejection(root, "Каток", "Кагок", "gir")
    assert denied_pairs(root) == frozenset()
    (root / "rejected-fixes.json").write_text("{oops", encoding="utf-8")
    msgs = []
    assert denied_pairs(root, msgs.append) == frozenset() and "rejected-fixes.json" in msgs[0]
    add_rejection(root, "a", "b", "x")                                  # the broken file is kept aside and recreated
    assert denied_pairs(root) == frozenset({("a", "b")})
    assert list(root.glob("rejected-fixes.json.broken-*"))


def test_write_atomic_keeps_file_mode(tmp_path):
    """mkstemp creates the file with 0600: rewriting book.md must not change an existing file's permissions."""
    import os
    import stat
    from techbookocr.fixes.journal import write_atomic
    p = tmp_path / "book.md"
    p.write_text("old", encoding="utf-8")
    p.chmod(0o644)
    write_atomic(p, "new")
    assert p.read_text(encoding="utf-8") == "new" and stat.S_IMODE(p.stat().st_mode) == 0o644
    q = tmp_path / "fresh.json"
    write_atomic(q, "x")                                                # a new file follows the umask, not 0600
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(q.stat().st_mode) == 0o666 & ~umask


def test_not_editable_while_processing(tmp_path):
    from techbookocr.fixes.journal import Journal, save_journal
    from techbookocr.fixes.review import FixError, check_editable, set_fix
    from techbookocr.library import Library
    d = _book(tmp_path)
    save_journal(d / "fixes.json", Journal([_fix()]))
    root = d.parent
    assert check_editable(d, root) is None                              # the book is not in the queue, so it is free
    (root / "cantor.djvu").touch()
    with Library(root) as lib:
        lib.add([root / "cantor.djvu"])
        lib.set_status("cantor", "processing")
    assert check_editable(d, root) == "book is processing"
    with pytest.raises(FixError, match="processing"):
        set_fix(d, "0046-1", False, library_root=root)


# --- review round 1 ------------------------------------------------------------------------------

AMBIG = "<!-- page: 34 scan: 0046 -->\n\nsteel Mo, iron Mo; and unrelated word Мо in a quote.\n"


def test_heal_ambiguity_is_not_found_not_flip(tmp_path):
    """The "now" variant occurs twice (ambiguous), "was" once in an unrelated place: not_found, the text is left alone."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import FixError, heal, set_fix
    d = _book(tmp_path, md=AMBIG)
    save_journal(d / "fixes.json", Journal([_fix(was="Мо", now="Mo")]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True and j.get("0046-1").state == "not_found"
    with pytest.raises(FixError, match="not found"):
        set_fix(d, "0046-1", True, library_root=d.parent)
    assert (d / "book.md").read_text(encoding="utf-8") == AMBIG


def test_find_prefers_exact_context_in_next_section():
    """An exact "before + now + after" in the next section beats a single token on the fix's own page."""
    from techbookocr.fixes.locate import find
    md = ("<!-- page: 1 scan: 0046 -->\n\nКагок is a roller.\n\n"
          "<!-- page: 2 scan: 0047 -->\n\nThe big Кагок works.\n")
    f = _fix(was="Каток", now="Кагок", before="The big ", after=" works")
    a, b = find(md, f, "Кагок")
    assert md[a - 8:b + 6] == "The big Кагок works"


def test_context_does_not_cross_anchors():
    from techbookocr.fixes.locate import context
    md = "<!-- page: 34 scan: 0046 -->\n\nSome alloys of 5% Mo here.\n<!-- page: 35 scan: 0047 -->\n\nnext\n"
    a = md.index("Mo")
    before, _ = context(md, a, a + 2)
    assert a > 40 and before == "\n\nSome alloys of 5% "              # the 40-character window started inside the anchor
    md2 = "<!-- page: 1 scan: 0046 -->\n\nMo" + "x" * 37 + "\n<!-- page: 2 scan: 0047 -->\n"
    a2 = md2.index("Mo")
    assert context(md2, a2, a2 + 2)[1] == "x" * 37 + "\n"            # the right window ended on "<!"


def test_heal_refreshes_context_after_token_fallback(tmp_path):
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import heal
    d = _book(tmp_path)
    save_journal(d / "fixes.json", Journal([_fix(before="stale ", after=" stale")]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True and j.get("0046-1").state == "applied"
    g = read_journal(d / "fixes.json").get("0046-1")
    assert g.before.endswith("<td>Roll speed (m/min)</td><td>") and g.after.startswith("</td></tr></thead>")
    assert heal(d, read_journal(d / "fixes.json")) is False   # nothing changes on a repeat


def test_rejected_malformed_entries(tmp_path):
    from techbookocr.fixes.rejected import REJECTED, add_rejection, denied_pairs
    root = tmp_path
    for bad in ({"version": 1, "pairs": [5]},
                {"version": 1, "pairs": [{"was": "a", "now": "b"}]},
                {"version": 1, "pairs": [{"was": "a", "now": 1, "books": ["x"]}]},
                {"version": 1, "pairs": [{"was": "a", "now": "b", "books": "x"}]}):
        (root / REJECTED).write_text(json.dumps(bad), encoding="utf-8")
        msgs = []
        assert denied_pairs(root, msgs.append) == frozenset() and REJECTED in msgs[0]
        add_rejection(root, "c", "d", "book")                           # the broken file goes aside, the list is rebuilt
        assert denied_pairs(root) == frozenset({("c", "d")})
        (root / REJECTED).unlink()
    assert len(list(root.glob(f"{REJECTED}.broken-*"))) >= 1


# --- Ruling 7 --------------------------------------------------------------------------------------

def test_heal_flip_with_context_requires_exact_hit(tmp_path):
    """The fix has a context and the "other" variant is found only by token (the context did not match): not_found, no flip."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import heal
    d = _book(tmp_path, md=BOOK.replace("Specific load (t mm)", "Specific load (t/mm)"))
    save_journal(d / "fixes.json", Journal([_fix(before="stale ", after=" stale")]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True and j.get("0046-1").state == "not_found"


def test_heal_flip_with_context_exact_hit_still_flips(tmp_path):
    """A crash between writes left the context intact: an exact "before + was + after" heals the state."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import heal
    before, after = "<td>Roll speed (m/min)</td><td>", "</td></tr></thead>"
    d = _book(tmp_path, md=BOOK.replace("Specific load (t mm)", "Specific load (t/mm)"))
    save_journal(d / "fixes.json", Journal([_fix(before=before, after=after)]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True and j.get("0046-1").state == "reverted"


def test_token_does_not_match_inside_next_anchor():
    """The fix text equals the next page's number: it is not searched for inside the anchor."""
    from techbookocr.fixes.locate import find
    md = ("<!-- page: 34 scan: 0046 -->\n\nSome text.\n\n"
          "<!-- page: 35 scan: 0047 -->\n\nOther text.\n")
    assert find(md, _fix(was="38", now="35"), "35") is None


# --- Task 4: journal of an older book --------------------------------------------------------------

GIR_BOOK = """<!-- page: 243 scan: 0121R -->

Модификаторы: 10% Мо, 15% Ва.

<!-- page: 342 scan: 0171L -->

длина $t$ = 5 мм

<!-- page: 153 scan: 0075R -->

Кагок — 2 шт.
"""
GIR_Q = """| Misprint fixes | 3 |

## Misprint and print-defect fixes

| Page | Was | Now |
|---|---|---|
| 0121R (p. 243) | 10% Mo | 10% Мо |
| 0171L (p. 342) | l | t |
| 0075R (p. 153) | Каток — 2 шт. | Кагок — 2 шт. |
| 0121R (p. 243) | Пробсотборник | Пробсоброрник |
"""


class _Sp:
    def known(self, w):
        return w.lower() in {"каток", "шт"}


def test_legacy_journal_applies_variant_c(tmp_path):
    """Older book: unambiguous rules revert in book.md, the dictionary rule only sets "?", whatever is not found is not_found."""
    from techbookocr.fixes.journal import read_journal
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    langs = []
    j = load_journal(d, library_root=d.parent, speller_factory=lambda l: (langs.append(l), _Sp())[1])
    st = {f.id: (f.state, f.suggested, f.reason, f.decided_by) for f in j.fixes}
    assert st["0121R-1"] == ("reverted", False, "element to Cyrillic", "rule")
    assert st["0171L-1"] == ("reverted", False, "ambiguous single letter", "rule")
    assert st["0075R-1"] == ("applied", True, "replaces dictionary word", "model")
    assert st["0121R-2"][0] == "not_found"
    md = (d / "book.md").read_text(encoding="utf-8")
    assert "10% Mo, 15% Ва" in md and "$l$" in md and "Кагок — 2 шт." in md
    assert read_journal(d / "fixes.json") == j
    q = (d / "quality.md").read_text(encoding="utf-8")
    assert "(review: replaces dictionary word)" in q and "~~10% Мо~~ reverted: element to Cyrillic" in q
    assert langs == [["ru", "en"]]                                    # language from meta.json, ru by default


def test_legacy_journal_uses_rejected_pairs_and_works_without_speller(tmp_path):
    from techbookocr.fixes.rejected import add_rejection
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    add_rejection(d.parent, "Каток — 2 шт.", "Кагок — 2 шт.", "other-book")
    j = load_journal(d, library_root=d.parent)
    f = j.get("0075R-1")
    assert (f.state, f.reason, f.suggested) == ("reverted", "rejected by user", False)
    assert "Каток — 2 шт." in (d / "book.md").read_text(encoding="utf-8")


def test_broken_journal_is_kept_and_rebuilt(tmp_path):
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path)
    (d / "fixes.json").write_text("{oops", encoding="utf-8")
    j = load_journal(d, library_root=d.parent)
    assert [f.id for f in j.fixes] == ["0007-1", "0046-1"] and list(d.glob("fixes.json.broken-*"))


def test_peek_does_not_write_and_summary(tmp_path):
    from techbookocr.fixes.review import load_journal, peek_journal, summary
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    assert peek_journal(d).fixes and not (d / "fixes.json").exists()
    assert summary(d) == {"total": 4, "suggested": None, "reviewed": False}
    load_journal(d, library_root=d.parent, speller_factory=lambda l: _Sp())
    assert summary(d) == {"total": 4, "suggested": 1, "reviewed": False}
    assert summary(tmp_path / "nope") == {"total": 0, "suggested": None, "reviewed": False}


# --- Task 4, review round 1 (Ruling 8) -------------------------------------------------------------

def test_heal_exact_other_beats_token_current(tmp_path):
    """The token of the "current" variant hit an unrelated Cyrillic "Mo", the "other" one is found exactly by context: a flip, not a rebind."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import heal
    md = "<!-- page: 34 scan: 0046 -->\n\nСплав 10% Mo. Марка Мо и другие.\n"
    d = _book(tmp_path, md=md)
    save_journal(d / "fixes.json", Journal([_fix(was="Mo", now="Мо", before="Сплав 10% ", after=". Марка")]))
    j = read_journal(d / "fixes.json")
    assert heal(d, j) is True
    f = j.get("0046-1")
    assert f.state == "reverted" and f.before.endswith("Сплав 10% ") and f.after.startswith(". Марка")


def test_legacy_speller_failure_keeps_rules(tmp_path):
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    msgs = []

    def boom(langs):
        raise OSError("offline")
    j = load_journal(d, library_root=d.parent, speller_factory=boom, log=msgs.append)
    assert j.get("0121R-1").state == "reverted" and j.get("0075R-1").suggested is False
    assert any("offline" in m for m in msgs)


@pytest.mark.parametrize("data", [
    {"fixes": [1]},
    {"fixes": [{"id": "a-1", "scan": "a", "page": None, "block": None, "kind": None, "was": "x", "now": "y",
                "state": "applied", "before": None}]},
    {"fixes": [{"id": "a-1", "scan": 5, "page": None, "block": None, "kind": None, "was": "x", "now": "y",
                "state": "applied"}]},
    {"fixes": [{"id": "a-1", "scan": "a", "page": None, "block": None, "kind": None, "was": "x", "now": "y",
                "state": "applied", "after": 3}]},
])
def test_malformed_valid_json_is_broken(tmp_path, data):
    from techbookocr.fixes.journal import JournalError, read_journal
    from techbookocr.fixes.review import load_journal, peek_journal, summary
    d = _book(tmp_path)
    (d / "fixes.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(JournalError):
        read_journal(d / "fixes.json")
    assert [f.id for f in peek_journal(d).fixes] == ["0007-1", "0046-1"]
    assert summary(d) == {"total": 2, "suggested": None, "reviewed": False}
    j = load_journal(d, library_root=d.parent)
    assert [f.id for f in j.fixes] == ["0007-1", "0046-1"] and list(d.glob("fixes.json.broken-*"))


def test_legacy_crash_window_state_by_text(tmp_path):
    """Older book, quality.md says applied but the text already has "was": state follows the text."""
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=BOOK.replace("Specific load (t mm)", "Specific load (t/mm)"))
    j = load_journal(d, library_root=d.parent)
    assert j.get("0046-1").state == "reverted" and j.get("0007-1").state == "not_found"


def test_rebuild_after_broken_journal_does_not_apply_rules(tmp_path):
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    (d / "fixes.json").write_text("{oops", encoding="utf-8")
    j = load_journal(d, library_root=d.parent, speller_factory=lambda l: _Sp())
    assert j.get("0121R-1").state == "applied" and j.get("0171L-1").state == "applied"
    assert j.get("0075R-1").suggested is False
    assert (d / "book.md").read_text(encoding="utf-8") == GIR_BOOK


def test_legacy_next_section_hit_is_not_auto_reverted(tmp_path):
    from techbookocr.fixes.review import load_journal
    md = ("<!-- page: 243 scan: 0121R -->\n\nДругой текст.\n\n"
          "<!-- page: 244 scan: 0122L -->\n\nМодификаторы: 10% Мо, 15% Ва.\n")
    d = _book(tmp_path, md=md, quality=GIR_Q)
    j = load_journal(d, library_root=d.parent)
    f = j.get("0121R-1")
    assert f.state == "applied" and f.before.endswith("Модификаторы: ") and f.after.startswith(", 15%")
    assert (d / "book.md").read_text(encoding="utf-8") == md


def test_legacy_revert_clears_suggested(tmp_path):
    from techbookocr.fixes.review import load_journal
    q = GIR_Q.replace("| 10% Мо |", "| 10% Мо (review: replaces dictionary word) |")
    d = _book(tmp_path, md=GIR_BOOK, quality=q)
    f = load_journal(d, library_root=d.parent).get("0121R-1")
    assert (f.state, f.suggested, f.decided_by) == ("reverted", False, "rule")


# --- Task 4, review round 2 ------------------------------------------------------------------------

def test_legacy_flipped_by_text_skips_rules(tmp_path):
    """A "reverted" record, "was" is not found in the text, "now" is found by token elsewhere: state follows the text,
    no rules are applied, the book does not change."""
    from techbookocr.fixes.review import load_journal
    md = ("<!-- page: 243 scan: 0121R -->\n\nСплав: 10%Mo (марка А). Другой сплав: 10% Мо, 15% Ва.\n")
    q = GIR_Q.replace("| 10% Mo | 10% Мо |", "| 10% Mo | ~~10% Мо~~ reverted |")
    d = _book(tmp_path, md=md, quality=q)
    f = load_journal(d, library_root=d.parent).get("0121R-1")
    assert f.state == "applied" and f.reason != "element to Cyrillic"
    assert (d / "book.md").read_bytes() == md.encode("utf-8")


def test_legacy_not_found_clears_suggested(tmp_path):
    from techbookocr.fixes.review import load_journal
    q = GIR_Q.replace("| Пробсоброрник |", "| Пробсоброрник (review: replaces dictionary word) |")
    d = _book(tmp_path, md=GIR_BOOK, quality=q)
    f = load_journal(d, library_root=d.parent).get("0121R-2")
    assert (f.state, f.suggested) == ("not_found", False)


def test_journal_from_blocks_reads_state_of_text(tmp_path):
    from types import SimpleNamespace as NS

    from techbookocr.fixes.journal import read_journal
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    blocks = [NS(page="0046", ord=3, kind="table", fixes=[
                 {"was": "Specific load (t/mm)", "now": "Specific load (t mm)"},
                 {"was": "Rol speed", "now": "Roll speed", "rejected": "replaces dictionary word"}]),
              NS(page="0047", ord=0, kind="text", fixes=[{"was": "absent", "now": "nowhere"}])]
    pages = [NS(name="0046", printed="34"), NS(name="0047", printed="35")]
    j = journal_from_blocks(d, blocks, pages)
    st = {f.id: (f.state, f.block, f.kind, f.decided_by, f.page) for f in j.fixes}
    assert st == {"0046-1": ("applied", 3, "table", "model", "34"),
                  "0046-2": ("applied", 3, "table", "rule", "34"),      # the revert failed: the book has "now"
                  "0047-1": ("not_found", 0, "text", "model", "35")}
    assert j.get("0046-1").before.endswith("<td>") and read_journal(d / "fixes.json") == j


def test_journal_from_blocks_decided_by_user_for_user_rejection(tmp_path):
    from types import SimpleNamespace as NS

    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    blocks = [NS(page="0046", ord=3, kind="table", fixes=[
        {"was": "Specific load (t/mm)", "now": "Specific load (t mm)", "rejected": "rejected by user"},
        {"was": "Rol speed", "now": "Roll speed", "rejected": "replaces dictionary word"}])]
    j = journal_from_blocks(d, blocks, [NS(name="0046", printed="34")])
    assert [f.decided_by for f in j.fixes] == ["user", "rule"]


# --- Final branch review ---------------------------------------------------------------------------

TABLE_13 = ("<!-- page: 34 scan: 0046 -->\n\n<table><tr><td>A</td><td>1/3</td></tr><tr><td>B</td><td>1/3</td></tr>"
            "<tr><td>C</td><td>1/8</td></tr></table>\n\n<!-- page: 35 scan: 0047 -->\n\nNext page.\n")


def test_journal_from_blocks_ambiguous_expected_is_not_found_not_flip(tmp_path):
    """A rejected 1/3 -> 1/8: "was" 1/3 occurs twice (ambiguous), a genuine 1/8 once. Flipping to 1/8 is wrong:
    Space would turn the genuine 1/8 into 1/3. An ambiguity gives not_found, the book does not change."""
    from types import SimpleNamespace as NS

    from techbookocr.fixes.review import FixError, journal_from_blocks, load_journal, set_fix
    d = _book(tmp_path, md=TABLE_13, quality="# Q\n\n## Misprint and print-defect fixes\n\n- none\n")
    blocks = [NS(page="0046", ord=1, kind="table", fixes=[{"was": "1/3", "now": "1/8", "rejected": "changes digits"}])]
    j = journal_from_blocks(d, blocks, [NS(name="0046", printed="34")])
    assert j.fixes[0].state == "not_found"
    assert load_journal(d, library_root=d.parent).fixes[0].state == "not_found"
    with pytest.raises(FixError):
        set_fix(d, "0046-1", False, library_root=d.parent)
    assert (d / "book.md").read_text(encoding="utf-8") == TABLE_13


MILL = ("<!-- page: 34 scan: 0046 -->\n\nThe roll speed was measured in a mill with rolls.\n\n"
        "<!-- page: 35 scan: 0047 -->\n\nNext page.\n")


@pytest.mark.parametrize("raw", [{"was": "mill", "now": "", "rejected": "deletes text"},
                                 {"was": "mill", "now": ""},
                                 {"was": "", "now": "mill"},
                                 {"was": "", "now": "mill", "rejected": "inserts text"}])
def test_journal_from_blocks_empty_side_is_not_found(tmp_path, raw):
    from types import SimpleNamespace as NS

    from techbookocr.fixes.review import FixError, journal_from_blocks, set_fix
    d = _book(tmp_path, md=MILL)
    j = journal_from_blocks(d, [NS(page="0046", ord=1, kind="text", fixes=[raw])], [NS(name="0046", printed="34")])
    assert (j.fixes[0].state, j.fixes[0].before, j.fixes[0].after) == ("not_found", "", "")
    for applied in (True, False):
        with pytest.raises(FixError):
            set_fix(d, "0046-1", applied, library_root=d.parent)
    assert (d / "book.md").read_text(encoding="utf-8") == MILL


@pytest.mark.parametrize("row", ["| 0046 (p. 34) | mill | ~~~~ reverted: deletes text |",
                                 "| 0046 (p. 34) | mill |  |",
                                 "| 0046 (p. 34) |  | mill |"])
def test_legacy_empty_side_is_not_found(tmp_path, row):
    from techbookocr.fixes.review import load_journal
    q = ("# Q\n\n## Misprint and print-defect fixes\n\n| Page | Was | Now |\n|---|---|---|\n"
         f"{row}\n\n## Merged cells\n\n- none\n")
    d = _book(tmp_path, md=MILL, quality=q)
    j = load_journal(d, library_root=d.parent)
    assert [f.state for f in j.fixes] == ["not_found"]
    assert (d / "book.md").read_text(encoding="utf-8") == MILL


def test_set_fix_refuses_empty_side_even_if_journal_says_otherwise(tmp_path):
    """Second line of defence: a record with an empty side in fixes.json (an old build) cannot be toggled."""
    from techbookocr.fixes.journal import Journal, read_journal, save_journal
    from techbookocr.fixes.review import FixError, set_fix
    d = _book(tmp_path, md=MILL)
    save_journal(d / "fixes.json", Journal([_fix(was="mill", now="", state="reverted", before="measured in a ",
                                                 after=" with rolls.")]))
    with pytest.raises(FixError, match="inserts or deletes"):
        set_fix(d, "0046-1", True, library_root=d.parent)
    assert (d / "book.md").read_text(encoding="utf-8") == MILL
    assert read_journal(d / "fixes.json").get("0046-1").state == "not_found"      # heal dropped the record


def test_set_fix_passes_speller_to_first_journal_build(tmp_path):
    """The first set_fix/keep_fix call on an older book builds the journal with the dictionary, otherwise the "?" marks are lost for good."""
    from techbookocr.fixes.review import keep_fix, set_fix
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    j = set_fix(d, "0121R-1", True, library_root=d.parent, speller_factory=lambda l: _Sp(), dict_min_len=4)
    assert j.get("0075R-1").suggested is True
    d2 = _book(tmp_path / "x", md=GIR_BOOK, quality=GIR_Q)
    j = keep_fix(d2, "0121R-1", library_root=d2.parent, speller_factory=lambda l: _Sp())
    assert j.get("0075R-1").suggested is True


def test_legacy_user_rejection_is_decided_by_user(tmp_path):
    from techbookocr.fixes.rejected import add_rejection
    from techbookocr.fixes.review import load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    add_rejection(d.parent, "Каток — 2 шт.", "Кагок — 2 шт.", "other-book")
    f = load_journal(d, library_root=d.parent).get("0075R-1")
    assert (f.reason, f.decided_by) == ("rejected by user", "user")


def test_keep_fix_without_suggestion_is_noop(tmp_path):
    from techbookocr.fixes.review import keep_fix, load_journal
    d = _book(tmp_path, md=GIR_BOOK, quality=GIR_Q)
    load_journal(d, library_root=d.parent)
    paths = (d / "fixes.json", d / "quality.md", d / "book.md")
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    j = keep_fix(d, "0121R-1", library_root=d.parent)
    assert j.get("0121R-1").decided_by == "rule"
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before


@pytest.mark.parametrize("bad", ["quality", "journal", "journal_dir"])
def test_summary_tolerates_unreadable_files(tmp_path, bad):
    from techbookocr.fixes.review import summary
    d = _book(tmp_path)
    if bad == "quality":
        (d / "quality.md").write_bytes(b"## Misprint and print-defect fixes\n\xff\xfe\x00bad\n")
    elif bad == "journal":
        (d / "quality.md").write_bytes(b"\xff\xfe")
        (d / "fixes.json").write_bytes(b"\xff\xfe{")
    else:
        (d / "fixes.json").mkdir()
    assert summary(d) is None


# --- Scan crop of a fix (the v key on the Fixes screen) ---------------------------------------------

class _Pages:
    """Fake PageImages: get(name) -> page image; fail: pages on which get raises."""

    def __init__(self, size=(1000, 1400), fail=()):
        from PIL import Image
        self.img = Image.new("RGB", size, "white")
        self.fail, self.calls = set(fail), []

    def get(self, page):
        self.calls.append(page)
        if page in self.fail:
            raise OSError(f"cannot read {page}")
        return self.img


def _crop_blocks():
    from types import SimpleNamespace as NS
    return [NS(page="0046", ord=3, kind="table", bbox=(100, 220, 900, 400), fixes=[
                {"was": "Specific load (t/mm)", "now": "Specific load (t mm)"},
                {"was": "Rol speed", "now": "Roll speed", "rejected": "replaces dictionary word"}]),
            NS(page="0047", ord=0, kind="text", bbox=(100, 100, 900, 120), fixes=[]),
            NS(page="0047", ord=1, kind="text", bbox=(100, 200, 900, 220), fixes=[{"was": "10% Mо", "now": "10% Mo"}])]


def _crop_pages():
    from types import SimpleNamespace as NS
    return [NS(name="0046", printed="34"), NS(name="0047", printed="35")]


def test_journal_from_blocks_saves_block_crop_shared_by_block_fixes(tmp_path):
    """Crop of a block with fixes: fixes/<scan>-b<ord>.webp at the original resolution (bbox + crop_pad),
    one for all fixes of the block; a block without fixes is not cropped."""
    from PIL import Image

    from techbookocr.config import PipelineConfig
    from techbookocr.fixes.journal import read_journal
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    imgs = _Pages()
    j = journal_from_blocks(d, _crop_blocks(), _crop_pages(), images=imgs, cfg=PipelineConfig(crop_pad=12))
    assert [f.crop for f in j.fixes] == ["fixes/0046-b3.webp", "fixes/0046-b3.webp", "fixes/0047-b1.webp"]
    assert sorted(p.name for p in (d / "fixes").iterdir()) == ["0046-b3.webp", "0047-b1.webp"]
    with Image.open(d / "fixes" / "0046-b3.webp") as im:
        assert (im.format, im.size) == ("WEBP", (824, 204))          # no upscaling
    assert read_journal(d / "fixes.json").get("0046-1").crop == "fixes/0046-b3.webp"


def test_journal_from_blocks_page_block_crop_is_downscaled_page(tmp_path):
    """A whole-page block and a block without a box give the whole page, long side at most 1600 px."""
    from types import SimpleNamespace as NS

    from PIL import Image

    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    blocks = [NS(page="0046", ord=0, kind="page", bbox=(0, 0, 2000, 3000), fixes=[{"was": "Rol", "now": "Roll"}]),
              NS(page="0047", ord=2, kind="text", bbox=None, fixes=[{"was": "Mо", "now": "Mo"}])]
    j = journal_from_blocks(d, blocks, _crop_pages(), images=_Pages(size=(2000, 3000)))
    assert [f.crop for f in j.fixes] == ["fixes/0046-b0.webp", "fixes/0047-b2.webp"]
    for name in ("0046-b0.webp", "0047-b2.webp"):
        with Image.open(d / "fixes" / name) as im:
            assert im.size == (1067, 1600)


def test_journal_from_blocks_without_images_makes_no_crops(tmp_path):
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    (d / "fixes").mkdir()
    (d / "fixes" / "0001-b0.webp").write_bytes(b"old")                    # from a previous assembly
    j = journal_from_blocks(d, _crop_blocks(), _crop_pages())
    assert all(f.crop is None for f in j.fixes)
    assert not (d / "fixes").exists()


def test_journal_from_blocks_rebuild_removes_stale_crops(tmp_path):
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    (d / "fixes").mkdir()
    (d / "fixes" / "0001-b0.webp").write_bytes(b"old")
    journal_from_blocks(d, _crop_blocks(), _crop_pages(), images=_Pages())
    assert sorted(p.name for p in (d / "fixes").iterdir()) == ["0046-b3.webp", "0047-b1.webp"]


def test_journal_from_blocks_crop_failure_is_logged_not_fatal(tmp_path):
    """A failed crop of one block goes to the log, its fixes have no crop, the journal and other crops stay."""
    from techbookocr.fixes.journal import read_journal
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    lines: list[str] = []
    j = journal_from_blocks(d, _crop_blocks(), _crop_pages(), images=_Pages(fail={"0046"}), log=lines.append)
    assert [f.crop for f in j.fixes] == [None, None, "fixes/0047-b1.webp"]
    assert len(lines) == 1 and "0046" in lines[0] and "OSError" in lines[0]
    assert read_journal(d / "fixes.json") == j
    assert [p.name for p in (d / "fixes").iterdir()] == ["0047-b1.webp"]


def test_journal_from_blocks_all_crops_failed_leaves_no_dir(tmp_path):
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    j = journal_from_blocks(d, _crop_blocks(), _crop_pages(), images=_Pages(fail={"0046", "0047"}))
    assert all(f.crop is None for f in j.fixes)
    assert not (d / "fixes").exists()


def test_old_journal_without_crop_loads_and_crop_is_validated(tmp_path):
    from techbookocr.fixes.journal import Fix, JournalError, read_journal
    rec = _fix().to_dict()
    assert rec["crop"] is None
    del rec["crop"]
    p = tmp_path / "fixes.json"
    p.write_text(json.dumps({"version": 1, "fixes": [rec]}), encoding="utf-8")
    assert read_journal(p).fixes[0].crop is None
    assert Fix.from_dict({**rec, "crop": "fixes/0046-b3.webp"}).crop == "fixes/0046-b3.webp"
    with pytest.raises(JournalError):
        Fix.from_dict({**rec, "crop": 5})


def test_page_crop_limit_comes_from_config(tmp_path):
    """The long-side limit of a whole-page crop is [pipeline] fix_page_crop_max, not a constant in the code."""
    from types import SimpleNamespace as NS

    from PIL import Image

    from techbookocr.config import PipelineConfig
    from techbookocr.fixes.review import journal_from_blocks
    d = _book(tmp_path)
    blocks = [NS(page="0046", ord=0, kind="page", bbox=(0, 0, 2000, 3000), fixes=[{"was": "Rol", "now": "Roll"}])]
    journal_from_blocks(d, blocks, _crop_pages(), images=_Pages(size=(2000, 3000)),
                        cfg=PipelineConfig(fix_page_crop_max=800))
    with Image.open(d / "fixes" / "0046-b0.webp") as im:
        assert im.size == (533, 800)
