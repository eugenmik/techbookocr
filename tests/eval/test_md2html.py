import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(folder: Path) -> str:
    # markdown is not a project dependency: the script runs via uv run --with markdown (package is cached)
    subprocess.run(["uv", "run", "--with", "markdown", "python", "eval/md2html.py", str(folder)],
                   check=True, cwd=ROOT, capture_output=True)
    return (folder / "book.html").read_text(encoding="utf-8")


def test_md2html_strips_frontmatter(tmp_path):
    (tmp_path / "book.md").write_text("---\ntitle: x\n---\n\n# Текст\n", encoding="utf-8")
    html = _run(tmp_path)
    assert "title: x" not in html and "Текст" in html


def test_md2html_no_frontmatter_unchanged(tmp_path):
    (tmp_path / "book.md").write_text("# Без шапки\n", encoding="utf-8")
    assert "Без шапки" in _run(tmp_path)
