"""book.md → book.html alongside it (for viewing in a browser): uv run --with markdown python eval/md2html.py <book folder>..."""
import pathlib
import sys

import markdown

CSS = ("body{max-width:1000px;margin:auto;font-family:sans-serif;line-height:1.5}table{border-collapse:collapse}"
       "td,th{border:1px solid #999;padding:4px;vertical-align:top}img{max-width:100%}")
for d in map(pathlib.Path, sys.argv[1:]):
    text = d.joinpath("book.md").read_text()
    if text.startswith("---\n"):
        # look for the closing --- only in the first 50 lines: beyond that it is book text, not the header
        head = "".join(text.splitlines(keepends=True)[:50])
        end = head.find("\n---", 3)
        text = text[end + 4:] if end != -1 else text
    body = markdown.markdown(text, extensions=["tables", "footnotes"])
    d.joinpath("book.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>{d.name}</title><style>{CSS}</style>"
        "<script>window.MathJax={tex:{inlineMath:[['$','$']]}}</script>"
        f"<script src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js'></script>{body}")
    print(d / "book.html")
