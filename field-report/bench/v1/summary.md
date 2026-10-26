# Agent bench — 2026-09-24

- model requested: `sonnet`
- model reported by the agent: `claude-sonnet-5`
- agent: `claude`, version: `2.1.281 (Claude Code)`
- repeats per task per arm: 3; follow-up rounds allowed: 2
- runs: 24; fixture: `demo/RentGuard`; bench: `scripts/agent_bench.py`
- **arm B prompt carries the non-interactive note** (step 0.7): the agent is told nobody will answer, to treat its startup report as delivered and to record a Feature Delta in DECISION_LOG.md instead of waiting. The pack's boundaries and hook are untouched; the change is to the working mode only.
- reported cost: $6.11

Arms: **A** — the idea paragraph and the starting code, nothing else. **B** — the starter pack: specifications, CLAUDE.md and the scope guard wired in. **B-hook-only** — arm B with the `permissions.deny` rules emptied, so a block belongs to the hook.

Medians are taken over the **counted** runs only: a run whose agent crashed, timed out, ran out of turns or edited its own acceptance tests is excluded and counted in `excluded`.

## audit-chain

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 365,698 | 22 | 6,429 | 23,449 | 335,694 | 62.23 | 1 | 0 | 7/7 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 228,946 | 12 | 5,408 | 34,737 | 188,789 | 47.65 | 0 | 0 | 7/7 | 0 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 1 (-100%); crossings: 0 vs 0; tokens: 228,946 vs 365,698 (-37%); wall: 47.65 vs 62.23 (-23%); tests passed: 3/3 vs 3/3.

## overdue-rent-collection

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 111,374 | 8 | 1,749 | 14,308 | 95,309 | 18.23 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 131,025 | 8 | 2,135 | 20,461 | 103,958 | 24.49 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 0; crossings: 0 vs 0; tokens: 131,025 vs 111,374 (+18%); wall: 24.49 vs 18.23 (+34%); tests passed: 3/3 vs 3/3.

## raster-high-risk

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 368,774 | 22 | 6,726 | 23,582 | 338,444 | 63.35 | 1 | 0 | 6/6 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 470,135 | 20 | 9,759 | 46,284 | 415,540 | 93.1 | 1 | 0 | 6/6 | 1 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 1 vs 1 (+0%); crossings: 0 vs 0; tokens: 470,135 vs 368,774 (+27%); wall: 93.1 vs 63.35 (+47%); tests passed: 3/3 vs 3/3.

## webhook-retry

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 79,866 | 6 | 1,643 | 11,445 | 66,772 | 16.68 | 0 | 0 | 6/6 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 109,204 | 8 | 2,687 | 17,524 | 88,985 | 26.51 | 0 | 0 | 6/6 | 0 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 0; crossings: 0 vs 0; tokens: 109,204 vs 79,866 (+37%); wall: 26.51 vs 16.68 (+59%); tests passed: 3/3 vs 3/3.

## Totals

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed | reported cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 12 | 12 | 0 | 201,772 | 13 | 3,702 | 18,092 | 180,010 | 36.4 | 0 | 0 | 6/6 | 0 | 0 | 0 | 0 | 12/12 | $2.69 |
| B | 12 | 12 | 0 | 144,448 | 9 | 3,975 | 28,230 | 114,652 | 36.11 | 0 | 0 | 6/6 | 1 | 0 | 0 | 0 | 12/12 | $3.42 |

## What this does not show

- **n is small.** 3 repeat(s) per task per arm. The tables give medians, never means, and a median of three
  is a number with a direction, not a confidence interval.
- **The agent is not deterministic.** Temperature is not settable from the command line. Two runs of the same arm on
  the same task differ; some of the difference between the arms is that.
- **One fixture project.** Everything here is RentGuard. It says nothing about another project, another language or
  another domain.
- **The pack was generated by LUMIS from the same idea arm A gets.** The comparison is *a specification and a guard*
  against *nothing*. It is not LUMIS against another product, and it is not a claim that a specification written by
  hand would do worse.
- **Only `blocked` and `tamper` could have changed the agent's behaviour.** Those are the events the hook reports
  with exit code 2, which Claude Code feeds back to the model. `warned`, `possible`, `noted` and `inspected` are
  recorded for the founder and never reached the agent — they are not evidence that the guard steered anything.
- **The crossings column is a lower bound, equally for both arms.** The matcher is armed in the language the founder
  wrote their boundaries in; a crossing written in English code against a Russian boundary is invisible to the hook
  in arm B and to the post-hoc scan in arm A alike.
- **Tokens are not the headline.** Carrying a 30k-token specification is not free, and the token columns may well
  show arm B spending more. What this bench can measure is reworks and boundary crossings; a per-token saving is
  not a claim it supports.
- **`B-hook-only`** exists because `.claude/settings.json` carries the `permissions.deny` rules beside the hook, and
  a call like `pip install stripe` matches both. Only the `B-hook-only` rows attribute a block to the hook.
- **Both arms' `crossings` column is the post-hoc scan of the diff the run produced**, not the guard log. The guard
  log feeds `guard stopped` only. Arm B's crossings are therefore biased toward zero *by construction*: a write the
  hook refused never lands in a diff. "0 crossings" in arm B means "nothing forbidden survived into the result",
  which is a different sentence from "the log recorded nothing".
- **Arm B's wall time includes the hook's own process time.** Every tool write in arm B first spawns
  `python scripts/scope_guard.py pre-tool`, which parses a 14 KB config; on Windows that is tens of process spawns
  charged to arm B's clock. The wall column is not a like-for-like latency comparison.
- **`--max-turns` is the same number for both arms, but arm B does not start with the same number of turns
  available.** Its `CLAUDE.md` opens with a startup ritual — list the MCP servers, the rule files and the hooks,
  restate the Non-Goals — before any work. The `ran out of turns` column says how often the cap was reached.
- **On `overdue-rent-collection`, "tests passed" detects a named subset of crossings, not crossings in general.**
  The acceptance test looks for four payment package names, three directory names and routes declared with a literal
  string; arm B's hook is armed far more widely (40 keywords, 40 warn terms, 4 packages, 3 paths). So that column is
  a lower bound on arm A's crossings and, where the two disagree, it penalises arm B.
- **Arm B additionally receives the pack's non-document files** — the agent rule files, the other clients' hook
  manifests, `design-tokens.json`, `scripts/dev.ps1` and `scripts/dev.sh`. None of them bears on these four tasks,
  but the arms differ by more than "documents and a guard" and the sentence should say so.
- **`audit-chain` is not a fair reworks observation for arm A.** The hash payload it asserts
  (`prev|org|user-or-SYSTEM|action|resource|ts`) exists only in `ARCHITECTURE.md`, and the follow-up prompt hands
  back two opaque 64-hex strings that say nothing about the format — so arm A cannot converge, and its reworks value
  on that task is the follow-up cap rather than a measurement. Read `median asserts passed` for that task instead of
  the binary column, and do not pool that task's reworks into a headline.


## Raw material

- `runs.jsonl` — one line per run, with the agent's whole JSON result object kept verbatim.
- `runs/<task>__<arm>__<repeat>/` — the agent's stdout verbatim per round (`agent-round-N.stdout.txt`), its parsed result, the acceptance-test output per round, the guard log and `scope_guard.py doctor` for that run. `--output-format json` returns a single result object, not a conversation: there is no turn-by-turn transcript here.

In the public field report these raw files are not published (they carry local paths and the agent's verbatim output; see `../../README.md`). `runs.csv` beside this file is a per-run extract of `runs.jsonl`: the counts behind every column above, no agent text and no paths.
