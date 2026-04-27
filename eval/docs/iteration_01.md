# Iteration 01 Report — DHAv4 + Terminus2

## Config
- Base agent: terminus-2 (subclassed)
- Harness: DHAv4 (rule-based input curator + rule-based output validator)
- Model: GLM-4.7-Flash served via SGLang (port 8054)
- Benchmark: terminal-bench@2.0 (89 tasks, 88 completed for DHAv4)
- Date: 2026-04-09 / 2026-04-10
- Temperature: 0.5
- Concurrent trials: 4
- Note: Run was concurrent with another harbor job (dhv3cc) on the same SGLang endpoint, contributing to wall-clock timeouts

## DHAv4 Design (after iter01 fixes)

### Input Curator — rule-based message trimming
- Triggered when `len(chat.messages) > 16`
- Trims old verbose user messages (terminal outputs) in-place: replaces them with a short placeholder like `[terminal output trimmed, 8421 chars; started with: ...]`
- Preserves: system message, last 8 messages, all assistant turns, any message containing "error/traceback/failed/exception"
- Also trims current observation if `len > 12000`: keeps first 4k + last 6k chars
- LLM advisor only fires when stuck (≥3 identical observation hashes) AND turn ≥15 — never triggered in this run

### Output Validator — rule-based duplicate detection
- Rule 1: all-trivial commands (ls, pwd, echo, etc.) → PASS
- Rule 2: any heredoc or multi-line script → PASS
- Rule 3: any write command (`>`, `tee`, `mv`, `cp`, `pip install`, `gcc`, etc.) → PASS
- Rule 4: exact same command 3+ consecutive runs with no write between → REJECT
- Rule 5: default → PASS
- No LLM validation in this iteration (removed due to false positives in iter01 prototype)

## Results

| Metric | Terminus-2 baseline | DHAv4 | Delta |
|---|---|---|---|
| **Pass rate** | 11/89 (12.4%) | **17/88 (19.3%)** | **+6 tasks** |
| **Total tokens** | 139,324,051 | 45,303,212 | **−67.5%** |
| **Generator input tokens** | 137,038,992 | 44,078,807 | −67.8% |
| **Generator output tokens** | 2,285,059 | 1,224,405 | −46.4% |
| **Avg episodes per task** | 41.9 | 27.2 | −35.1% |
| **Harness tokens** | n/a | 0 | curator/validator are pure rule-based |

**Both success criteria met:**
- ✓ Beats baseline by ≥5 tasks (+6)
- ✓ Generator token usage with DHAv4 lower than baseline total tokens (−67.5%)
- ✓ Harness overhead < 20% of baseline total tokens (0%, no LLM calls in harness)

## New Wins (DHAv4 passed, baseline failed) — 12 tasks
- cancel-async-tasks, cobol-modernization, code-from-image, crack-7z-hash, extract-elf, fix-code-vulnerability, headless-terminal, mcmc-sampling-stan, openssl-selfsigned-cert, portfolio-optimization, pypi-server, vulnerable-secret

## Regressions (baseline passed, DHAv4 failed) — 6 tasks
- build-pmars, distribution-search, git-leak-recovery, log-summary-date-ranges, merge-diff-arc-agi-task, prove-plus-comm

Of these, build-pmars and distribution-search hit AgentTimeoutError (likely SGLang load contention rather than DHAv4 logic). Net delta of +6 = 12 wins − 6 losses.

## Top failure pattern: AgentTimeoutError
42 of 88 tasks errored out with AgentTimeoutError. Median episodes-at-timeout was 33; some tasks hit timeout at only 2-3 episodes (LLM call wall time was the culprit, not episode count). Root cause is likely concurrent SGLang load — the dhv3cc experiment was running on the same endpoint with 4 workers throughout the run.

## Token Reduction Mechanism
The trim_old_observations function delivers most of the savings. Examples:
- schemelike-metacircular-eval: 21.4M → 4.8M tokens (78% reduction), episodes 184→70
- fix-ocaml-gc: 16.6M → 3.5M (79%), episodes 233→115
- regex-chess: 4.0M → 0.14M (97%), episodes 70→10

The huge per-task reductions on long-running tasks come from the geometric blow-up in baseline Terminus2: every turn re-sends the full conversation history including all prior terminal outputs. By trimming old verbose user messages mid-history, DHAv4 keeps the per-turn prompt size roughly bounded.

## Issues to fix in next iteration

1. **AgentTimeoutError accounts for 47% of failures.** This is partly server load, but it also shows DHAv4 is not aggressive enough about preventing slow tasks from running too long. Possible fixes:
   - Add a stuck detector that aborts if 5+ turns produce identical-looking output
   - Add a maximum-episode soft cap (e.g. 50) with a "wrap up and submit" prompt
2. **Curator is too passive.** It only does rule-based trimming. For very long tasks, an LLM-based summary would compress better than truncation. But the cost has to be justified by reducing more tokens than the summary itself uses.
3. **6 regressions.** Some tasks the baseline solved were lost. For non-timeout regressions, the most likely cause is that the trimmed history removed information the model later needed. Investigation needed: do the regressions correlate with high-trim turns?

## Next steps (per user direction)

Both iteration_01 success criteria met (+6 tasks, lower tokens). Per the user's instruction, next phase is **direction C**: build a harness-agnostic middleware so DHAv4 can wrap claude-code, terminus-kira, mini-swe, openhands. The middleware needs to intercept LLM calls (likely via litellm hook or wrapper) so the same curator/validator logic can be applied without subclassing each agent.
