#!/usr/bin/env bash
# Run the meta-harness baseline (arxiv 2603.28052, SuperagenticAI/metaharness)
# end-to-end on one benchmark, in two phases:
#
#   PHASE 1 — sweep all benchmark tasks. For each task we build a per-task
#             metaharness "project" and run the optimization loop with our
#             SGLang-backed proposer (baselines/metaharness_plugin). With the
#             default BUDGET=1 the loop calls proposer.invoke() ONCE per task
#             ("train once"). The optimized workspace lives at:
#                 $RESULTS/phase1_per_task/$task_id/runs/<run>/candidates/<id>/workspace
#             Every LLM call in this phase goes through the single SGLang
#             endpoint at $URL.
#
#   PHASE 2 — fresh terminus-2 evaluation via harbor against the benchmark.
#             With the default ATTEMPTS=3 (harbor --n-attempts), each task is
#             evaluated 3 times ("eval 3 runs"). The per-task workspaces from
#             phase 1 are exposed to harbor via METAHARNESS_PROPOSALS_DIR (an
#             integration hook — the downstream agent reads them per-task if it
#             knows the env var).
#
# Usage:
#   bash scripts/baselines/run_metaharness.sh <sglang_port> <benchmark:tb|swe> [model] [results_dir]
#
# Env overrides:
#   TB_LIMIT       (default 89)         # number of tasks to sweep on TB
#   SWE_LIMIT      (default 500)        # ... on SWE-bench Verified
#   N              (default 4)          # n_concurrent in phase 2 harbor run
#   BUDGET         (default 1)          # metaharness budget per task. The engine
#                                       # always materializes a 1-candidate baseline
#                                       # (no proposer call), then calls
#                                       # proposer.invoke() BUDGET times. So
#                                       # BUDGET=1 ⇒ 1 proposer call per task in
#                                       # phase 1 ("train once").
#   ATTEMPTS       (default 3)          # harbor --n-attempts (-k) in phase 2:
#                                       # how many times terminus-2 evaluates each
#                                       # task. Default 3 ⇒ "evaluate 3 runs".
#   TASK_INDEX_FILE                     # path to newline-separated task IDs;
#                                       # if unset, synthetic ids 0..LIMIT-1 are used
#   SKIP_PHASE1=1  / SKIP_PHASE2=1      # skip a phase
#
set -euo pipefail

PORT="${1:?Usage: $0 <sglang_port> <benchmark:tb|swe> [model] [results_dir]}"
BENCH_SHORT="${2:?Usage: $0 <sglang_port> <benchmark:tb|swe> [model] [results_dir]}"
MODEL="${3:-qwen3.5-35b-a3b}"
RESULTS_ARG="${4:-}"

case "$BENCH_SHORT" in
  tb)  HARBOR_BENCH="terminal-bench@2.0"; LIMIT="${TB_LIMIT:-89}"  ;;
  swe) HARBOR_BENCH="swebench-verified";  LIMIT="${SWE_LIMIT:-500}";;
  *) echo "Unknown benchmark: $BENCH_SHORT (expected tb|swe)" >&2; exit 2 ;;
esac

HOST_IP=$(hostname -I | awk '{print $1}')
URL="http://$HOST_IP:$PORT/v1"
DOCKER_URL="http://172.17.0.1:$PORT/v1"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESULTS="${RESULTS_ARG:-$REPO_ROOT/results/metaharness_${MODEL}_${BENCH_SHORT}}"
TASKS_DIR="$RESULTS/phase1_per_task"
PHASE2_DIR="$RESULTS/phase2_terminus2"
TEMPLATE="$RESULTS/template"

MH_ROOT="$REPO_ROOT/baselines/metaharness"
PLUGIN_ROOT="$REPO_ROOT/baselines"

PY="${PYTHON:-python}"
N="${N:-4}"
BUDGET="${BUDGET:-1}"
ATTEMPTS="${ATTEMPTS:-3}"

# All proposals share this single OpenAI-compatible SGLang endpoint.
export OPENAI_API_KEY=dummy
export OPENAI_BASE_URL="$URL"
export OPENAI_API_BASE="$URL"
export SGLANG_API_KEY=dummy
export SGLANG_BASE_URL="$URL"
export SGLANG_MODEL="$MODEL"
export LLM_BASE_URL="$URL"
export PYTHONPATH="$PLUGIN_ROOT:$MH_ROOT/src:${PYTHONPATH:-}"

mkdir -p "$RESULTS" "$TASKS_DIR" "$PHASE2_DIR" "$TEMPLATE/baseline"

echo "================================================================"
echo "Meta-harness baseline"
echo "  benchmark  : $HARBOR_BENCH ($BENCH_SHORT)"
echo "  model      : $MODEL"
echo "  sglang URL : $URL"
echo "  docker URL : $DOCKER_URL"
echo "  results    : $RESULTS"
echo "  budget/task: $BUDGET   limit: $LIMIT   phase2 n: $N   phase2 attempts/task: $ATTEMPTS"
if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
  echo "  pinned GPU : CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
fi
echo "================================================================"

