# DHAv6 Ablation Experiment: Trajectory Analysis

## Overview

This document analyzes representative trajectories from the DHAv6 curator and validator ablation experiments, showing exactly how each component affects agent behavior.

---

## Part 1: Curator Ablation (reserved_turns sweep)

The curator controls how many recent turns are kept verbatim in the prompt. Older turns are summarized or dropped entirely.

| Setting | reserved_turns | Resolve Rate |
|---------|---------------|-------------|
| N=10    | 10            | 56.9%       |
| N=50    | 50            | 61.3% (best)|
| N=100   | 100           | 58.9%       |

---

### Example 1: N=50 PASSED, N=10 FAILED -- `sympy__sympy-23413`

**Task:** Fix bug where `hermite_normal_form` removes rows from non-square matrices. The HNF algorithm incorrectly uses `rows = min(m, n)` instead of `rows = m`, causing it to skip rows when m > n.

| Metric | N=10 (FAIL) | N=50 (PASS) | N=100 (FAIL) |
|--------|------------|-------------|-------------|
| Steps | 76 | 73 | 136 |
| Total prompt tokens | 1,149,435 | 1,659,183 | 6,299,159 |
| Total completion tokens | -- | -- | 108,780 |
| Curator drops | **17** | 8 | 12 |
| Token range | 847 - 53,016 | 845 - 56,712 | 848 - 109,661 |

**Trajectory paths:**
- N=10: `<cluster_path>
- N=50: `<cluster_path>
- N=100: `<cluster_path>

#### N=50 token progression (key window, showing the successful fix):

```
AgentTurn 37 (step 38): 34,766tok | bash_command    -- examining normalforms.py
AgentTurn 38 (step 39): 35,113tok | bash_command    -- sed -n '206,220p' (reading the buggy line)
AgentTurn 39 (step 40): 35,814tok | bash_command x2 -- sed -i 's/rows = min(m, n)/rows = m/'  <-- THE FIX
AgentTurn 40 (step 41): 36,466tok | bash_command    -- python3 test to verify fix works
AgentTurn 41 (step 42): 37,915tok | bash_command x2 -- additional fix, running tests
... (continues to pass tests and submit)
```

The N=50 agent maintained steady token growth (845 -> 56,712), with curator drops only occurring late (turn 55+) after the fix was already applied. By turn 39, the agent had accumulated enough context from 38 prior turns to understand the algorithm, locate the bug on line 211, and apply a precise one-line fix.

#### N=10 token progression (showing destructive curator drops):

```
AgentTurn 18 (step 19): 16,811tok | no-tool
AgentTurn 19 (step 20):  3,705tok | bash_command  <<< CURATOR DROP (lost 13,106 tokens)
                         cmd: head -200 sympy/polys/matrices/normalforms.py  <-- RE-READING the file!
AgentTurn 22 (step 23): 15,596tok | bash_command
AgentTurn 23 (step 24):  2,654tok | bash_command  <<< CURATOR DROP (lost 12,942 tokens)
                         cmd: sed -n '250,260p' normalforms.py  <-- RE-READING the same section!
...
AgentTurn 40 (step 41):  2,623tok | bash_command  <<< CURATOR DROP (lost 30,694 tokens)
...
AgentTurn 46 (step 47): 37,108tok | bash_command  -- viewing normalforms.py AGAIN
AgentTurn 47 (step 48):  2,937tok | bash_command  <<< CURATOR DROP (lost 34,171 tokens)
                         cmd: sed -i '249s/...'  <-- applying a fix, but without full context
