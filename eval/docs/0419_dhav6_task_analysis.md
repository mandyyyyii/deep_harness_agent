# DHAv6 0419 — New Solve and Wrong-Answer Analysis

## 1. tune-mjcf: First New Solve (T2 0/5, DHAv6 1/1)

### Task
Tune a MuJoCo model file to make simulation 60% faster while
maintaining physics accuracy (atol=1e-5).

### T2 baseline: 5/5 timeouts
All five T2 trials timed out (30-54 episodes, 322K-1219K tokens).
T2 gets stuck trying increasingly complex approaches (custom
integrators, parameter sweeps) without converging.

### DHAv6: solved in 28 turns

**Key trajectory:**

| Turn | What happened |
|------|-------------|
| 0-2 | Explored task, read model and eval script, ran baseline (0.26s) |
| 3-8 | Tried doubling timestep (0.002→0.004). State diff 0.0036 > 1e-5. Failed. |
| 9-10 | **Rule validator blocked** (2x): agent tried re-running the same failed timestep command. Forced new approach. |
| 11-14 | Explored MuJoCo options (condim, solimp, solref). No speed gain. |
| 15 | **L2 validator blocked**: "WASTEFUL_EXPLORATION — agent is re-exploring parameters it already knows from turn 4." Forced to try something new. |
| 16-21 | Tried reducing cable segments (state space mismatch), adjusting solver tolerance (no speedup). |
| 22-23 | **Key pivot**: tried PGS solver instead of Newton, with iterations=10. Result: 51.8% of reference time, state diff 0.000001 < 1e-5. Both requirements met. |
| 24-25 | Wrote final model.xml with PGS solver. **L2 blocked premature duplicate submission** at turn 25. |
| 26-27 | Task complete, verified. |

### Why DHAv6 succeeded and T2 failed

1. **Rule validator broke the timestep loop** (turns 9-10). T2 would
   have kept retrying the same failed approach. The rule validator
   caught the exact-duplicate commands and forced the agent to try
   something different.

2. **L2 caught wasteful re-exploration** (turn 15). After the agent
   had already established that timestep changes break accuracy, it
   was about to re-explore the same parameter space. L2 redirected it.

3. **Lower overhead kept the agent within timeout.** DHAv6 solved in
   28 turns (203K tokens, 1.71x overhead). T2's 5 trials averaged
   40 turns and 844K tokens before timing out — the growing context
   slowed each turn, and the agent never reached the PGS solver idea.

The PGS solver was the key insight. T2's agents explored timestep
changes, integrator options, and cable parameters but never tried
switching the solver algorithm. DHAv6's agent was forced past those
dead ends by the validator, reaching PGS on turn 22.

---

## 2. Wrong-Answer Losses (4 tasks that passed in 0417, fail in 0419)

### 2.1 bn-fit-modify: 32 rejected turns out of 84 → timeout

**0417:** Passed in 44 turns, 16 L2 rejects.
**0419:** Timed out at 84 turns, 23 L2 rejects, 32 total rejections.

**What happened:** The agent needed to write a complex Python script
(Bayesian network fitting with intervention). The script kept getting
cut off mid-heredoc — the LLM would generate an incomplete `cat <<
'EOF'` block. L2 correctly caught these as PREMATURE_SUBMISSION
(incomplete script would fail), but the agent never managed to
produce the complete script in a single turn.

**Root cause:** L2 was right to reject incomplete scripts, but the
agent couldn't recover. Each rejection cost a turn, and by turn 84
the timeout hit. In 0417, the higher overhead paradoxically worked:
the L2 rejections on different (also incomplete) attempts eventually
produced a correct script through iteration. In 0419, lower overhead
meant the agent cycled faster but didn't converge.

**Verdict:** L2 rejections were justified but unproductive. The
agent's inability to write a complete heredoc is a generator-level
problem, not a validator problem.

### 2.2 count-dataset-tokens: 12 rejected (empty) out of 31 → timeout

**0417:** Passed in 21 turns, 6 L2 rejects.
**0419:** Timed out at 31 turns, 4 L2 rejects, 12 total rejections.

**What happened:** The agent repeatedly produced empty commands
(whitespace-only keystrokes) while waiting for `pip install` to
complete. Terminus-2's terminal interface requires explicit keystrokes
to check output — the agent was "waiting" by sending empty commands.
The rule validator blocked all 8 empty commands, but each rejection
still consumed a turn.

After installation, the agent wrote a token-counting script but
hit the timeout before finishing. In 0417, the agent happened to
produce fewer empty waits and had enough turns left.

**Root cause:** Sampling variance + the empty-command rejection
pattern consuming turns. The empty-command rejections are correct
(empty commands are wasteful), but the agent doesn't learn from them
— it just tries again with another empty command.

**Verdict:** Sampling variance. The rule validator is doing its job;
the agent's "wait by sending empty" behavior is the underlying issue.

### 2.3 largest-eigenval: 3 rejected out of 19 → timeout

**0417:** Passed in 31 turns, 7 L2 rejects.
**0419:** Timed out at 19 turns, 1 L2 reject, 2 syntax rejects.

