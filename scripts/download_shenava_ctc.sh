#!/usr/bin/env bash
# Download the preferred Persian ASR model (Shenava Koochik CTC / sherpa-onnx).
# Usage:
#   ./scripts/download_shenava_ctc.sh [/path/to/models]
set -euo pipefail

MODELS_ROOT="${1:-${MODELS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/models}}"
TARGET="$MODELS_ROOT/shenava-koochik-ctc"
BASE_URL="${SHENAVA_CTC_URL:-https://huggingface.co/PersianML/Shenava-Koochik-v1.0-sherpa-onnx/resolve/main}"

mkdir -p "$TARGET"
cd "$TARGET"

echo "Downloading Shenava Koochik CTC into $TARGET ..."
for file in model.onnx tokens.txt persian_itn.py; do
  if [[ -f "$file" ]]; then
    echo "  skip existing $file"
    continue
  fi
  echo "  fetching $file"
  curl -fL --retry 4 --retry-delay 4 -o "$file" "$BASE_URL/$file"
done

if [[ ! -f model.onnx || ! -f tokens.txt ]]; then
  echo "Download incomplete: need model.onnx and tokens.txt" >&2
  exit 1
fi

ls -lh model.onnx tokens.txt
echo "Ready. Set MODELS_DIR=$MODELS_ROOT and POST /api/boot"
