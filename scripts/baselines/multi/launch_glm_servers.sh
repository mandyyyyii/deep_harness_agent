#!/usr/bin/env bash
# Launch 8 GLM-4.7-Flash sglang servers, one per GPU (0..7), on consecutive ports.
#
# Usage:
#   bash launch_glm_servers.sh [base_port]
#
# Defaults:
#   base_port = 8060   -> GPU i serves on port (base_port + i), i.e. 8060..8067
#
# Each server is launched in the background with nohup. PIDs are written to
# glm_servers.pids next to this script; logs go to logs/glm_gpu${i}.log.
#
# To wait for readiness:
#   for p in $(seq 8060 8067); do
#     until curl -sf http://127.0.0.1:$p/v1/models >/dev/null; do sleep 5; done
#     echo "port $p ready"
#   done
#
# To stop all servers launched here:
#   xargs -a glm_servers.pids -r kill -9
set -euo pipefail

BASE_PORT="${1:-8060}"
NUM_GPUS=8

SGLANG_PY="/xuanwu-tank/north/xw27/envs/sglang_env/bin/python"
HF_HOME="${HF_HOME:-/xuanwu-tank/north/xw27/cache}"
MODEL="zai-org/GLM-4.7-Flash"
SERVED_NAME="GLM-4.7-Flash"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/glm_servers.pids"
mkdir -p "$LOG_DIR"
: > "$PID_FILE"

echo "================================================================"
echo "Launching ${NUM_GPUS} GLM-4.7-Flash servers"
echo "Model:     $MODEL"
echo "HF_HOME:   $HF_HOME"
echo "Ports:     ${BASE_PORT}..$((BASE_PORT + NUM_GPUS - 1))"
echo "Log dir:   $LOG_DIR"
echo "PID file:  $PID_FILE"
echo "================================================================"

for i in $(seq 0 $((NUM_GPUS - 1))); do
  PORT=$((BASE_PORT + i))
  LOG="$LOG_DIR/glm_gpu${i}.log"
  echo "  GPU ${i} -> port ${PORT}  (log: ${LOG})"
  HF_HOME="$HF_HOME" CUDA_VISIBLE_DEVICES=$i nohup \
    "$SGLANG_PY" -m sglang.launch_server \
      --model-path "$MODEL" \
      --served-model-name "$SERVED_NAME" \
      --host 0.0.0.0 --port "$PORT" \
      --tp-size 1 \
      --mem-fraction-static 0.85 \
      --context-length 131072 \
      --tool-call-parser glm47 \
      --reasoning-parser glm45 \
      --trust-remote-code \
      > "$LOG" 2>&1 &
  echo $! >> "$PID_FILE"
done

echo ""
echo "All ${NUM_GPUS} servers launched in the background."
echo "PIDs: $(tr '\n' ' ' < "$PID_FILE")"