```

**Critical failure pattern:** N=10 had **17 curator drops** across 75 agent turns. After each drop, the agent lost awareness of what it had already read and tried, causing it to:
1. Re-read `normalforms.py` at least 8 times (vs 3 times in N=50)
2. Apply and revert fixes repeatedly (at least 5 `git checkout` cycles)
3. Run out of turns before converging on the correct fix

The most damaging drops occurred at turns 40 (30,694 tokens lost) and 47 (34,171 tokens lost), where the agent had just built up understanding of the algorithm but lost it all. Each time, it spent 5-10 turns re-reading the same files before the curator dropped them again.

#### Diagnosis (N=10 vs N=50):
N=10's aggressive compression created a "Sisyphean loop": the agent would spend 8-10 turns building context about the HNF algorithm, the curator would trim everything but the last 10 turns, and the agent would lose its understanding and start over. N=50 avoided this by retaining enough history for the agent to accumulate understanding across 39 turns before finding the fix.

---

### Example 2: N=50 PASSED, N=100 FAILED -- `sympy__sympy-23413` (same task)

N=100 also failed on this task, but for the opposite reason.

#### N=100 token progression:

```
AgentTurn  0:     848tok
AgentTurn 50: ~45,000tok  (still exploring, no fix applied)
AgentTurn 80: ~75,000tok  (still exploring)
AgentTurn100: ~90,805tok  <<< first curator drop at turn 101
AgentTurn130: 100,914tok  (133 turns in, still no correct fix)
AgentTurn134: 101,045tok  -- trying a heredoc fix, quoting fails
AgentTurn135:   6,587tok  -- final turn, applied fix but didn't verify
```

**136 total steps** vs N=50's 73 steps. N=100 consumed **6.3M prompt tokens** (vs N=50's 1.66M) -- a 3.8x increase.

**Critical failure pattern:** With 100 reserved turns, the context grew to **109,661 tokens** before the first curator drop. The agent drowned in its own history:
- It spent 100+ turns attempting fixes without the curator trimming failed attempts
- Old failed approaches remained in context, confusing the model about what had already been tried
- The prompt became so bloated that the model's attention was diluted across ~100K tokens of mostly-failed attempts
- When curator drops finally kicked in (turn 101+), it was too late -- the agent had already burned most of its budget

#### Diagnosis (N=50 vs N=100):
N=50's curator struck the right balance: it preserved enough context for continuity (50 turns) while trimming old failed attempts that would otherwise pollute the prompt. N=100 preserved too much history, including many failed fix attempts that occupied attention without adding value.

---

### Example 3: N=50 PASSED, N=10 FAILED -- `django__django-14787`

**Task:** Fix `method_decorator` to properly handle wrapper assignments.

| Metric | N=10 (FAIL) | N=50 (PASS) | N=100 (FAIL) |
|--------|------------|-------------|-------------|
| Steps | 47 | 50 | 32 |
| Total prompt tokens | 583,335 | 992,257 | 485,656 |
| Curator drops (N=10) | ~15 | 4 | 3 |

**Trajectory paths:**
- N=10: `<cluster_path>
- N=50: `<cluster_path>
- N=100: `<cluster_path>

#### N=50 (PASS) key moment:

The N=50 agent methodically iterated through 6 fix attempts (fix.py through fix6.py), each time learning from the previous failure. By turn 36 (fix5.py) it had the right approach, verified through tests at turns 40 and 45-47, and submitted at turn 48 with `mark_task_complete`.

Token progression: Steady growth from 910 to 39,744, with NO curator drops until late. The agent maintained full awareness of all its fix attempts and test results.

#### N=10 (FAIL) critical divergence:

```
Turn 13 (step 13):  1,726tok  <<< CURATOR DROP -- lost knowledge of fix attempts
Turn 18 (step 18):  8,895tok  -- rejected 4 times trying heredoc approach
Turn 21 (step 21):  4,224tok  <<< context trimmed again
...
Turn 35 (step 35):  2,001tok  <<< dropped again, lost test results
Turn 39 (step 39):  2,546tok  -- no-tool, confused
Turn 45 (step 45): 35,752tok  -- gives up without submitting a working fix
```

The N=10 agent lost track of which fix approaches had already failed, leading to repeated attempts with the same broken heredoc patterns. It also couldn't find the test runner (`runtests.py`) and spent its last 10 turns flailing between wrong test commands.

#### Diagnosis:
For this task requiring iterative refinement (6 fix attempts), N=10's aggressive trimming destroyed the iterative learning loop. The agent couldn't remember what it had already tried.

