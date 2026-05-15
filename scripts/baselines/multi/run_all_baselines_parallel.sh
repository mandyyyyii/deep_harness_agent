#!/usr/bin/env bash
# Fan out 8 workers in parallel: 6 stock baselines pinned to their own
# GLM-4.7-Flash servers, plus 2 meta-harness workers sharing a single SGLang
# endpoint. The two worker classes have different per-task semantics:
#
#   * 6 GLM-pinned baselines (terminus-2, terminus-kira, mini-swe-agent,
#     swe-agent, openhands, qwen-coder), via run_one_baseline.sh:
#       3 OUTER harbor invocations × 2 benchmarks. Each harbor invocation
#       calls the agent once per task (harbor --n-attempts defaults to 1).
#       Output dirs: <baseline>/{tb,swe}_run{1,2,3}/
#
#   * 2 meta-harness workers, via run_metaharness.sh, ONE BENCHMARK EACH
#     (one on TB, one on SWE-Verified):
#       PHASE 1 — metaharness optimizer with BUDGET=1 (default): 1 proposer
#                 call per task = "train once". Produces a per-task workspace
#                 under metaharness-<bench>/phase1_per_task/<task_id>/.
#       PHASE 2 — terminus-2 harbor eval with --n-attempts=ATTEMPTS=3
#                 (default): each task evaluated 3 times = "eval 3 runs".
#                 Output under metaharness-<bench>/phase2_terminus2/.
#
# Assignment:
#   GPU 0 / port 8060 -> terminus-2
#   GPU 1 / port 8061 -> terminus-kira
#   GPU 2 / port 8062 -> mini-swe-agent
#   GPU 3 / port 8063 -> swe-agent
#   GPU 4 / port 8064 -> openhands
#   GPU 5 / port 8065 -> qwen-coder
#   GPU 6            -> meta-harness (Terminal-Bench)   ← shared SGLang endpoint
#   GPU 7            -> meta-harness (SWE-Verified)     ← shared SGLang endpoint
#
# Prerequisite: launch_glm_servers.sh has been run for the per-baseline GLM
# servers on ports 8060-8065. The meta-harness workers (GPU 6, GPU 7) route
# ALL their LLM calls through one shared SGLang endpoint passed as the third
# arg (sglang_port). That endpoint may live on any host/GPU outside this
# script; pin its GPUs separately.
#
# Usage:
#   bash run_all_baselines_parallel.sh [results_root] [base_port] [sglang_port] [model]
#
# Defaults:
#   results_root = $REPO_ROOT/results/glm47_baselines_parallel
#   base_port    = 8060
#   sglang_port  = 8051   # single SGLang endpoint shared by both meta-harness workers
#   model        = qwen3.5-35b-a3b   # model name advertised by the SGLang endpoint
#
# Meta-harness env overrides (forwarded by run_metaharness.sh):
#   BUDGET=1        # phase 1 proposer calls per task ("train once")
#   ATTEMPTS=3      # phase 2 harbor -k attempts per task ("eval 3 runs")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

RESULTS_ROOT="${1:-$REPO_ROOT/results/glm47_baselines_parallel}"
BASE_PORT="${2:-8060}"
SGLANG_PORT="${3:-8051}"
SGLANG_MODEL="${4:-qwen3.5-35b-a3b}"

BASELINES=(terminus-2 terminus-kira mini-swe-agent swe-agent openhands qwen-coder)

# Meta-harness workers: (label, gpu_id, benchmark_short)
META_LABELS=(metaharness-tb metaharness-swe)
META_GPUS=(6 7)
META_BENCHES=(tb swe)

mkdir -p "$RESULTS_ROOT/logs"

echo "================================================================"
echo "Parallel baseline orchestrator"
echo "Results root: $RESULTS_ROOT"
echo "GLM base port: $BASE_PORT   (per-baseline servers on 8060-8065)"
echo "SGLang port:   $SGLANG_PORT (shared by both meta-harness workers)"
echo "SGLang model:  $SGLANG_MODEL"
echo "Baselines:     ${BASELINES[*]}"
echo "Meta-harness:  ${META_LABELS[*]}  (GPUs ${META_GPUS[*]})"
echo "================================================================"

PIDS=()
LABELS=()
for i in "${!BASELINES[@]}"; do
  B="${BASELINES[$i]}"
  PORT=$((BASE_PORT + i))
  LOG="$RESULTS_ROOT/logs/${B}.log"
  OUT="$RESULTS_ROOT/${B}"
  echo "$(date) | launching $B  (GPU $i, port $PORT)  log=$LOG"
  bash "$SCRIPT_DIR/run_one_baseline.sh" "$B" "$PORT" "$OUT" \
    > "$LOG" 2>&1 &
  PIDS+=($!)
  LABELS+=("$B")
done

# Meta-harness workers (arxiv 2603.28052 / SuperagenticAI/metaharness).
# Each pinned to one GPU but sharing the single SGLang endpoint on $SGLANG_PORT.
# CUDA_VISIBLE_DEVICES isolates the orchestrator + any harbor docker containers
# it spawns; the orchestrator itself does no local GPU compute.
MH_SCRIPT="$REPO_ROOT/scripts/baselines/run_metaharness.sh"
for i in "${!META_LABELS[@]}"; do
  LABEL="${META_LABELS[$i]}"
  GPU="${META_GPUS[$i]}"
  BENCH="${META_BENCHES[$i]}"
  LOG="$RESULTS_ROOT/logs/${LABEL}.log"
  OUT="$RESULTS_ROOT/${LABEL}"
  echo "$(date) | launching $LABEL  (GPU $GPU, sglang :$SGLANG_PORT, bench=$BENCH)  log=$LOG"
  CUDA_VISIBLE_DEVICES="$GPU" \
    bash "$MH_SCRIPT" "$SGLANG_PORT" "$BENCH" "$SGLANG_MODEL" "$OUT" \
    > "$LOG" 2>&1 &
  PIDS+=($!)
  LABELS+=("$LABEL")
done

echo ""
echo "Launched ${#PIDS[@]} workers (PIDs: ${PIDS[*]}). Waiting for completion..."
echo ""

FAIL=0
for idx in "${!PIDS[@]}"; do
  pid="${PIDS[$idx]}"
  L="${LABELS[$idx]}"
  if wait "$pid"; then
    echo "$(date) | OK    $L (pid=$pid)"
  else
    rc=$?
    echo "$(date) | FAIL  $L (pid=$pid, rc=$rc)"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "================================================================"
echo "$(date) | All workers finished. Failures: $FAIL"
echo "Logs:    $RESULTS_ROOT/logs/"
echo "GLM baselines:  $RESULTS_ROOT/<baseline>/{tb,swe}_run{1,2,3}/"
echo "Meta-harness:   $RESULTS_ROOT/metaharness-{tb,swe}/phase{1_per_task,2_terminus2}/"
echo "================================================================"
exit $FAIL
