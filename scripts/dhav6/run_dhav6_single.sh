#!/usr/bin/env bash
# Run DHAv6 on a single benchmark with configurable parameters (for debugging).
#
# Usage:
#   bash run_dhav6_single.sh <sglang_port> <benchmark> [options]
#
# Arguments:
#   sglang_port     Port of the SGLang server (e.g., 8051)
#   benchmark       "tb" for Terminal-Bench 2.0, "swe" for SWE-bench Verified
#
# Options (env vars):
#   MODEL           Model name (default: qwen3.5-35b-a3b)
#   N               Concurrent trials (default: 4 for tb, 2 for swe)
#   LIMIT           Max tasks (default: 89 for tb, 500 for swe)
#   CURATOR         Enable curator (default: true)
#   VALIDATOR       Enable validator (default: true)
#   VALIDATOR_MODE  Validator L2 mode: tolerant|strict (default: tolerant)
#   TEMPERATURE     Sampling temperature (default: 0.6)
#   OUTPUT          Output directory override
set -euo pipefail

PORT="${1:?Usage: $0 <sglang_port> <benchmark: tb|swe>}"
BENCHMARK="${2:?Usage: $0 <sglang_port> <benchmark: tb|swe>}"

MODEL="${MODEL:-qwen3.5-35b-a3b}"
TEMPERATURE="${TEMPERATURE:-0.6}"
CURATOR="${CURATOR:-true}"
VALIDATOR="${VALIDATOR:-true}"
VALIDATOR_MODE="${VALIDATOR_MODE:-tolerant}"

HOST_IP=$(hostname -I | awk '{print $1}')
URL="http://$HOST_IP:$PORT/v1"
DOCKER_URL="http://172.17.0.1:$PORT/v1"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

export OPENAI_API_KEY=dummy
export OPENAI_BASE_URL="$URL"
export OPENAI_API_BASE="$URL"

cd "$REPO_ROOT"

case "$BENCHMARK" in
  tb)
    N="${N:-4}"
    LIMIT="${LIMIT:-89}"
    DATASET="terminal-bench@2.0"
    AGENT_IMPORT="dhav6_agent:DHAv6Agent"
    OUTPUT="${OUTPUT:-results/dhav6_single_tb_${MODEL}}"
    ;;
  swe)
    N="${N:-2}"
    LIMIT="${LIMIT:-500}"
    DATASET="swebench-verified"
    AGENT_IMPORT="dhav6_miniswe_agent:DHAv6MiniSweAgent"
    OUTPUT="${OUTPUT:-results/dhav6_single_swe_${MODEL}}"
    ;;
  *)
    echo "Unknown benchmark: $BENCHMARK (use 'tb' or 'swe')"; exit 1
    ;;
esac

mkdir -p "$OUTPUT"

echo "DHAv6 single run:"
echo "  Benchmark: $DATASET"
echo "  Model:     $MODEL"
echo "  Server:    $URL"
echo "  N:         $N"
echo "  Limit:     $LIMIT"
echo "  Curator:   $CURATOR"
echo "  Validator: $VALIDATOR (mode=$VALIDATOR_MODE)"
echo "  Output:    $OUTPUT"
echo ""

PYTHONPATH="$REPO_ROOT/dhav6:${PYTHONPATH:-}" \
harbor run \
  --agent-import-path "$AGENT_IMPORT" \
  -m "openai/$MODEL" \
  -d "$DATASET" \
  -o "$OUTPUT" \
  -n "$N" \
  -l "$LIMIT" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=$TEMPERATURE" \
  --ak "enable_curator=$CURATOR" \
  --ak "enable_validator=$VALIDATOR" \
  --ak "validator.task_understanding.mode=$VALIDATOR_MODE"

echo "$(date) | Done. Results in: $OUTPUT"