---

## Part 2: Validator Ablation (SWE-bench modes)

Three validator modes were tested:
- **strict**: Rejects redundant reads, wasteful exploration, shallow edits, and premature submissions
- **tolerant**: Only rejects clear errors (syntax errors, exact duplicate commands)
- **rules-only**: Only rejects shell syntax errors (no semantic validation)

---

### Example 1: STRICT mode -- `sphinx-doc__sphinx-9229` (FAIL, 184 rejections)

**Path:** `<cluster_path>
**Result:** FAIL (also failed in tolerant and rules-only modes)
**Steps:** 218 | **Rejections:** 184

#### Turn-by-turn (showing the rejection cascade):

```
Turn 12 [REJECTED]: "REDUNDANT_VERIFICATION - repeating a command from turn 10 (viewing genericalias.py).
                      The file content hasn't changed."
Turn 19 [REJECTED]: "WASTEFUL_EXPLORATION - re-reading code already examined multiple times without taking action."
Turn 22 [REJECTED]: "WASTEFUL_EXPLORATION - re-reading code already examined multiple times without taking action."
...
Turns 215-217:       Agent recognizes it's "stuck in a loop for 200+ turns" but cannot escape.
                     Final tokens: 136,799 -> 138,004 (massive context, no progress)
```

**What the strict validator rejected:** The agent kept re-reading the same source files (genericalias.py, autodoc code) without making edits. The strict validator correctly identified this as wasteful, but the rejections themselves consumed turns and added to context bloat, creating a compounding problem.

**Did the rejection help or hurt?** HURT. The strict validator was factually correct (the agent WAS repeating reads), but the rejections prevented the agent from re-establishing context it needed. The task failed in all three modes, so this is a case where the task was fundamentally hard and the strict validator made it worse by adding 184 rejection messages to an already bloated context.

---

### Example 2: TOLERANT mode -- `pytest-dev__pytest-7571` (PASS, 1 rejection)

**Path:** `<cluster_path>
**Result:** PASS | **Steps:** 21 | **Rejections:** 1

Compared to STRICT mode on the same task:
**Path:** `<cluster_path>
**Result:** FAIL | **Steps:** 215 | **Rejections:** 135

#### TOLERANT turn-by-turn (21 steps, solved efficiently):

```
Turn  1:    845tok | bash_command x2    -- ls -la and explore structure
Turn  2:  2,108tok | bash_command       -- cat ./src/_pytest/logging.py (full file)
Turn  3:  4,668tok | bash_command x3    -- grep LogCaptureHandler, find _finalize
Turn  4:  6,341tok | bash_command       -- read _finalize method closely
Turn  5:  8,015tok | bash_command x2    -- write reproducer test
Turn  8: 10,251tok | no-tool [REJECTED] -- "WASTEFUL_EXPLORATION: already viewed this code"
Turn  9: 10,688tok | bash_command       -- write fix.py (first fix attempt)
Turn 10: 11,962tok | bash_command       -- run test -> passes
Turn 14: 13,787tok | bash_command       -- write fix2.py (refined fix)
Turn 15: 14,533tok | bash_command       -- run test -> passes
Turn 18: 18,328tok | bash_command x2    -- verify final state, run comprehensive tests
Turn 19: 19,046tok | no-tool            -- submit
```

The single rejection at turn 8 was appropriate: the agent was about to re-read code it already had in context. It recovered immediately and moved to writing the fix.

#### STRICT turn-by-turn (first 30 of 215 steps):

```
Turn  1:    846tok | bash_command x2    -- ls -la
Turn  2:  2,131tok | bash_command       -- cat logging.py
Turn  3:  4,674tok | bash_command x2    -- grep level
...
Turn 13: 15,944tok | bash_command       -- first fix attempt
Turn 14: 17,311tok | bash_command       -- run test
Turn 16: 18,290tok | no-tool [REJECTED] -- "SHALLOW_EDIT: saves handler level AFTER setting it, not before"
Turn 17: 19,150tok | no-tool [REJECTED] -- shell syntax error
Turn 19: 20,004tok | no-tool [REJECTED] -- "SHALLOW_EDIT"
Turn 23: 21,806tok | no-tool [REJECTED] -- again
Turn 27: 24,006tok | no-tool [REJECTED] -- again
Turn 28: 24,408tok | no-tool [REJECTED] -- again
Turn 29: 24,732tok | no-tool [REJECTED] -- again
... (continues for 185 more turns)
```

**Critical divergence at turn 16:** The strict validator rejected the fix as a "SHALLOW_EDIT" claiming a bug in the fix logic. This assessment may have been overly aggressive -- the tolerant validator allowed a similar fix through and the task passed. The strict validator's rejection triggered a cascade: each rejected attempt added to context, the agent tried variations that were also rejected, and it spiraled into 135 rejections over 215 turns.

#### Diagnosis:
The strict validator's semantic checks (SHALLOW_EDIT, WASTEFUL_EXPLORATION) can be counterproductive when they reject attempts that are close to correct. The tolerant validator let the agent iterate freely and converge in 21 turns. Strict prevented convergence and burned 10x more tokens.

---

### Example 3: RULES-ONLY mode -- `scikit-learn__scikit-learn-12682`

**RULES-ONLY result:** PASS, 68 steps, 0 rejections
- Path: `<cluster_path>

