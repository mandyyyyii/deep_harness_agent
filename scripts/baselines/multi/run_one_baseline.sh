#!/usr/bin/env bash
# Run one baseline against one GLM-4.7-Flash server: 3 runs x 2 benchmarks
# (terminal-bench@2.0 + swebench-verified).
#
# Usage:
#   bash run_one_baseline.sh <baseline> <port> <results_dir>
#
#   baseline:    terminus-2 | terminus-kira | mini-swe-agent | swe-agent | openhands | qwen-coder
#   port:        port of the GLM-4.7-Flash server this baseline should target
#   results_dir: directory under which run-* subdirs are written
#
# All temperature/kwarg settings match scripts/baselines/run_baselines.sh.
set -euo pipefail

BASELINE="${1:?Usage: $0 <baseline> <port> <results_dir>}"
PORT="${2:?Usage: $0 <baseline> <port> <results_dir>}"
RESULTS="${3:?Usage: $0 <baseline> <port> <results_dir>}"

MODEL="GLM-4.7-Flash"
HOST_IP=$(hostname -I | awk '{print $1}')
URL="http://$HOST_IP:$PORT/v1"
DOCKER_URL="http://172.17.0.1:$PORT/v1"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

export OPENAI_API_KEY=dummy
export OPENAI_BASE_URL="$URL"
export OPENAI_API_BASE="$URL"
export SGLANG_API_KEY=dummy
export SGLANG_BASE_URL="$URL"
export LLM_BASE_URL="$URL"

mkdir -p "$RESULTS"
cd "$REPO_ROOT"

TB_N=4
SWE_N=4
TB_LIMIT=89
SWE_LIMIT=500

echo "================================================================"
echo "Baseline:     $BASELINE"
echo "GLM server:   $URL  (docker: $DOCKER_URL)"
echo "Results dir:  $RESULTS"
echo "================================================================"

# Wait for server to come up
echo "$(date) | [$BASELINE port=$PORT] waiting for $URL/models ..."
until curl -sf "$URL/models" >/dev/null 2>&1; do sleep 10; done
echo "$(date) | [$BASELINE port=$PORT] server ready."

run_one() {
  local bench="$1" out_subdir="$2" run_num="$3"
  local out="$RESULTS/${out_subdir}_run${run_num}"
  local n=$TB_N limit=$TB_LIMIT
  if [ "$bench" = "swebench-verified" ]; then n=$SWE_N; limit=$SWE_LIMIT; fi

  echo ""
  echo "$(date) | [$BASELINE run${run_num}] $bench -> $out"
  docker network prune -f 2>/dev/null || true

  case "$BASELINE" in
    terminus-2)
      harbor run \
        -a terminus-2 -m "openai/$MODEL" -d "$bench" \
        -o "$out" -n "$n" -l "$limit" \
        --ak "api_base=$DOCKER_URL" \
        --ak "temperature=0.6" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    terminus-kira)
      PYTHONPATH="$REPO_ROOT/baselines/KIRA:${PYTHONPATH:-}" \
      harbor run \
        --agent-import-path "terminus_kira.terminus_kira:TerminusKira" \
        -m "openai/$MODEL" -d "$bench" \
        -o "$out" -n "$n" -l "$limit" \
        --ak "api_base=$DOCKER_URL" \
        --ak "temperature=0.6" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    mini-swe-agent)
      harbor run \
        -a mini-swe-agent -m "openai/$MODEL" -d "$bench" \
        -o "$out" -n "$n" -l "$limit" \
        --agent-kwarg "model.model_kwargs.temperature=0.6" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    swe-agent)
      harbor run \
        -a swe-agent -m "hosted_vllm/$MODEL" -d "$bench" \
        -o "$out" -n "$n" -l "$limit" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    openhands)
      harbor run \
        -a openhands -m "openai/$MODEL" -d "$bench" \
        -o "$out" -n 2 -l "$limit" \
        --ak "api_base=$DOCKER_URL" \
        --ae "LLM_TEMPERATURE=0.6" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    qwen-coder)
      harbor run \
        -a qwen-coder -m "openai/$MODEL" -d "$bench" \
        -o "$out" -n "$n" -l "$limit" \
        --agent-kwarg "base_url=$DOCKER_URL" \
        || echo "$(date) | $BASELINE $bench run${run_num} exited $?"
      ;;
    *)
      echo "Unknown baseline: $BASELINE"; exit 2 ;;
  esac
}

for RUN in 1 2 3; do
  run_one "terminal-bench@2.0" "tb"  "$RUN"
  run_one "swebench-verified"  "swe" "$RUN"
done

echo ""
echo "$(date) | [$BASELINE port=$PORT] ALL 3 RUNS x 2 BENCHMARKS COMPLETE"
