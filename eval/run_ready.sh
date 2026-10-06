#!/usr/bin/env bash
# Eval scheduler: run `techbookocr eval` for each model as soon as its weights are downloaded (dl_<key>.done), one at a time.
set -u
cd "$(dirname "$0")/.."
LOG=eval/logs
PENDING=(${BAKEOFF_MODELS:-dots_mocr chandra2 paddle_vl hunyuan qwen9b_page})
while [ ${#PENDING[@]} -gt 0 ]; do
  next=()
  ran=0
  for k in "${PENDING[@]}"; do
    if [ $ran -eq 0 ] && [ -e "$LOG/dl_$k.done" ]; then
      echo "$(date +%T) $k: eval start" >>"$LOG/bakeoff.log"
      uv run techbookocr eval --models "$k" >"$LOG/eval_$k.log" 2>&1
      echo "$(date +%T) $k: eval exit $?" >>"$LOG/bakeoff.log"
      ran=1
    elif [ -e "$LOG/dl_$k.failed" ]; then
      echo "$(date +%T) $k: download failed" >>"$LOG/bakeoff.log"
    else
      next+=("$k")
    fi
  done
  PENDING=("${next[@]}")
  [ $ran -eq 0 ] && sleep 30
done
uv run techbookocr eval-report >>"$LOG/bakeoff.log" 2>&1
echo "$(date +%T) ALL DONE" >>"$LOG/bakeoff.log"
