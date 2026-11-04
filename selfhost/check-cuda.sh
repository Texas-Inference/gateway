#!/usr/bin/env bash
set -euo pipefail

# Pre-flight gate for a freshly rented GPU box (Vast/RunPod/etc.).
# Verifies the NVIDIA driver's CUDA version and (optionally) that torch can see CUDA.
# The listing's "Max CUDA" is NOT trustworthy — always check here first.
#
#   ./check-cuda.sh              # require CUDA >= 13.0
#   MIN_CUDA=12.4 ./check-cuda.sh

MIN_CUDA="${MIN_CUDA:-13.0}"

command -v nvidia-smi >/dev/null 2>&1 || { echo "FAIL: nvidia-smi not found (no NVIDIA GPU/driver?)"; exit 1; }

cuda="$(nvidia-smi 2>/dev/null | grep -oE 'CUDA Version: [0-9]+\.[0-9]+' | head -1 | grep -oE '[0-9]+\.[0-9]+')"
echo "detected driver CUDA: ${cuda:-none}   required: >= ${MIN_CUDA}"
[ -n "$cuda" ] || { echo "FAIL: could not parse CUDA version"; exit 1; }

if ! python3 - "$cuda" "$MIN_CUDA" <<'PY'
import sys
got, need = float(sys.argv[1]), float(sys.argv[2])
sys.exit(0 if got >= need else 1)
PY
then
  echo "FAIL: driver CUDA ${cuda} < ${MIN_CUDA}. cu13 wheels will NOT run here."
  echo "      -> destroy this instance and rent one showing CUDA >= ${MIN_CUDA}."
  exit 1
fi

# If torch is installed, confirm it can actually reach the GPU.
if python3 -c "import torch" >/dev/null 2>&1; then
  if python3 -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"; then
    v="$(python3 -c 'import torch; print(torch.__version__, torch.version.cuda)')"
    echo "PASS: driver CUDA ${cuda} >= ${MIN_CUDA}; torch ${v}; cuda_available=True"
  else
    echo "FAIL: driver CUDA ${cuda} ok, but torch.cuda.is_available() is False (torch/CUDA mismatch)."
    exit 1
  fi
else
  echo "PASS: driver CUDA ${cuda} >= ${MIN_CUDA} (torch not installed yet)."
fi
