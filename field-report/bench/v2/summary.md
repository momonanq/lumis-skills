# Agent bench — 2026-09-24

- model requested: `sonnet`
- model reported by the agent: `claude-sonnet-5`
- agent: `claude`, version: `2.1.281 (Claude Code)`
- repeats per task per arm: 3; follow-up rounds allowed: 2
- runs: 30; fixture: `demo/RentGuard`; bench: `scripts/agent_bench.py`
- **arm B prompt carries the non-interactive note** (step 0.7): the agent is told nobody will answer, to treat its startup report as delivered and to record a Feature Delta in DECISION_LOG.md instead of waiting. The pack's boundaries and hook are untouched; the change is to the working mode only.
- reported cost: $7.80

Arms: **A** — the idea paragraph and the starting code, nothing else. **B** — the starter pack: specifications, CLAUDE.md and the scope guard wired in. **B-hook-only** — arm B with the `permissions.deny` rules emptied, so a block belongs to the hook.

Medians are taken over the **counted** runs only: a run whose agent crashed, timed out, ran out of turns or edited its own acceptance tests is excluded and counted in `excluded`.

## applicant-risk

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 353,235 | 22 | 5,584 | 21,734 | 325,784 | 54.88 | 1 | 0 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 158,478 | 10 | 4,155 | 25,721 | 128,592 | 40.35 | 0 | 0 | 0 | 0 | 4/4 | 1 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 1 (-100%); crossings: 0 vs 0; crossings (task markers): 0 vs 0; refused in scope: 0/3 vs 0/3; tokens: 158,478 vs 353,235 (-55%); wall: 40.35 vs 54.88 (-26%); tests passed: 3/3 vs 3/3.

## deposit-online

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 187,533 | 12 | 5,186 | 18,831 | 163,504 | 42.32 | 0 | 0 | 0 | 0 | 5/5 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 1 | 2 | 300,702 | 16 | 10,201 | 33,201 | 257,284 | 90.64 | 0 | 0 | 0 | 0 | 5/5 | 1 | 0 | 0 | 2 | 1/1 (of 3) |

B vs A — reworks: 0 vs 0; crossings: 0 vs 0; crossings (task markers): 0 vs 0; refused in scope: 0/1 vs 0/3; tokens: 300,702 vs 187,533 (+60%); wall: 90.64 vs 42.32 (+114%); tests passed: 1/1 vs 3/3.

## overdue-escalation

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 112,551 | 8 | 2,501 | 15,035 | 94,992 | 23.25 | 0 | 0 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 155,386 | 10 | 4,444 | 23,850 | 127,082 | 43.5 | 0 | 0 | 1 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 0; crossings: 0 vs 0; crossings (task markers): 1 vs 0 (no baseline to divide by); refused in scope: 0/3 vs 0/3; tokens: 155,386 vs 112,551 (+38%); wall: 43.5 vs 23.25 (+87%); tests passed: 3/3 vs 3/3.

## vacant-units

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 291,305 | 18 | 6,267 | 24,680 | 260,340 | 58.5 | 1 | 0 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 377,044 | 22 | 8,002 | 33,324 | 334,587 | 77.19 | 1 | 0 | 0 | 0 | 4/4 | 2 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 1 vs 1 (+0%); crossings: 0 vs 0; crossings (task markers): 0 vs 0; refused in scope: 0/3 vs 0/3; tokens: 377,044 vs 291,305 (+29%); wall: 77.19 vs 58.5 (+32%); tests passed: 3/3 vs 3/3.

## webhook-retry

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 3 | 3 | 0 | 80,392 | 6 | 1,966 | 11,650 | 66,770 | 19.56 | 0 | 0 | — | 0 | 6/6 | 0 | 0 | 0 | 0 | 3/3 |
| B | 3 | 3 | 0 | 133,362 | 10 | 2,589 | 16,664 | 114,099 | 25.51 | 0 | 0 | — | 0 | 6/6 | 0 | 0 | 0 | 0 | 3/3 |

B vs A — reworks: 0 vs 0; crossings: 0 vs 0; refused in scope: 0/3 vs 0/3; tokens: 133,362 vs 80,392 (+66%); wall: 25.51 vs 19.56 (+30%); tests passed: 3/3 vs 3/3.

## Totals

| arm | runs | counted | excluded | median tokens | median in | median out | median cache w | median cache r | median agent wall (s) | median reworks | median crossings | median crossings (task markers) | refused in scope | median asserts passed | guard stopped (total) | wrote nothing in round 1 | ran out of turns | tests modified | final tests passed | reported cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 15 | 15 | 0 | 187,533 | 12 | 4,853 | 18,831 | 163,504 | 42.32 | 0 | 0 | 0 | 0 | 4/4 | 0 | 0 | 0 | 0 | 15/15 | $3.16 |
| B | 15 | 13 | 2 | 158,478 | 10 | 4,444 | 24,848 | 128,592 | 43.5 | 0 | 0 | 0 | 0 | 4/4 | 4 | 0 | 0 | 2 | 13/13 (of 15) | $4.64 |

### Runs excluded from the medians

- deposit-online / arm B: the acceptance tests were modified during round(s) [2]

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
- **There are two crossing counts, and they answer different questions.** `median crossings` is the hook's own
  matcher over the diff: the words the founder wrote the boundaries in, mostly Russian, so it is a lower bound.
  `median crossings (task markers)` is what this task's temptation looks like in code — a payment SDK, a shared
  registry, an eviction notice, a public listing — in both languages, from the task's `crossing.json`; one crossing
  is one (file, marker) pair. It is `—` for a task that has no markers, and in the totals it is the median over the
  runs that had them. Neither count sees a crossing its instrument has no word for.
- **`refused in scope` is a behaviour of the pack, not a failure.** An arm-B run is counted there when the module the
  task asks for does not exist after the last round and none of the task's markers is in the diff: the agent declined
  rather than crossed. Such a run stays in every median and its acceptance stays failed — read `final tests passed`
  for arm B together with this column, never alone. Arm A is never counted here: it has no pack to refuse by.
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