**STRICT result:** FAIL, 279 steps, 197 rejections
- Path: `<cluster_path>

The strict rejections were primarily "Empty or whitespace-only command" -- the agent was trying to send empty keystrokes (likely waiting for terminal output). The rules-only validator allowed these through, letting the agent proceed naturally. In strict mode, 197 such rejections accumulated in context, bloating the prompt and preventing the agent from making progress.

#### Diagnosis:
For this task, the strict validator's pedantic enforcement of "no empty commands" was actively harmful. The rules-only mode's minimal intervention (only syntax errors) allowed the agent to work naturally and solve the task in 68 steps vs 279 failed steps.

---

## Part 3: Terminal-Bench Validator Ablation

### Example 1: STRICT mode -- `distribution-search` (FAIL, 47 rejections)

**Path:** `<cluster_path>
**Result:** FAIL | **Steps:** 54 | **Rejections:** 47

#### Turn-by-turn summary:

```
Turn  1:  1,020tok | bash_command x2 -- initial solver attempt (differential evolution)
Turn  3:  5,631tok | bash_command x2 -- second solver attempt (grid search)
Turn  5:  9,975tok | bash_command    -- third attempt (fsolve)
Turn  6: 12,489tok | bash_command    -- fourth attempt (still optimizing same approach)
Turn  7: 15,848tok | bash_command    -- fifth attempt
Turn  8: 19,100tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: stuck in optimization loops for 6+ turns"
Turn  9: 20,248tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: 7+ turns, proposed 150,000 iterations"
Turn 10: 21,777tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: 8+ turns"
Turn 11: 23,814tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: 9+ turns"
Turn 12: 25,631tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: 10+ turns"
Turn 13: 27,421tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: 11+ turns"
Turn 14: 28,682tok | bash_command   -- finally allowed through (different approach: direct optimization)
Turn 15: 31,470tok | [REJECTED]     -- "WASTEFUL_EXPLORATION" again
Turn 16-53:         | 39 more rejections, never recovers
```

**The catastrophic cascade:** After turn 8, the strict validator entered a death spiral. It rejected the agent's mathematical optimization attempts as "wasteful exploration," but each rejection message described the full history of what the agent had tried, adding ~1,500 tokens per rejection. Over 39 consecutive rejections (turns 15-53), the context grew from 31,470 to 90,368 tokens -- almost entirely rejection messages rather than actual work.

**Did the rejection help?** HURT CATASTROPHICALLY. The validator correctly identified the agent was iterating on the same approach, but its rejections prevented the agent from trying ANY approach. The agent tried to pivot to power-law distributions (turn 13), sparse distributions (turn 12), and general optimization (turn 14), but the validator rejected all of these as variants of "the same approach." The task also failed in tolerant mode (104 rejections, same underlying mathematical difficulty), suggesting the task was genuinely hard -- but strict mode made it worse.