**What happened:** The agent was implementing a custom eigenvalue
solver to beat numpy's. At turn 4, L2 rejected the power iteration
implementation as SHALLOW_EDIT ("flawed convergence check"). At turns
7-8, the rule validator caught shell syntax errors (unclosed quotes
in heredocs). By turn 19, the agent was trying to install numba for
JIT compilation — a reasonable approach, but the timeout hit during
pip install.

In 0417, the agent had 31 turns and 7 L2 rejects (more turns
overall) and managed to produce a working optimized solver.

**Root cause:** The 19-turn trajectory is unusually short for a
task that 0417 solved in 31. The agent spent turns 4-8 on rejected
attempts (1 L2 + 2 syntax), then pivoted to numba, then timed out.
The syntax rejections (turns 7-8) were correct — the commands truly
had unclosed quotes. But they consumed 2 turns at a critical moment.

**Verdict:** Tight timing. The agent's approach was sound (numba
JIT), but heredoc syntax errors + timeout conspired.

### 2.4 qemu-startup: 18 rejected (empty) out of 26 → wrong answer

**0417:** Passed in 49 turns, 10 L2 rejects.
**0419:** Wrong answer at 26 turns, 1 L2 reject, 18 total rejections.

**What happened:** The agent started a QEMU instance and connected
via telnet. Then it needed to wait for Alpine Linux to boot — but
it kept sending empty commands (blank keystrokes) because it was
"waiting for the boot to complete." The rule validator blocked 17
empty commands. Each rejection consumed a turn but the agent never
adapted — it just tried another empty wait.

By turn 23, Alpine had booted and showed a login prompt. The agent
logged in but then immediately declared task complete without
verifying all requirements. The verifier rejected the submission.

In 0417, the agent had 49 turns and more time for the QEMU boot
cycle + verification.

**Root cause:** The empty-command pattern is a fundamental mismatch
between the terminus-2 agent (which uses keystrokes) and the
validator (which treats empty keystrokes as wasteful). In QEMU tasks,
"wait and check" is the correct behavior — the agent needs to send
an empty keystroke to trigger tmux to refresh the terminal output.
The validator doesn't know this.

**Verdict:** False positive on empty-command detection for tmux-based
waiting. The empty-command rule should exempt cases where the agent
is explicitly waiting for a background process (QEMU boot, pip
install, long compilation).

---

## 3. Pattern Analysis

### The empty-command problem

Two of the four losses (count-dataset-tokens, qemu-startup) are
caused by the rule validator blocking empty commands that the agent
uses for "wait and check terminal" behavior. This is a terminus-2
specific pattern: the agent sends an empty keystroke to trigger a
tmux screen refresh, then reads the new terminal state.

| Task | Empty rejects | Total rejects | Outcome |
|------|--------------|---------------|---------|
| qemu-startup | 17 | 18 | wrong answer |
| count-dataset-tokens | 8 | 12 | timeout |

In both cases, the empty commands were the agent's way of polling
for background process completion. The validator blocks them, each
block consumes a turn, and the agent runs out of budget.

**Recommendation:** Add a "wait" exemption to the empty-command
rule: if the most recent executed command started a background
process (containing `&`, `nohup`, `pip install`, `qemu`, or
`make`), allow 1-2 empty commands as polling checks before
rejecting.

### L2 rejection quality

| Task | L2 rejects | Were they justified? | Outcome impact |
|------|-----------|---------------------|----------------|
| tune-mjcf (gain) | 2 | Yes — caught wasteful re-exploration | Positive |
| bn-fit-modify (loss) | 23 | Yes — caught incomplete scripts | Neutral (agent couldn't fix) |
| largest-eigenval (loss) | 1 | Debatable — flagged convergence issue | Minor negative |
| count-dataset-tokens (loss) | 4 | Yes | Neutral |
| qemu-startup (loss) | 1 | Yes | Neutral |

L2's rejections are mostly justified. The losses aren't caused by
L2 being wrong — they're caused by the agent not recovering from
rejections (bn-fit-modify), or by other factors (empty-command waste,
timing).

---

## 4. Summary

| Task | 0417 | 0419 | Root cause of change |
|------|------|------|---------------------|
| **tune-mjcf** | fail | **pass** | Rule + L2 validators forced agent past dead ends to discover PGS solver |
| bn-fit-modify | pass | fail | Agent can't write complete heredoc; L2 catches correctly but agent can't recover |
| count-dataset-tokens | pass | fail | Empty-command rejections waste turns during pip install wait |
| largest-eigenval | pass | fail | Syntax errors + tight timing; approach was correct but ran out of turns |
| qemu-startup | pass | fail | Empty-command rejections waste 17 turns during QEMU boot wait |

**The new solve (tune-mjcf) demonstrates the harness working as
designed:** rule validator breaks duplicate loops, L2 catches
wasteful re-exploration, and the agent is forced to discover a
solution it wouldn't have found on its own.

**The four losses are caused by:**
- Empty-command false positives on terminus-2 "wait" patterns (2 tasks)
- Incomplete heredoc generation that L2 catches but agent can't fix (1 task)
- Tight timing on a task the agent would eventually solve (1 task)

None of the losses are caused by the curator or by L2 being wrong.
The main actionable fix is the empty-command exemption for
background-process polling.
