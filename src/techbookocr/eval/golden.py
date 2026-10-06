"""Gold page set: manifest, image extraction, review sheet."""
from __future__ import annotations

import html
import json
import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from techbookocr.config import RenderConfig
from techbookocr.ingest.pipeline import ingest_page
from techbookocr.ingest.source import open_book


@dataclass(frozen=True)
class GoldenPage:
    id: str
    book: str
    scan: int
    side: str
    categories: tuple[str, ...]
    lang: str = "ru"


def load_manifest(path: Path) -> list[GoldenPage]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    pages = [GoldenPage(id=p["id"], book=p["book"], scan=int(p["scan"]), side=p.get("side", ""),
                        categories=tuple(p.get("categories", ())), lang=p.get("lang", "ru"))
             for p in raw.get("page", [])]
    # Detect duplicate ids
    ids = [p.id for p in pages]
    if len(ids) != len(set(ids)):
        dupes = [id_ for id_ in set(ids) if ids.count(id_) > 1]
        raise ValueError(f"duplicate page ids in manifest: {dupes}")
    return pages


def candidate_name(book: Path, scan: int) -> str:
    """Generate unique candidate filename from book path and scan number."""
    return f"{book.stem}{book.suffix.replace('.', '_')}_{scan:04d}.jpg"


def _find_book(books_dir: Path, prefix: str) -> Path:
    hits = sorted(p for p in books_dir.iterdir() if p.name.startswith(prefix) and p.suffix.lower() in (".djvu", ".pdf"))
    if not hits:
        raise FileNotFoundError(f"no book starting with {prefix!r} in {books_dir}")
    return hits[0]


def extract_golden(manifest: Path, books_dir: Path, out_dir: Path, cfg: RenderConfig) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for gp in load_manifest(manifest):
        target = out_dir / f"{gp.id}.png"
        if not target.exists():
            with tempfile.TemporaryDirectory() as tmp, open_book(_find_book(books_dir, gp.book)) as src:
                refs = ingest_page(src, gp.scan, Path(tmp), cfg)
                match = [r for r in refs if r.side == gp.side]
                if not match:
                    raise ValueError(f"{gp.id}: side {gp.side!r} not produced (got {[r.side for r in refs]})")
                # Atomic write: write to .png.tmp then os.replace
                tmp_target = target.with_suffix(".png.tmp")
                shutil.copy(Path(tmp) / match[0].file, tmp_target)
                os.replace(tmp_target, target)
        files.append(target)
    return files


def golden_pairs(golden_dir: Path) -> list[tuple[GoldenPage, Path, Path]]:
    out = []
    for gp in load_manifest(golden_dir / "manifest.toml"):
        png, md = golden_dir / f"{gp.id}.png", golden_dir / f"{gp.id}.md"
        if png.exists() and md.exists():
            out.append((gp, png, md))
    return out


_REVIEW = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Gold set: review</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@14/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<style>body{{font-family:sans-serif;margin:0}}section{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;border-bottom:4px solid #888}}
img{{width:100%}}.pg{{position:relative}}.fig{{position:absolute;border:2px solid #e00;background:rgba(255,0,0,.2);pointer-events:none}}table{{border-collapse:collapse}}td,th{{border:1px solid #999;padding:2px 6px}}h2{{grid-column:1/3;margin:0}}pre{{white-space:pre-wrap;word-wrap:break-word}}</style>
</head><body>{sections}
<script>
function esc(s){{return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function escTilde(s){{
  return s.split(/(```[\s\S]*?```|`[^`\n]*`)/).map((p,i)=>i%2?p:p.replace(/~/g,'&#126;')).join('');
}}
function renderMd(md){{
  const mathRegex = /(\$\$[^$]+\$\$|\$[^$]+\$)/g;
  const math = [];let html = md;
  const matches = md.matchAll(mathRegex);
  for(const m of matches){{math.push(m[0]);}}
  for(let i=0;i<math.length;i++){{html=html.replace(math[i],'@@MATH'+i+'@@');}}
  if(typeof marked !== 'undefined'){{html = marked.parse(escTilde(html));}}else{{html = '<pre>'+esc(html)+'</pre>';}}
  for(let i=0;i<math.length;i++){{html=html.replace('@@MATH'+i+'@@',()=>esc(math[i]));}}
  return html;
}}
function drawFigures(id){{
  const boxes=figures[id]; if(!boxes||!boxes.length) return;
  const img=document.getElementById('img-'+id), layer=document.getElementById('figs-'+id);
  const draw=()=>{{
    layer.innerHTML=''; const k=img.clientWidth/img.naturalWidth;
    for(const b of boxes){{
      const d=document.createElement('div'); d.className='fig';
      d.style.left=(b[0]*k)+'px'; d.style.top=(b[1]*k)+'px';
      d.style.width=((b[2]-b[0])*k)+'px'; d.style.height=((b[3]-b[1])*k)+'px';
      layer.appendChild(d);
    }}
  }};
  if(img.complete&&img.naturalWidth) draw(); else img.addEventListener('load',draw);
  window.addEventListener('resize',draw);
}}
const pages={data};
const figures={figures};
for(const [id,md] of Object.entries(pages)){{
  const el=document.getElementById('md-'+id);
  drawFigures(id);
  try{{
    el.innerHTML = renderMd(md);
    if(typeof renderMathInElement !== 'undefined'){{renderMathInElement(el,{{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}]}});}}
  }}catch(e){{el.innerHTML='<pre>Error: '+e.message+'</pre>';}}
}}
</script>
</body></html>"""


def write_review_html(golden_dir: Path) -> Path:
    sections, data, figures = [], {}, {}
    for gp in load_manifest(golden_dir / "manifest.toml"):
        md = golden_dir / f"{gp.id}.md"
        if not md.exists():
            continue
        data[gp.id] = md.read_text(encoding="utf-8")
        fj = golden_dir / f"{gp.id}.figures.json"
        if fj.exists():
            figures[gp.id] = json.loads(fj.read_text(encoding="utf-8")).get("figures", [])
        gp_id_escaped = html.escape(gp.id, quote=True)
        categories_escaped = html.escape(", ".join(gp.categories), quote=True)
        sections.append(f'<section><h2>{gp_id_escaped} — {categories_escaped}</h2>'
                        f'<div class="pg"><img src="{gp_id_escaped}.png" id="img-{gp_id_escaped}">'
                        f'<div class="figs" id="figs-{gp_id_escaped}"></div></div><div id="md-{gp_id_escaped}"></div></section>')
    out = golden_dir / "review.html"
    out.write_text(_REVIEW.format(sections="\n".join(sections),
                                  data=json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
                                  figures=json.dumps(figures)), encoding="utf-8")
    return out
