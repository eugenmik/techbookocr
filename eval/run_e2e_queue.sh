#!/usr/bin/env bash
# Task 12 queue: each book in variant 1 (fast, local qwen9b arbiter), then variant 2 = copy + --redo arbiter
# on the remote qwen3.8-27B UD (thinking off). Timing per run in eval/logs/e2e-*.log.
set -u
cd "$(dirname "$0")/.."
run() {  # name book out config [extra...]
  local name=$1 book=$2 out=$3 cfg=$4; shift 4
  local s=$SECONDS
  uv run techbookocr run "$book" --mode fast --out "$out" --config "$cfg" "$@" > "eval/logs/e2e-$name.log" 2>&1
  echo "exit $? elapsed $((SECONDS - s)) s" >> "eval/logs/e2e-$name.log"
  echo "$(date '+%F %T') $name: $(tail -1 eval/logs/e2e-$name.log)" >> eval/logs/e2e-queue.log
}
deskew_figs() {  # figures from the layout stage cropped before deskewing existed (idempotent)
  uv run python -c "
import sys, glob
from PIL import Image
from techbookocr.pipeline.crops import deskew_photo, save_image
for f in glob.glob(sys.argv[1] + '/images/*_fig*.png'):
    im = Image.open(f); im.load(); out = deskew_photo(im)
    if out is not im: save_image(out, f)
" "$1" 2>/dev/null
}
# book paths come from the environment; set them to your own test books
SPECS=("book1|${E2E_BOOK1:-test_books/book1.djvu}|"
       "book2|${E2E_BOOK2:-test_books/book2.djvu}|")
for spec in "${SPECS[@]}"; do
  IFS='|' read -r name book extra <<< "$spec"; stem=$(basename "${book%.*}")
  # arguments are the names of books to run (all by default)
  if [ $# -gt 0 ] && ! printf '%s\n' "$@" | grep -qx "$name"; then continue; fi
  run "$name-v1" "$book" out/v1-fast-9b techbookocr.toml $extra
  grep -q "^exit 0" "eval/logs/e2e-$name-v1.log" || continue
  deskew_figs "out/v1-fast-9b/$stem"
  rm -rf "out/v2-fast-qwen38/$stem"; mkdir -p out/v2-fast-qwen38
  cp -a "out/v1-fast-9b/$stem" "out/v2-fast-qwen38/$stem"
  run "$name-v2" "$book" out/v2-fast-qwen38 eval/techbookocr-v2-qwen38.toml --redo arbiter
done
echo "$(date '+%F %T') queue done" >> eval/logs/e2e-queue.log
