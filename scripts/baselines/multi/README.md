# Parallel baseline evaluation on 8 GPUs

This directory drives the full parallel evaluation: **6 stock agents**
(terminus-2, terminus-kira, mini-swe-agent, swe-agent, openhands, qwen-coder)
plus **2 meta-harness workers** (one per benchmark), in parallel on a single
8-GPU node.

## Pick one model for the whole sweep

For a fair comparison every worker — the 6 stock baselines AND both
meta-harness workers — should run against the **same** model.

| Mode | Model | Status |
|---|---|---|
| **A. All-GLM**     | GLM-4.7-Flash    | Turnkey with the scripts as-shipped |
| **B. All-Qwen3.5** | Qwen3.5-35B-A3B  | Requires 1 file edit + a multi-server launch loop (see below) |

> Mixing models (e.g. GLM baselines + Qwen3.5 meta-harness) is possible but
> defeats the point of a baseline comparison. The shipped defaults of
> `run_all_baselines_parallel.sh` happen to point in that mixed direction;
> the instructions below override that.

## GPU layout (identical for both modes)

| GPU | Port | Worker |
|---|---|---|
| 0 | 8060 | terminus-2 |
| 1 | 8061 | terminus-kira |
| 2 | 8062 | mini-swe-agent |
| 3 | 8063 | swe-agent |
| 4 | 8064 | openhands |
| 5 | 8065 | qwen-coder |
| 6 | 8066 | metaharness-tb  (also serves metaharness-swe as the shared endpoint) |
| 7 | 8067 | metaharness-swe pinned here (no local LLM compute on this GPU) |

Each worker pins to its GPU via `CUDA_VISIBLE_DEVICES`. The two meta-harness
workers do no local GPU compute — they share a single SGLang endpoint, picked
from the per-GPU servers above (we use port 8066 by default; any of 8060–8067
would work).

---

## One-time environment setup

```bash
bash scripts/env/setup_env.sh           # creates conda env "dha_env"
conda activate dha_env
```

This installs harbor (eval framework), sglang, litellm, and per-agent deps.
Prereqs: conda, CUDA, Docker. See `scripts/env/setup_env.sh` for details.

---

## Mode A — All-GLM (turnkey)

### Step 1: launch 8 GLM-4.7-Flash servers

```bash
cd scripts/baselines/multi
bash launch_glm_servers.sh              # GPU i → port 8060+i, i=0..7
```

This launches 8 SGLang servers in the background (PIDs in
`glm_servers.pids`, logs in `logs/glm_gpu{i}.log`), each configured with
`--tool-call-parser glm47 --reasoning-parser glm45 --context-length 131072`.

Wait for readiness:

```bash
for p in $(seq 8060 8067); do
  until curl -sf http://127.0.0.1:$p/v1/models >/dev/null; do sleep 5; done
  echo "  port $p ready"
done
```

### Step 2: fan out all 8 evaluation workers

```bash
bash run_all_baselines_parallel.sh \
  $REPO_ROOT/results/glm47_run \
  8060 8066 GLM-4.7-Flash
#       │     │
#       │     └── meta-harness shared endpoint (one of the GLM ports)
#       └──────── first port for the 6 baselines (consumes 8060..8065)
```

The 4th argument is the meta-harness model name — set it to
`GLM-4.7-Flash` so both meta-harness workers send requests with the model
name that the SGLang server on port 8066 actually serves.

The 6 stock baselines automatically use `GLM-4.7-Flash` because
`run_one_baseline.sh` defines `MODEL="GLM-4.7-Flash"` at line 19.

---

## Mode B — All-Qwen3.5

### Step 1: make the baseline runner use Qwen3.5

`run_one_baseline.sh:19` hardcodes the model name; flip it to Qwen3.5:

```bash
sed -i 's/^MODEL="GLM-4.7-Flash"/MODEL="qwen3.5-35b-a3b"/' \
  scripts/baselines/multi/run_one_baseline.sh
```

(Or open the file and edit line 19 by hand.)

### Step 2: launch 8 Qwen3.5-35B-A3B servers

`launch_qwen35_server.sh` (singular) launches just one tensor-parallel
server, intended for the mixed-mode shared-endpoint use case. For
all-Qwen3.5 you need one server per GPU. Run this loop from
`scripts/baselines/multi/`:

```bash
mkdir -p logs
: > qwen35_servers.pids
for i in $(seq 0 7); do
  PORT=$((8060 + i))
  HF_HOME=/xuanwu-tank/north/xw27/cache CUDA_VISIBLE_DEVICES=$i nohup \
    /xuanwu-tank/north/xw27/envs/sglang_env/bin/python -m sglang.launch_server \
      --model-path Qwen/Qwen3.5-35B-A3B \
      --served-model-name qwen3.5-35b-a3b \
      --host 0.0.0.0 --port $PORT --tp-size 1 \
      --mem-fraction-static 0.85 --context-length 131072 \
      --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
      --trust-remote-code \
      > logs/qwen35_gpu${i}.log 2>&1 &
  echo $! >> qwen35_servers.pids
done
```

