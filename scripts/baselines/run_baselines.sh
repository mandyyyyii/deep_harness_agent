#!/usr/bin/env bash
# Run all 6 baseline agents on Terminal-Bench 2.0 and SWE-bench Verified.
#
# Usage:
#   bash run_baselines.sh <sglang_port> [model_name]
#
# Example:
#   bash run_baselines.sh 8051 qwen3.5-35b-a3b
#
# Agents: terminus-2, terminus-kira, mini-swe-agent, swe-agent, openhands, qwen-coder
# Benchmarks: terminal-bench@2.0 (89 tasks), swebench-verified (500 tasks)
set -euo pipefail

PORT="${1:?Usage: $0 <sglang_port> [model_name]}"
MODEL="${2:-qwen3.5-35b-a3b}"

HOST_IP=$(hostname -I | awk '{print $1}')
URL="http://$HOST_IP:$PORT/v1"
DOCKER_URL="http://172.17.0.1:$PORT/v1"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESULTS="$REPO_ROOT/results/baselines_${MODEL}"

export OPENAI_API_KEY=dummy
export OPENAI_BASE_URL="$URL"
export OPENAI_API_BASE="$URL"
export SGLANG_API_KEY=dummy
export SGLANG_BASE_URL="$URL"
export LLM_BASE_URL="$URL"

cd "$REPO_ROOT"
mkdir -p "$RESULTS"

TB_N=10    # concurrent trials for terminal-bench
SWE_N=4    # concurrent trials for swe-bench
TB_LIMIT=89
SWE_LIMIT=500

run_agent() {
  local AGENT="$1"
  local DATASET="$2"
  local OUTPUT="$3"
  local CONCURRENT="$4"
  local LIMIT="$5"
  shift 5
  local EXTRA_ARGS=("$@")

  echo ""
  echo "$(date) | Starting $AGENT on $DATASET (limit=$LIMIT, n=$CONCURRENT)..."
  docker network prune -f 2>/dev/null || true

  harbor run \
    -a "$AGENT" \
    -m "openai/$MODEL" \
    -d "$DATASET" \
    -o "$OUTPUT" \
    -n "$CONCURRENT" \
    -l "$LIMIT" \
    "${EXTRA_ARGS[@]}" \
    || echo "$(date) | $AGENT on $DATASET exited with error $?"

  echo "$(date) | $AGENT on $DATASET DONE"
}

run_custom_agent() {
  local IMPORT_PATH="$1"
  local DATASET="$2"
  local OUTPUT="$3"
  local CONCURRENT="$4"
  local LIMIT="$5"
  shift 5
  local EXTRA_ARGS=("$@")

  echo ""
  echo "$(date) | Starting $IMPORT_PATH on $DATASET (limit=$LIMIT, n=$CONCURRENT)..."
  docker network prune -f 2>/dev/null || true

  harbor run \
    --agent-import-path "$IMPORT_PATH" \
    -m "openai/$MODEL" \
    -d "$DATASET" \
    -o "$OUTPUT" \
    -n "$CONCURRENT" \
    -l "$LIMIT" \
    "${EXTRA_ARGS[@]}" \
    || echo "$(date) | $IMPORT_PATH on $DATASET exited with error $?"

  echo "$(date) | $IMPORT_PATH on $DATASET DONE"
}

echo "================================================================"
echo "Baseline evaluation suite"
echo "Model: $MODEL  |  Server: $URL"
echo "================================================================"

# =====================================================================
# TERMINAL-BENCH 2.0  (89 tasks)
# =====================================================================

# 1. terminus-2
run_agent terminus-2 terminal-bench@2.0 "$RESULTS/terminus2_tb" "$TB_N" "$TB_LIMIT" \
  --agent-kwarg "api_base=$DOCKER_URL" \
  --agent-kwarg "temperature=0.5"

# 2. terminus-kira (custom import path, needs KIRA on PYTHONPATH)
PYTHONPATH="$REPO_ROOT/baselines/KIRA:${PYTHONPATH:-}" \
run_custom_agent "terminus_kira.terminus_kira:TerminusKira" terminal-bench@2.0 \
  "$RESULTS/kira_tb" "$TB_N" "$TB_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6"

# 3. mini-swe-agent
run_agent mini-swe-agent terminal-bench@2.0 "$RESULTS/miniswe_tb" "$TB_N" "$TB_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.5" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192"

# 4. swe-agent
run_agent swe-agent terminal-bench@2.0 "$RESULTS/sweagent_tb" "$TB_N" "$TB_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.5" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192"

# 5. openhands
run_agent openhands terminal-bench@2.0 "$RESULTS/openhands_tb" 2 "$TB_LIMIT"

# 6. qwen-coder
run_agent qwen-coder terminal-bench@2.0 "$RESULTS/qwencoder_tb" "$TB_N" "$TB_LIMIT" \
  --agent-kwarg "base_url=$DOCKER_URL"

# =====================================================================
# SWE-BENCH VERIFIED  (500 tasks)
# =====================================================================

# 1. terminus-2
run_agent terminus-2 swebench-verified "$RESULTS/terminus2_swe" "$SWE_N" "$SWE_LIMIT" \
  --agent-kwarg "api_base=$DOCKER_URL" \
  --agent-kwarg "temperature=0.5"

# 2. terminus-kira
PYTHONPATH="$REPO_ROOT/baselines/KIRA:${PYTHONPATH:-}" \
run_custom_agent "terminus_kira.terminus_kira:TerminusKira" swebench-verified \
  "$RESULTS/kira_swe" "$SWE_N" "$SWE_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6"

# 3. mini-swe-agent
run_agent mini-swe-agent swebench-verified "$RESULTS/miniswe_swe" "$SWE_N" "$SWE_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.5" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192"

# 4. swe-agent
run_agent swe-agent swebench-verified "$RESULTS/sweagent_swe" "$SWE_N" "$SWE_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.5" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192"

# 5. openhands
run_agent openhands swebench-verified "$RESULTS/openhands_swe" 2 "$SWE_LIMIT"

# 6. qwen-coder
run_agent qwen-coder swebench-verified "$RESULTS/qwencoder_swe" "$SWE_N" "$SWE_LIMIT" \
  --agent-kwarg "base_url=$DOCKER_URL"

echo ""
echo "================================================================"
echo "$(date) | ALL BASELINE RUNS COMPLETE"
echo "Results in: $RESULTS"
echo "================================================================"
