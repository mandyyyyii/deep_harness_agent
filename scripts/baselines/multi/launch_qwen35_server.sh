#!/usr/bin/env bash
# Launch one Qwen3.5-35B-A3B sglang server: the shared meta-harness endpoint
# referenced by run_all_baselines_parallel.sh (default port 8051).
#
# Qwen3.5-35B-A3B is a MoE VLM (~67 GB bf16, arch Qwen3_5MoeForConditionalGeneration,
# model_type qwen3_5_moe, hybrid linear-attention + full-attention). Confirmed
# supported by sglang 0.5.10 via sglang/srt/models/qwen3_5.py. The text-only
# inference path is used by the meta-harness proposer.
#
# Usage:
#   bash launch_qwen35_server.sh [port] [gpus] [tp_size]
#
# Defaults:
#   port    = 8051
#   gpus    = 6,7    (last two GPUs; matches run_all_baselines_parallel.sh layout)
#   tp_size = 2      (matches number of gpus by default)
#
# Parser flags:
#   --tool-call-parser qwen3_coder   # <tool_call><function=...><parameter=...> format
#   --reasoning-parser qwen3         # <think>...</think> tags
#
# Logs go to logs/qwen35_server.log; PID written to qwen35_server.pid.
#
# To wait for readiness:
#   until curl -sf http://127.0.0.1:8051/v1/models >/dev/null; do sleep 5; done
#
# To stop:
#   xargs -a qwen35_server.pid -r kill -9
set -euo pipefail

PORT="${1:-8051}"
GPUS="${2:-6,7}"
TP_SIZE="${3:-$(awk -F, '{print NF}' <<<"$GPUS")}"

SGLANG_PY="/xuanwu-tank/north/xw27/envs/sglang_env/bin/python"
HF_HOME="${HF_HOME:-/xuanwu-tank/north/xw27/cache}"
MODEL="Qwen/Qwen3.5-35B-A3B"
SERVED_NAME="qwen3.5-35b-a3b"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/qwen35_server.pid"
mkdir -p "$LOG_DIR"
: > "$PID_FILE"

LOG="$LOG_DIR/qwen35_server.log"

echo "================================================================"
echo "Launching Qwen3.5-35B-A3B sglang server"
echo "Model:       $MODEL"
echo "Served as:   $SERVED_NAME"
echo "HF_HOME:     $HF_HOME"
echo "Port:        $PORT"
echo "GPUs:        $GPUS  (tp_size=$TP_SIZE)"
echo "Log:         $LOG"
echo "PID file:    $PID_FILE"
echo "================================================================"

HF_HOME="$HF_HOME" CUDA_VISIBLE_DEVICES="$GPUS" nohup \
  "$SGLANG_PY" -m sglang.launch_server \
    --model-path "$MODEL" \
    --served-model-name "$SERVED_NAME" \
    --host 0.0.0.0 --port "$PORT" \
    --tp-size "$TP_SIZE" \
    --mem-fraction-static 0.85 \
    --context-length 131072 \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --trust-remote-code \
    > "$LOG" 2>&1 &
echo $! >> "$PID_FILE"

echo ""
echo "Qwen3.5-35B-A3B server launched in the background."
echo "PID: $(tr '\n' ' ' < "$PID_FILE")"
