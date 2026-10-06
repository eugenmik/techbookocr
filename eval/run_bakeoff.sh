#!/usr/bin/env bash
# Stage 0 bake-off driver: download weights in parallel (with retries), run each model's eval as soon as its weights are present.
set -u
cd "$(dirname "$0")/.."
LOG=eval/logs; mkdir -p "$LOG" "$HOME/.cache/huggingface/gguf"
export HF_HUB_DISABLE_XET=1
HF="uvx --from huggingface_hub hf"

download() {  # key repo [extra hf args...]
  local key=$1 repo=$2; shift 2
  local extra=("$@")
  for attempt in 1 2 3 4 5 6 7 8; do
    if $HF download "$repo" "${extra[@]}" >>"$LOG/dl_$key.log" 2>&1; then
      touch "$LOG/dl_$key.done"; return 0
    fi
    echo "retry $attempt" >>"$LOG/dl_$key.log"; sleep 30
  done
  touch "$LOG/dl_$key.failed"
}

# order = eval priority
MODELS=(${BAKEOFF_MODELS:-dots_mocr chandra2 paddle_vl hunyuan qwen9b_page})
declare -A REPO=(
  [dots_mocr]=dots-studio/dots.mocr [chandra2]=dangvansam/chandra-ocr-2-FP8-dynamic
  [paddle_vl]=PaddlePaddle/PaddleOCR-VL-1.6 [hunyuan]=tencent/HunyuanOCR
  [qwen9b_page]=unsloth/Qwen3.5-9B-GGUF [dots_ocr]=dots-studio/dots.ocr [deepseek2]=deepseek-ai/DeepSeek-OCR-2)

for k in "${MODELS[@]}"; do
  rm -f "$LOG/dl_$k.done" "$LOG/dl_$k.failed"
  if [ "$k" = qwen9b_page ]; then
    download "$k" "${REPO[$k]}" Qwen3.5-9B-Q5_K_M.gguf mmproj-F16.gguf --local-dir "$HOME/.cache/huggingface/gguf" &
  elif [ "$k" = hunyuan ]; then
    download "$k" "${REPO[$k]}" --exclude "v1.0/*" &
  else
    download "$k" "${REPO[$k]}" &
  fi
done

docker pull ghcr.io/ggml-org/llama.cpp:server-cuda >"$LOG/pull_llamacpp.log" 2>&1 &

for k in "${MODELS[@]}"; do
  until [ -e "$LOG/dl_$k.done" ] || [ -e "$LOG/dl_$k.failed" ]; do sleep 20; done
  if [ -e "$LOG/dl_$k.failed" ]; then echo "$(date +%T) $k: download failed" >>"$LOG/bakeoff.log"; continue; fi
  echo "$(date +%T) $k: eval start" >>"$LOG/bakeoff.log"
  uv run techbookocr eval --models "$k" >"$LOG/eval_$k.log" 2>&1
  echo "$(date +%T) $k: eval exit $?" >>"$LOG/bakeoff.log"
done
wait
uv run techbookocr eval-report >>"$LOG/bakeoff.log" 2>&1
echo "$(date +%T) ALL DONE" >>"$LOG/bakeoff.log"
