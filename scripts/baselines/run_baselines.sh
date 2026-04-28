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
#
# Notes on model prefix:
#   - Most agents use "openai/<model>" prefix for OpenAI-compatible endpoints.
#   - swe-agent requires "hosted_vllm/<model>" prefix (uses litellm routing).
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

TB_N=4    # concurrent trials for terminal-bench
SWE_N=4    # concurrent trials for swe-bench
TB_LIMIT=89
SWE_LIMIT=500

echo "================================================================"
echo "Baseline evaluation suite"
echo "Model: $MODEL  |  Server: $URL"
echo "Docker URL: $DOCKER_URL"
echo "================================================================"

# =====================================================================
# TERMINAL-BENCH 2.0  (89 tasks)
# =====================================================================

# --- 1. terminus-2 ---
echo ""
echo "$(date) | [TB 1/6] terminus-2 on terminal-bench..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a terminus-2 \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/terminus2_tb" \
  -n "$TB_N" -l "$TB_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  || echo "$(date) | terminus-2 TB exited with error $?"

# --- 2. terminus-kira ---
echo ""
echo "$(date) | [TB 2/6] terminus-kira on terminal-bench..."
docker network prune -f 2>/dev/null || true
PYTHONPATH="$REPO_ROOT/baselines/KIRA:${PYTHONPATH:-}" \
harbor run \
  --agent-import-path "terminus_kira.terminus_kira:TerminusKira" \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/kira_tb" \
  -n "$TB_N" -l "$TB_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  || echo "$(date) | terminus-kira TB exited with error $?"

# --- 3. mini-swe-agent ---
echo ""
echo "$(date) | [TB 3/6] mini-swe-agent on terminal-bench..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a mini-swe-agent \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/miniswe_tb" \
  -n "$TB_N" -l "$TB_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.6" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192" \
  || echo "$(date) | mini-swe-agent TB exited with error $?"

# --- 4. swe-agent (uses hosted_vllm/ prefix) ---
echo ""
echo "$(date) | [TB 4/6] swe-agent on terminal-bench..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a swe-agent \
  -m "hosted_vllm/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/sweagent_tb" \
  -n "$TB_N" -l "$TB_LIMIT" \
  || echo "$(date) | swe-agent TB exited with error $?"

# --- 5. openhands ---
echo ""
echo "$(date) | [TB 5/6] openhands on terminal-bench..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a openhands \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/openhands_tb" \
  -n 2 -l "$TB_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  || echo "$(date) | openhands TB exited with error $?"

# --- 6. qwen-coder ---
echo ""
echo "$(date) | [TB 6/6] qwen-coder on terminal-bench..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a qwen-coder \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/qwencoder_tb" \
  -n "$TB_N" -l "$TB_LIMIT" \
  --agent-kwarg "base_url=$DOCKER_URL" \
  || echo "$(date) | qwen-coder TB exited with error $?"

# =====================================================================
# SWE-BENCH VERIFIED  (500 tasks)
# =====================================================================

# --- 1. terminus-2 ---
echo ""
echo "$(date) | [SWE 1/6] terminus-2 on swebench-verified..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a terminus-2 \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/terminus2_swe" \
  -n "$SWE_N" -l "$SWE_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  || echo "$(date) | terminus-2 SWE exited with error $?"

# --- 2. terminus-kira ---
echo ""
echo "$(date) | [SWE 2/6] terminus-kira on swebench-verified..."
docker network prune -f 2>/dev/null || true
PYTHONPATH="$REPO_ROOT/baselines/KIRA:${PYTHONPATH:-}" \
harbor run \
  --agent-import-path "terminus_kira.terminus_kira:TerminusKira" \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/kira_swe" \
  -n "$SWE_N" -l "$SWE_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  || echo "$(date) | terminus-kira SWE exited with error $?"

# --- 3. mini-swe-agent ---
echo ""
echo "$(date) | [SWE 3/6] mini-swe-agent on swebench-verified..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a mini-swe-agent \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/miniswe_swe" \
  -n "$SWE_N" -l "$SWE_LIMIT" \
  --agent-kwarg "model.model_kwargs.temperature=0.6" \
  --agent-kwarg "model.model_kwargs.max_tokens=8192" \
  || echo "$(date) | mini-swe-agent SWE exited with error $?"

# --- 4. swe-agent (uses hosted_vllm/ prefix) ---
echo ""
echo "$(date) | [SWE 4/6] swe-agent on swebench-verified..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a swe-agent \
  -m "hosted_vllm/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/sweagent_swe" \
  -n "$SWE_N" -l "$SWE_LIMIT" \
  || echo "$(date) | swe-agent SWE exited with error $?"

# --- 5. openhands ---
echo ""
echo "$(date) | [SWE 5/6] openhands on swebench-verified..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a openhands \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/openhands_swe" \
  -n 2 -l "$SWE_LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  || echo "$(date) | openhands SWE exited with error $?"

# --- 6. qwen-coder ---
echo ""
echo "$(date) | [SWE 6/6] qwen-coder on swebench-verified..."
docker network prune -f 2>/dev/null || true
harbor run \
  -a qwen-coder \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/qwencoder_swe" \
  -n "$SWE_N" -l "$SWE_LIMIT" \
  --agent-kwarg "base_url=$DOCKER_URL" \
  || echo "$(date) | qwen-coder SWE exited with error $?"

echo ""
echo "================================================================"
echo "$(date) | ALL BASELINE RUNS COMPLETE"
echo "Results in: $RESULTS"
echo "================================================================"
