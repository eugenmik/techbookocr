import shutil
import subprocess

import pytest
from PIL import Image

from techbookocr.config import RenderConfig
from techbookocr.eval.golden import candidate_name, extract_golden, golden_pairs, load_manifest, write_review_html


def _manifest(tmp_path):
    m = tmp_path / "manifest.toml"
    m.write_text(
        """
[[page]]
id = "saf-100L"
book = "Сафронов"
scan = 100
side = "L"
categories = ["table", "text"]

[[page]]
id = "vor-60"
book = "Воронин"
scan = 60
side = ""
categories = ["text", "list"]
""",
        encoding="utf-8",
    )
    return m


def test_load_manifest(tmp_path):
    pages = load_manifest(_manifest(tmp_path))
    assert [p.id for p in pages] == ["saf-100L", "vor-60"]
    assert pages[0].categories == ("table", "text") and pages[0].lang == "ru"


def test_golden_pairs_only_complete(tmp_path):
    _manifest(tmp_path)
    Image.new("RGB", (5, 5)).save(tmp_path / "saf-100L.png")
    (tmp_path / "saf-100L.md").write_text("x", encoding="utf-8")
    Image.new("RGB", (5, 5)).save(tmp_path / "vor-60.png")
    pairs = golden_pairs(tmp_path)
    assert [p.id for p, _, _ in pairs] == ["saf-100L"]


def test_review_html(tmp_path):
    _manifest(tmp_path)
    Image.new("RGB", (5, 5)).save(tmp_path / "saf-100L.png")
    (tmp_path / "saf-100L.md").write_text("| a |\n\n$$x^2$$", encoding="utf-8")
    html = write_review_html(tmp_path).read_text(encoding="utf-8")
    assert "saf-100L.png" in html and "katex" in html and "x^2" in html


@pytest.mark.books
def test_extract_real_pages(tmp_path, books_dir):
    out = tmp_path / "g"
    files = extract_golden(_manifest(tmp_path), books_dir, out, RenderConfig(deskew=False))
    assert [f.name for f in files] == ["saf-100L.png", "vor-60.png"]
    assert Image.open(out / "saf-100L.png").size[0] < 2000  # left half of the spread


def test_candidate_name():
    from pathlib import Path
    assert candidate_name(Path("/books/Сафронов.djvu"), 123) == "Сафронов_djvu_0123.jpg"
    assert candidate_name(Path("/books/Гиршович_Том 2.pdf"), 0) == "Гиршович_Том 2_pdf_0000.jpg"


def test_load_manifest_duplicate_ids(tmp_path):
    m = tmp_path / "manifest.toml"
    m.write_text(
        """
[[page]]
id = "dup-100"
book = "Сафронов"
scan = 100
side = "L"

[[page]]
id = "dup-100"
book = "Воронин"
scan = 60
side = ""
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate page ids"):
        load_manifest(m)


def test_review_html_escapes_script_tag(tmp_path):
    m = tmp_path / "manifest.toml"
    m.write_text(
        """
[[page]]
id = "test-1"
book = "Тест"
scan = 1
side = ""
categories = ["text"]
""",
        encoding="utf-8",
    )
    Image.new("RGB", (5, 5)).save(tmp_path / "test-1.png")
    # Markdown content with </script> that would break page if not escaped
    (tmp_path / "test-1.md").write_text("Some text </script> and more", encoding="utf-8")
    html = write_review_html(tmp_path).read_text(encoding="utf-8")
    # The </script> in markdown should be escaped to <\/script> in JSON to prevent breaking the page
    # Extract the pages JSON object
    script_section = html.split('const pages=')[1].split(';')[0]
    # Should have escaped version
    assert "<\\/script>" in script_section


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_render_md_escapes_math_with_node(tmp_path):
    """Test the renderMd JavaScript function with node.js to verify math escaping."""
    # Extract the renderMd and esc functions from the review template
    from techbookocr.eval.golden import _REVIEW

    # Extract the functions from _REVIEW template
    script_start = _REVIEW.find("function esc(s)")
    script_end = _REVIEW.find("const pages={data};")
    functions_js = _REVIEW[script_start:script_end].strip()

    # Create a test script
    test_js = functions_js + """
// Test 1: math with display $$ should be preserved with escaping
const result1 = renderMd('$$x^2$$');
if (result1.includes('$$x^2$$')) {
  console.log('PASS: display math preserved');
} else {
  console.log('FAIL: display math not found in', result1);
  process.exit(1);
}

// Test 2: inline math with < should be escaped
const result2 = renderMd('$a<b$');
if (result2.includes('$a&lt;b$')) {
  console.log('PASS: inline math escaped');
} else {
  console.log('FAIL: inline math not escaped', result2);
  process.exit(1);
}

// Test 3: mixed math and text
const result3 = renderMd('Text $$x^2$$ and $a<b$ end');
if (result3.includes('$$x^2$$') && result3.includes('$a&lt;b$')) {
  console.log('PASS: mixed math escaped');
} else {
  console.log('FAIL: mixed math failed', result3);
  process.exit(1);
}
"""

    script_file = tmp_path / "test_render_md.js"
    script_file.write_text(test_js, encoding="utf-8")

    # Run with node
    result = subprocess.run(
        ["node", str(script_file)],
        capture_output=True,
        text=True,
        timeout=5
    )

    assert result.returncode == 0, f"node test failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "PASS: display math preserved" in result.stdout
    assert "PASS: inline math escaped" in result.stdout
    assert "PASS: mixed math escaped" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_tilde_not_strikethrough_and_figure_overlay(tmp_path):
    from techbookocr.eval.golden import _REVIEW

    script_start = _REVIEW.find("function esc(s)")
    script_end = _REVIEW.find("const pages={data};")
    functions_js = _REVIEW[script_start:script_end].strip()
    test_js = """
// stub marked: GFM-like strikethrough on ~x~ / ~~x~~, passes entities through
globalThis.marked = {parse: s => s.replace(/~{1,2}([^~]+)~{1,2}/g, '<del>$1</del>')};
""" + functions_js + """
const r = renderMd('(~2,2 г/см³) и (~7,8 г/см³)');
if (r.includes('<del>') || !r.includes('&#126;2,2')) { console.log('FAIL', r); process.exit(1); }
const r2 = renderMd('`a~b` и ~c');
if (!r2.includes('`a~b`') || !r2.includes('&#126;c')) { console.log('FAIL2', r2); process.exit(1); }
console.log('PASS: tilde');
"""
    f = tmp_path / "t.js"
    f.write_text(test_js, encoding="utf-8")
    res = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=5)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS: tilde" in res.stdout

    g = tmp_path / "g"
    g.mkdir()
    (g / "manifest.toml").write_text('[[page]]\nid="p1"\nbook="b"\nscan=1\ncategories=["text"]\n', encoding="utf-8")
    (g / "p1.md").write_text("x\n", encoding="utf-8")
    (g / "p1.png").write_bytes(b"")
    (g / "p1.figures.json").write_text('{"figures": [[1, 2, 30, 40]]}', encoding="utf-8")
    page = write_review_html(g).read_text(encoding="utf-8")
    assert '"p1": [[1, 2, 30, 40]]' in page and 'id="figs-p1"' in page
