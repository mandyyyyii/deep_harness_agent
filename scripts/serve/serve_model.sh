#!/usr/bin/env bash
# Launch SGLang server for a given model.
#
# Usage: bash serve_model.sh <model_path_or_hf_id> <port> [tp_size]
#
# Examples:
#   bash serve_model.sh Qwen/Qwen3.5-35B-A3B 8051
#   bash serve_model.sh Qwen/Qwen3.5-397B-A17B 8051 8
#   bash serve_model.sh THUDM/GLM-4.7-Flash 8060 1
set -euo pipefail

MODEL="${1:?Usage: $0 <model_path_or_hf_id> <port> [tp_size]}"
PORT="${2:?Usage: $0 <model_path_or_hf_id> <port> [tp_size]}"
TP="${3:-1}"

# Derive a short served-model-name from the model path
MODEL_NAME=$(basename "$MODEL" | sed 's|/|_|g')
HOST_IP=$(hostname -I | awk '{print $1}')

# Model-specific flags
EXTRA_ARGS=()

case "$MODEL" in
  *Qwen3.5*|*qwen3.5*|*Qwen3-*)
    # Qwen 3.x family: enable reasoning parser + tool call parser
    EXTRA_ARGS+=(
      --context-length 262144
      --reasoning-parser qwen3
      --tool-call-parser qwen3_coder
    )
    ;;
  *GLM*|*glm*)
    # GLM family: standard tool calling, shorter context
    EXTRA_ARGS+=(
      --context-length 131072
    )
    ;;
  *)
    # Default: conservative context length
    EXTRA_ARGS+=(
      --context-length 131072
    )
    ;;
esac

echo "Starting SGLang server:"
echo "  Model:   $MODEL"
echo "  Name:    $MODEL_NAME"
echo "  Port:    $PORT"
echo "  TP:      $TP"
echo "  URL:     http://$HOST_IP:$PORT/v1"
echo "  Extra:   ${EXTRA_ARGS[*]}"
echo ""

exec python -m sglang.launch_server \
  --model-path "$MODEL" \
  --served-model-name "$MODEL_NAME" \
  --host 0.0.0.0 \
  --port "$PORT" \
  --tp-size "$TP" \
  --mem-fraction-static 0.9 \
  "${EXTRA_ARGS[@]}"