Wait for readiness (same loop as mode A, ports 8060–8067).

### Step 3: fan out all 8 evaluation workers

```bash
bash run_all_baselines_parallel.sh \
  $REPO_ROOT/results/qwen35_run \
  8060 8066 qwen3.5-35b-a3b
```

The 4th argument is the meta-harness model name — `qwen3.5-35b-a3b` matches
the `--served-model-name` from the loop above.

---

## Worker semantics (same for both modes)

| Worker | Per-task work |
|---|---|
| 6 stock baselines (via `run_one_baseline.sh`)        | **3 outer harbor invocations × 2 benchmarks.** Each invocation runs the agent once per task (`harbor --n-attempts` defaults to 1). Produces 3 separate result directories: `<baseline>/{tb,swe}_run{1,2,3}/`. |
| meta-harness workers (via `../run_metaharness.sh`)   | **Phase 1: `BUDGET=1` proposer call per task** ("train once"). Optimized harness lands at `phase1_per_task/<task_id>/`. **Phase 2: `ATTEMPTS=3` (`harbor -k 3`)** ⇒ each task evaluated 3 times in a single harbor job. |

The 6 baselines and the meta-harness workers use **different mechanisms** to
get to "3 evaluation runs per task". The baselines repeat the outer
`harbor run` 3 times; meta-harness uses `--n-attempts 3` inside a single
harbor run. Coverage is comparable; the directory layouts differ.

---

## Tuning knobs (env vars)

Set these on the outer command line; both `run_one_baseline.sh` and
`run_metaharness.sh` inherit the parent shell's environment.

| Env var | Affects | Default | Meaning |
|---|---|---|---|
| `BUDGET`    | meta-harness phase 1 | `1`   | `proposer.invoke()` calls per task. The engine always materializes a 1-candidate baseline first; `BUDGET` controls the number of proposer-driven candidates on top. `1` ⇒ "train once". |
| `ATTEMPTS`  | meta-harness phase 2 | `3`   | `harbor --n-attempts (-k)` — independent terminus-2 attempts per task on the phase-1-optimized workspace. `3` ⇒ "eval 3 runs". |
| `TB_LIMIT`  | meta-harness         | `89`  | Number of Terminal-Bench tasks to sweep. |
| `SWE_LIMIT` | meta-harness         | `500` | Number of SWE-bench Verified tasks to sweep. |
| `N`         | meta-harness phase 2 | `4`   | Harbor `--n-concurrent`. |
| `SKIP_PHASE1=1` / `SKIP_PHASE2=1` | meta-harness | unset | Skip a phase. |

> Note: these env vars affect the meta-harness pipeline only. The 6 stock
> baselines use their own internal constants (`TB_N=4`, `SWE_N=4`,
> `TB_LIMIT=89`, `SWE_LIMIT=500`, the outer `for RUN in 1 2 3` loop —
> all hardcoded at `run_one_baseline.sh:35-38,113`). To change them, edit
> that file directly.

---

## Output layout

```
$RESULTS_ROOT/
├── logs/                                       # stdout+stderr per worker
│   ├── terminus-2.log
│   ├── …
│   ├── metaharness-tb.log
│   └── metaharness-swe.log
├── <baseline>/                                 # one dir per stock baseline
│   ├── tb_run1/   tb_run2/   tb_run3/          # 3 separate harbor jobs on TB
│   └── swe_run1/  swe_run2/  swe_run3/         # 3 separate harbor jobs on SWE-Verified
└── metaharness-{tb,swe}/                       # one dir per meta-harness worker
    ├── phase1_per_task/<task_id>/runs/…/workspace   # optimized harness per task
    └── phase2_terminus2/                            # single harbor job, -k 3 attempts/task
```

---

## Stopping / cleanup

From `scripts/baselines/multi/`:

```bash
# All-GLM mode
xargs -a glm_servers.pids -r kill -9

# All-Qwen3.5 mode
xargs -a qwen35_servers.pids -r kill -9

# Stray harbor docker containers (if any worker crashed mid-run)
docker ps -q --filter 'ancestor=harbor' | xargs -r docker kill
docker network prune -f
```

---

## Files in this directory

| File | Role |
|---|---|
| `launch_glm_servers.sh`           | Launch the 8 per-GPU GLM-4.7-Flash SGLang servers (mode A) |
| `launch_qwen35_server.sh`         | Launch **one** Qwen3.5-35B-A3B server (singular; intended for mixed-mode shared-endpoint use, not for the symmetric all-Qwen3.5 setup) |
| `run_one_baseline.sh`             | Inner runner for one stock baseline: 3 harbor jobs × 2 benchmarks. **Line 19 hardcodes the model name — flip it for mode B.** |
| `run_all_baselines_parallel.sh`   | Outer orchestrator — launches all 8 workers and waits |
| `../run_metaharness.sh`           | Inner runner for one meta-harness worker (phase 1 train → phase 2 eval) |
