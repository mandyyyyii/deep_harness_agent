#!/usr/bin/env bash
# Run DHAv6 with curator + validator enabled on Terminal-Bench 2.0 and SWE-bench Verified.
#
# Usage:
#   bash run_dhav6.sh <sglang_port> [model_name]
#
# Example:
#   bash run_dhav6.sh 8051 qwen3.5-35b-a3b
#
# Config:
#   Terminal-Bench 2.0:  n=20 concurrent, 89 tasks, curator=true, validator=true
#   SWE-bench Verified:  n=50 concurrent, 500 tasks, curator=true, validator=true
set -euo pipefail

PORT="${1:?Usage: $0 <sglang_port> [model_name]}"
MODEL="${2:-qwen3.5-35b-a3b}"

HOST_IP=$(hostname -I | awk '{print $1}')
URL="http://$HOST_IP:$PORT/v1"
DOCKER_URL="http://172.17.0.1:$PORT/v1"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESULTS="$REPO_ROOT/results/dhav6_${MODEL}"

export OPENAI_API_KEY=dummy
export OPENAI_BASE_URL="$URL"
export OPENAI_API_BASE="$URL"

cd "$REPO_ROOT"
mkdir -p "$RESULTS"

# Common DHAv6 kwargs
SAMPLING='llm_kwargs={"top_p":0.95,"presence_penalty":0.0,"extra_body":{"top_k":20,"min_p":0.0,"repetition_penalty":1.0,"chat_template_kwargs":{"enable_thinking":true}}}'

echo "================================================================"
echo "DHAv6 evaluation (curator + validator enabled)"
echo "Model: $MODEL  |  Server: $URL"
echo "================================================================"

# =====================================================================
# TERMINAL-BENCH 2.0  (89 tasks, n=20)
# =====================================================================
echo ""
echo "$(date) | Starting DHAv6 on Terminal-Bench 2.0 (n=20, curator+validator)..."
docker network prune -f 2>/dev/null || true

PYTHONPATH="$REPO_ROOT/dhav6:${PYTHONPATH:-}" \
harbor run \
  --agent-import-path dhav6_agent:DHAv6Agent \
  -m "openai/$MODEL" \
  -d terminal-bench@2.0 \
  -o "$RESULTS/dhav6_tb" \
  -n 20 \
  -l 89 \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  --ak "$SAMPLING" \
  --ak "enable_curator=true" \
  --ak "enable_validator=true" \
  || echo "$(date) | DHAv6 TB exited with error $?"

echo "$(date) | DHAv6 on Terminal-Bench 2.0 DONE"

# =====================================================================
# SWE-BENCH VERIFIED  (500 tasks, n=50)
# =====================================================================
echo ""
echo "$(date) | Starting DHAv6 on SWE-bench Verified (n=50, curator+validator)..."
docker network prune -f 2>/dev/null || true

PYTHONPATH="$REPO_ROOT/dhav6:${PYTHONPATH:-}" \
harbor run \
  --agent-import-path dhav6_miniswe_agent:DHAv6MiniSweAgent \
  -m "openai/$MODEL" \
  -d swebench-verified \
  -o "$RESULTS/dhav6_swe" \
  -n 50 \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  --ak "$SAMPLING" \
  --ak "enable_curator=true" \
  --ak "enable_validator=true" \
  || echo "$(date) | DHAv6 SWE exited with error $?"

echo "$(date) | DHAv6 on SWE-bench Verified DONE"

echo ""
echo "================================================================"
echo "$(date) | ALL DHAv6 RUNS COMPLETE"
echo "Results in: $RESULTS"
echo "================================================================"