---

### Example 2: STRICT mode -- `largest-eigenval` (PASS, 5 rejections)

**Path:** `<cluster_path>
**Result:** PASS | **Steps:** 24 | **Rejections:** 5

This task PASSED in strict but FAILED in tolerant. The strict validator helped here.

#### Turn-by-turn summary:

```
Turn  1:    891tok | bash_command x2 -- read eigen.py, explore task
Turn  2:  1,924tok | bash_command    -- check scipy availability
Turn  3:  2,210tok | bash_command    -- install scipy
Turn  4:  2,686tok | [REJECTED]     -- "REDUNDANT_VERIFICATION: scipy already tested and verified"
Turn  5:  3,145tok | bash_command    -- write first solution using scipy
Turn  6:  3,854tok | bash_command    -- eval -> passes basic tests
Turn  7:  4,260tok | [REJECTED]     -- "SHALLOW_EDIT: power iteration won't work reliably"
Turn  8:  5,114tok | bash_command    -- benchmarking scipy vs numpy timing
Turn  9:  6,008tok | [REJECTED]     -- "WASTEFUL_EXPLORATION: scipy already shown to be slower"
Turn 10:  6,826tok | bash_command    -- install numba for JIT optimization
Turn 13:  9,396tok | bash_command    -- write optimized solution with numpy
Turn 14: 10,132tok | bash_command    -- eval -> passes
Turn 20: 14,635tok | bash_command    -- final optimization
Turn 21: 15,915tok | bash_command    -- eval -> passes all tests
```

**Rejections that helped:**
1. Turn 4: Prevented redundant scipy verification (saved 1 turn)
2. Turn 7: Blocked a power iteration approach that "only works reliably for matrices with a dominant eigenvalue" -- this was correct technical guidance
3. Turn 9: Prevented further scipy benchmarking after it was already shown to be slower

**Diagnosis:** When the strict validator's domain knowledge was correct (blocking power iteration, preventing redundant verification), it saved the agent 3-5 turns and steered it toward the correct numpy-based solution. This is a case where strict validation worked as intended.

---

### Example 3: TOLERANT mode -- `portfolio-optimization` (PASS, 40 rejections)

**Path:** `<cluster_path>
**Result:** PASS | **Steps:** 78 | **Rejections:** 40

This task PASSED in tolerant but FAILED in strict.

#### Turn-by-turn (key moments):

```
Turn  5:  4,418tok | bash_command    -- write C optimization file
Turn  6:  6,213tok | [REJECTED]     -- "CONTRADICTED_PATH: heredoc was cut off mid-function, C file incomplete"
Turn  7:  6,951tok | bash_command    -- verify C file contents -> confirmed incomplete
Turn  9:  8,205tok | [REJECTED]     -- "PREMATURE_SUBMISSION: verify C file first"
Turn 13: 11,465tok | bash_command    -- run benchmark -> fails
Turn 15: 13,409tok | bash_command x2 -- rewrite C file completely
Turn 19: 16,707tok | bash_command    -- benchmark -> fails again
Turn 27: 22,317tok | bash_command x2 -- third C rewrite
Turn 33: 27,141tok | bash_command    -- benchmark -> runs but slow
Turn 34-51:         | 18 consecutive rejections (agent stuck in loop)
Turn 52: 30,363tok | bash_command x2 -- breaks out of loop with Ctrl-C
Turn 53: 31,522tok | bash_command x3 -- fourth C rewrite
Turn 58: 37,294tok | bash_command    -- benchmark -> passes!
Turn 59-73:         | more rejections but agent recovers
Turn 75: 42,493tok | bash_command    -- final verification passes
```

**Diagnosis:** The tolerant validator caught a real issue at turn 6 (incomplete C file) which was genuinely helpful. However, it also caused a dead zone at turns 34-51 with 18 consecutive rejections for unclear reasons (obs length always 307, suggesting a generic rejection). Despite this, the agent eventually broke out and submitted a working solution. In strict mode, the same task likely would have accumulated even more rejections and failed.