# ----------------------------------------------------------------------
# Per-task metaharness project template
# ----------------------------------------------------------------------
cat > "$TEMPLATE/metaharness.json" <<JSON
{
  "objective": "Improve the agent harness for the $HARBOR_BENCH task referenced in TASK.md. Edit AGENTS.md so a downstream terminus-2 agent has the guidance, allowed commands, and stopping rules it needs to pass this task.",
  "constraints": [
    "Keep edits short and concrete.",
    "Do not invent task content that is not in TASK.md.",
    "Stay within the allowed write scope."
  ],
  "baseline_dir": "baseline",
  "runs_dir": "runs",
  "tasks_file": "tasks.json",
  "required_files": ["AGENTS.md", "TASK.md"],
  "allowed_write_paths": ["AGENTS.md"],
  "backend_plugins": {
    "sglang": {
      "factory": "metaharness_plugin.sglang_backend:create_backend",
      "options": {
        "base_url": "$URL",
        "api_key":  "dummy",
        "model":    "$MODEL",
        "temperature": 0.5,
        "max_tokens":  8192
      }
    }
  },
  "default_budget": $BUDGET
}
JSON

cat > "$TEMPLATE/tasks.json" <<'JSON'
[
  {"id":"has-header","type":"file_phrase","path":"AGENTS.md","weight":0.5,
   "required_phrases":["# Agent Instructions"]},
  {"id":"references-task","type":"file_phrase","path":"AGENTS.md","weight":1.0,
   "required_phrases":["TASK.md"]},
  {"id":"non-trivial","type":"command","weight":1.0,
   "command":"test $(wc -c < AGENTS.md) -gt 200","expect_exit_code":0}
]
JSON

cat > "$TEMPLATE/baseline/AGENTS.md" <<'MD'
# Agent Instructions
(Baseline harness. The optimizer should rewrite this to give the downstream
terminus-2 agent task-specific guidance based on TASK.md.)
MD

# TASK.md is rewritten per task below.

# ----------------------------------------------------------------------
# Task index: either user-provided, or synthetic ids [0, LIMIT)
# ----------------------------------------------------------------------
TASK_INDEX="$RESULTS/task_index.txt"
if [ -n "${TASK_INDEX_FILE:-}" ] && [ -s "${TASK_INDEX_FILE}" ]; then
  cp "$TASK_INDEX_FILE" "$TASK_INDEX"
  echo "Using $TASK_INDEX_FILE ($(wc -l < "$TASK_INDEX") tasks)."
else
  seq 0 $((LIMIT - 1)) | awk '{printf("%s-task-%04d\n", "'"$BENCH_SHORT"'", $1)}' > "$TASK_INDEX"
  echo "TASK_INDEX_FILE not set; using synthetic ids ($(wc -l < "$TASK_INDEX"))."
fi

# ----------------------------------------------------------------------
# PHASE 1: per-task metaharness optimization
# ----------------------------------------------------------------------
if [ "${SKIP_PHASE1:-0}" = "1" ]; then
  echo "SKIP_PHASE1=1 — skipping phase 1."
else
  echo ""
  echo "$(date) | PHASE 1 — metaharness sweep (sglang backend) over $(wc -l < "$TASK_INDEX") tasks"

  P1_FAILS=0
  P1_OK=0
  while IFS= read -r TASK_ID; do
    [ -z "$TASK_ID" ] && continue
    TASK_PROJ="$TASKS_DIR/$TASK_ID"
    rm -rf "$TASK_PROJ"
    cp -r "$TEMPLATE" "$TASK_PROJ"
    cat > "$TASK_PROJ/baseline/TASK.md" <<EOF
# Task: $TASK_ID
Benchmark: $HARBOR_BENCH
This is task $TASK_ID. The harness should help the agent solve this benchmark
task; rewrite AGENTS.md with concrete guidance.
EOF

    if "$PY" -m metaharness.cli run "$TASK_PROJ" \
          --backend sglang \
          --budget "$BUDGET" \
          --run-name "$TASK_ID" \
          > "$TASK_PROJ/metaharness.stdout.log" \
          2> "$TASK_PROJ/metaharness.stderr.log"; then
      P1_OK=$((P1_OK+1))
    else
      echo "  [$TASK_ID] metaharness run failed (rc=$?). See $TASK_PROJ/metaharness.stderr.log"
      P1_FAILS=$((P1_FAILS+1))
    fi
  done < "$TASK_INDEX"
  echo "$(date) | PHASE 1 done. ok=$P1_OK  failed=$P1_FAILS"
fi

# ----------------------------------------------------------------------
# PHASE 2: fresh terminus-2 evaluation via harbor
# ----------------------------------------------------------------------
if [ "${SKIP_PHASE2:-0}" = "1" ]; then
  echo "SKIP_PHASE2=1 — skipping phase 2."
  echo "Results in: $RESULTS"
  exit 0
fi

echo ""
echo "$(date) | PHASE 2 — terminus-2 fresh eval on $HARBOR_BENCH"
docker network prune -f 2>/dev/null || true

# Expose per-task modified workspaces to any agent that knows how to read them.
# Hook point: terminus-2 / a wrapper can read METAHARNESS_PROPOSALS_DIR and
# prepend the matching task's AGENTS.md to its system prompt. Wiring that
# read-side is out of scope for this script.
harbor run \
  -a terminus-2 \
  -m "openai/$MODEL" \
  -d "$HARBOR_BENCH" \
  -o "$PHASE2_DIR" \
  -n "$N" -l "$LIMIT" -k "$ATTEMPTS" \
  --ak "api_base=$DOCKER_URL" \
  --ak "temperature=0.6" \
  --ae "METAHARNESS_PROPOSALS_DIR=$TASKS_DIR" \
  --ae "METAHARNESS_BENCHMARK=$BENCH_SHORT" \
  || echo "$(date) | phase 2 terminus-2 exited with $?"

echo ""
echo "================================================================"
echo "$(date) | DONE."
echo "Phase 1 workspaces : $TASKS_DIR/<task_id>/runs/<task_id>/candidates/<id>/workspace"
echo "Phase 2 harbor out : $PHASE2_DIR"
echo "================================================================"
