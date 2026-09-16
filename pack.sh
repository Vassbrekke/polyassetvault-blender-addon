#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/polyassetvault-blender.zip"
rm -f "$OUT"
(
  cd "$ROOT"
  zip -r "$OUT" polyassetvault \
    -x '*/__pycache__/*' \
    -x '*.pyc' \
    -x '*/.*'
)
echo "$OUT"
