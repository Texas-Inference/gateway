#!/usr/bin/env bash
set -euo pipefail

# SGLang single-node launcher for self-hosted DeepSeek V4.1 (or V4-Flash / a tiny
# model for testing). One env-driven script works on RunPod, bare metal, the 8x
# B300 node, and Vast.ai.
#
# RUNTIME=docker (default): wraps the server in `docker run --gpus all`.
# RUNTIME=bare:             runs `python3 -m sglang.launch_server` directly
#                           (use on Vast.ai / any host where you're already
#                           inside the GPU container and can't nest Docker).
# PRINT_ONLY=1:             echoes the resolved command instead of running it.
#
# GPU-specific flags (parallelism, KV dtype, speculative decode) come from the
# SGLang cookbook recipe for your exact GPU; pass them via EXTRA_ARGS (see recipe.md).

MODEL_ID="${MODEL_ID:-deepseek-ai/DeepSeek-V4.1-Flash-1017}"
SERVED_NAME="${SERVED_NAME:-$MODEL_ID}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-30000}"
TP_SIZE="${TP_SIZE:-8}"
EP_SIZE="${EP_SIZE:-8}"
DP_SIZE="${DP_SIZE:-1}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-262144}" # 256K
MEM_FRACTION="${MEM_FRACTION:-0.92}"
CHUNKED_PREFILL="${CHUNKED_PREFILL:-16384}"
MAX_RUNNING="${MAX_RUNNING:-32}"
API_KEY="${API_KEY:?set API_KEY (SGLang auth key, used as the upstream key)}"
# V4.1 is NOT in an SGLang release yet -> use the preview image. For the tiny
# test (e.g. Qwen on a T4/3060) set IMAGE=lmsysorg/sglang:latest instead.
IMAGE="${IMAGE:-lmsysorg/sglang:dev-dsv41}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
SHM_SIZE="${SHM_SIZE:-32g}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
RUNTIME="${RUNTIME:-docker}"

SERVER=(python3 -m sglang.launch_server
  --model-path "$MODEL_ID"
  --served-model-name "$SERVED_NAME"
  --host "$HOST"
  --port "$PORT"
  --tp-size "$TP_SIZE"
  --ep-size "$EP_SIZE"
  --dp-size "$DP_SIZE"
  --context-length "$CONTEXT_LENGTH"
  --mem-fraction-static "$MEM_FRACTION"
  --chunked-prefill-size "$CHUNKED_PREFILL"
  --max-running-requests "$MAX_RUNNING"
  --api-key "$API_KEY")

# shellcheck disable=SC2206
[ -n "$EXTRA_ARGS" ] && SERVER+=($EXTRA_ARGS)

case "$RUNTIME" in
  docker)
    CMD=(docker run --gpus all --ipc=host --shm-size "$SHM_SIZE"
      -p "${PORT}:${PORT}"
      -v "${HF_CACHE}:/root/.cache/huggingface"
      -e "HF_TOKEN=${HF_TOKEN:-}"
      "$IMAGE"
      "${SERVER[@]}")
    ;;
  bare)
    # Already inside a GPU container (Vast.ai): run SGLang directly.
    export HF_HOME="${HF_HOME:-$HF_CACHE}"
    CMD=("${SERVER[@]}")
    ;;
  *)
    echo "RUNTIME must be 'docker' or 'bare' (got '$RUNTIME')" >&2
    exit 1
    ;;
esac

if [ "${PRINT_ONLY:-0}" = "1" ]; then
  printf '%q ' "${CMD[@]}"
  printf '\n'
  exit 0
fi

exec "${CMD[@]}"