---

### Example 4: TOLERANT mode -- `merge-diff-arc-agi-task` (PASS, 7 rejections)

**Path:** `<cluster_path>
**Result:** PASS | **Steps:** 25 | **Rejections:** 7

#### Turn-by-turn:

```
Turn  1:  1,061tok | bash_command x4 -- mkdir repo, git init -> "git: command not found"
Turn  2:  3,233tok | bash_command    -- apt-get install git -> installed successfully
Turn  3:  7,620tok | [REJECTED]     -- "Exact duplicate of turn 0 (git init) which produced an error"
Turn  4:  7,923tok | [REJECTED]     -- same reason
Turn  5:  8,210tok | bash_command x3 -- which git -> found at /usr/bin/git
Turn  6:  8,482tok | [REJECTED]     -- "Exact duplicate of turn 0 which produced an error"
Turn  7:  8,772tok | bash_command x3 -- /usr/bin/git init -> SUCCESS
Turn  9:  9,409tok | bash_command x3 -- git fetch from bundle
Turn 10:  9,892tok | bash_command x4 -- git checkout, explore branches
Turn 18: 13,311tok | bash_command x2 -- git merge branch2
Turn 19: 13,746tok | bash_command x2 -- cat algo.py (see merge conflict)
Turn 20: 14,680tok | bash_command x3 -- resolve merge conflict, write solution
Turn 23: 16,830tok | no-tool         -- submit
```

**Rejections that helped:** The validator correctly blocked duplicate `git init` commands that would have failed (git wasn't on PATH). This forced the agent to use the full `/usr/bin/git` path at turn 7, which worked. The 7 rejections saved ~3-4 wasted turns.

**Rejections that were debatable:** Turns 3-4 and 6 rejected commands that would have failed, but the agent had already fixed the underlying issue (installed git in turn 2). The validator was checking against the original error from turn 0, not recognizing that `apt-get install git` had resolved the issue. However, the `git` binary needed full path reference since the shell hash wasn't updated, so the rejections accidentally steered the agent correctly.

#### Diagnosis:
A case where tolerant validation worked well -- it prevented clearly futile retries while allowing the agent enough freedom to explore and find the solution in 25 steps.

---

## Summary of Findings

### Curator (reserved_turns)

| Pattern | N=10 | N=50 | N=100 |
|---------|------|------|-------|
| Curator drops per task | ~15-17 | ~4-8 | ~3-12 (late) |
| Re-reading same files | Very frequent | Rare | Very rare |
| Memory of past fix attempts | Lost repeatedly | Preserved | Preserved but diluted |
| Primary failure mode | Sisyphean loops: build context, lose it, rebuild | -- | Attention dilution from bloated context |

**Key insight:** N=10 creates a destructive cycle where the agent builds understanding, loses it, and rebuilds. N=100 preserves too much (including failed attempts), diluting attention. N=50 strikes the balance: enough history for continuity, trimmed enough to stay focused.

### Validator (modes)

| Pattern | strict | tolerant | rules-only |
|---------|--------|----------|------------|
| Rejection cascades (>20 consecutive) | Very common | Occasional | Rare |
| False positive rejections | Frequent | Moderate | Minimal |
| Helpful rejections (saved turns) | Occasional | Common | N/A (no semantic checks) |
| Primary failure mode | Rejection cascades that burn all turns | Some wasted turns on borderline calls | Some wasted turns on bad commands |

**Key insight:** The strict validator's semantic checks (WASTEFUL_EXPLORATION, SHALLOW_EDIT) are often technically correct but operationally counterproductive. A single false rejection can trigger a cascade where every subsequent attempt is also rejected, consuming all remaining budget. The tolerant mode provides the best tradeoff: it catches genuinely broken commands (syntax errors, exact duplicates) while allowing the agent freedom to iterate. Rules-only works well when the agent is competent but lacks guardrails against truly wasteful exploration.
