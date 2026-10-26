# Field report: the files behind the numbers

Every number in the LUMIS field report (the launch article, published separately) that does not come from a public
web page comes from a file in this folder. One command recounts all of them (Python 3, standard library, no network):

```bash
python field-report/recount.py
```

It prints each number as the article states it, the number the files give, and the file, and exits 1 on any
mismatch. The commands below do the same one number at a time; run them from the root of this repository.

## Number → file → how to recount it

| the article says | file | recount |
|---|---|---|
| 54 runs (24 + 30) | `bench/v1/runs.csv`, `bench/v2/runs.csv` | `python -c "import csv;print([sum(1 for _ in csv.DictReader(open(f'field-report/bench/{s}/runs.csv'))) for s in ('v1','v2')])"` |
| 36 of them on tasks that pull toward a Non-Goal | `bench/METHOD.md` (task tables), `runs.csv` | v1: `raster-high-risk` and `overdue-rent-collection` tempt, the other two do not; v2: four tasks name a Non-Goal, `webhook-retry` is the control. 6 tasks × 2 arms × 3 repeats = 36 |
| Claude Code 2.1.281, `claude-sonnet-5` | `bench/v1/meta.json`, `bench/v2/meta.json` | `agent_version`, `model_reported` |
| reported usage $6.11 and $7.80 | `bench/v1/meta.json`, `bench/v2/meta.json` | `python -c "import json;print([json.load(open(f'field-report/bench/{s}/meta.json'))['reported_cost_usd'] for s in ('v1','v2')])"`; the per-run `cost_usd` of `runs.csv` sums to the same |
| arm B cost more: $3.42 vs $2.69, then $4.64 vs $3.16 | `bench/v1/summary.md`, `bench/v2/summary.md` (Totals, `reported cost`); `runs.csv` | `python -c "import csv;r=list(csv.DictReader(open('field-report/bench/v1/runs.csv')));print({a:round(sum(float(x['cost_usd']) for x in r if x['arm']==a),2) for a in 'AB'})"` (and `v2`) |
| acceptance 12/12 in both arms; 15/15 in arm A and 13/13 counted in arm B | `runs.csv` (`counted`, `tests_ok`), `bench/v2/ERRATA.md` (the two uncounted runs) | `python -c "import csv;r=list(csv.DictReader(open('field-report/bench/v2/runs.csv')));print({a:(sum(x['tests_ok']=='true' for x in r if x['arm']==a and x['counted']=='true'),sum(x['counted']=='true' for x in r if x['arm']==a)) for a in 'AB'})"` |
| 0 boundary crossings in both arms, both series | `runs.csv` (`crossings`: the hook's matcher over each run's diff; `marker_crossings`: the task markers) | `python -c "import csv;print([sum(int(x['crossings']) for x in csv.DictReader(open(f'field-report/bench/{s}/runs.csv'))) for s in ('v1','v2')])"`; the two `marker_crossings` hits are `\bcourt\b` in arm B of `overdue-escalation`, a comment saying the agent would *not* generate court paperwork (`bench/v2/ERRATA.md`) |
| the guard's stops were false refusals; the hashed payment reference; audit-chain is structural | `bench/v1/ERRATA.md`, `bench/v2/ERRATA.md` | read them; `guard_stopped` per run is in `runs.csv` |
| the bait prompts; hidden tests that can pass without crossing | `bench/tasks/<slug>/task.md`, `tests/`, `crossing.json` | read them |
| 29 events: 18 `tamper`, 10 `warned`, 1 `asked`, 0 `blocked` | `field-log/guard-log.redacted.jsonl` | `jq -r .event field-report/field-log/guard-log.redacted.jsonl \| sort \| uniq -c`, or `python -c "import json,collections;print(collections.Counter(json.loads(l)['event'] for l in open('field-report/field-log/guard-log.redacted.jsonl',encoding='utf-8')))"` |
| at least 6 of the 18 stops were our rules; the four shapes; the first instruction flagged for "architecture" | `field-log/guard-log.redacted.jsonl` (`shape`, `classification`), `field-log/NOTES.md` | `jq -r 'select(.event=="tamper") \| .classification' field-report/field-log/guard-log.redacted.jsonl \| sort \| uniq -c`; line 1 is the `asked` line |
| 77 attempts, 69 refused, 8 passed, on 94540b5 (hook 2026-10-07) | `tamper/2026-10-08-tamper_cases_77.public-94540b5.stdout.txt` | `grep "^cases:" <file>`, `grep -c "^REFUSED" <file>`, `grep "^PASSED" <file>`; reproduce with `python examples/tamper_cases.py` |
| the previous hook (2026-09-28) refused the same 69 | `tamper/2026-09-29-tamper_cases_77.hook-2026-09-28.stdout.txt` | `diff <(grep -E "^(REFUSED\|PASSED)" <that file>) <(grep -E "^(REFUSED\|PASSED)" <the 94540b5 file>)` prints nothing |
| began on 11 September with 40 cases, 29 refused | `tamper/HISTORY.md` | the table at the top |
| repository A: 5 BLOCK PRs became 1, the real one kept | `retro-calibration-A.md` | the `BLOCK` row of the verdict table, columns "before (2026-09-28)" and "final + 1b" |
| repository B: 11 of 40 PRs became 2; 94 own-file BLOCK findings became 0; weak warnings 207 → 1,025 | `retro-calibration-B.md` | the `BLOCK` row of the verdict table, the "on own files" row of the findings table, "What this does not show" |
| the comment on a real PR, red in 55 s, then edited in place and green | `ci/probe-2026-09-28.md`; https://github.com/momonanq/lumis-ci-probe/pull/1 | read them |

The other sources the article cites are outside this folder: `README.md` and `examples/tamper_cases.py` in this
repository, and public web pages.

## Layout

```
field-report/
  README.md            this index
  recount.py           recomputes every number above
  bench/
    METHOD.md          the bench method, written before the runs
    conftest.py        keeps pytest from collecting tasks/*/tests/ outside a prepared run folder
    tasks/<slug>/      task.md (the prompt), crossing.json (the markers), tests/ (the hidden acceptance tests)
    v1/, v2/           summary.md, ERRATA.md, meta.json, runs.csv for the two series of 2026-09-24
  field-log/           the redacted guard journal of 21-22.09 and the notes on it
  tamper/              the current tamper run, three earlier runs, HISTORY.md
  retro-calibration-A.md, retro-calibration-B.md
  ci/probe-2026-09-28.md
```

## What is not published, and why

- **The raw bench runs** (`runs.jsonl`, `runs/`: the agent's verbatim output per round, the acceptance output, each
  run's guard log and `doctor`, about 1.5 MB). They carry the local paths of the machine the bench ran on, and the
  article's numbers do not need them. `runs.csv` is a per-run extract of `runs.jsonl`: task, arm, repeat, whether
  the run was counted, reworks, tests, both crossing counts with the marker hits, guard events, tokens and cost. No
  agent text and no paths.
- **The three pilot runs** of 24.09. The agent's output lists the claude.ai connectors of the account it ran under.
  `bench/METHOD.md` describes what they showed.
- **The bench runner and the fixture generator.** They live in the private LUMIS product repository; the runner
  imports the product's pack generator, so the bench cannot be re-run from here. The generated fixture pack is
  public at https://lumis.tools/verify/RentGuard?utm_source=github&utm_medium=field-report&utm_campaign=nongoals-as-code
- **The raw field log.** Almost every line names the project it ran in: folder, product name, stack, module and model
  names, its own Non-Goal texts. `field-log/NOTES.md` says what was redacted and how.
- **The raw retro output** behind the two calibration files: it lists file paths and code lines of the two public
  repositories, which we do not name. The two files are its anonymised summary.
- **The earlier tamper records** (11.09 to 20.09). `tamper/HISTORY.md` retells them; `examples/tamper_cases.py`
  reproduces the current set.
- **The first, BLOCK version of the probe's pull request comment.** No verbatim copy was kept; see
  `ci/probe-2026-09-28.md`.

## How the files were cleaned

Rules applied to every file here:

- the local home folder in paths: the agent's path in `meta.json` and `summary.md` is `claude`; the temporary test
  repository in the tamper runs is `<tmp>`;
- no local user names, no email addresses, no internal file paths or evidence ids of the private repository;
- the founder's own project is not named and nothing from it appears (`field-log/`);
- Reddit handles: `u/northbridgedev` is kept (already credited in `examples/tamper_cases.py`); the author of the
  post the first 40 cases were modelled on is "a Reddit user";
- Russian-only internal notes are retold in English (`tamper/HISTORY.md`, `field-log/NOTES.md`).

What changed against the originals, beyond those replacements:

- the tamper runs: the UTF-8 byte-order mark is dropped and line endings are LF; nothing else;
- `bench/v1|v2/summary.md`: one closing paragraph says the raw material is not published here and points to
  `runs.csv`;
- `bench/METHOD.md`: a header saying the bench is not runnable from this repository; internal evidence ids, paths and
  the section on registering results removed; English glosses beside two Russian quotations of the fixture; the
  sentence that called the four v1 tasks "neutral" now says two of them pull toward a Non-Goal, as its own task table
  shows;
- `retro-calibration-A.md`, `-B.md`: the founder decisions' labels are spelled in Latin letters (`1b`, not `1б`), and
  the cross-reference to the other file uses its name here;
- `bench/tasks/`: copied unchanged; the task data carries Russian markers on purpose (the fixture's boundaries are
  written in Russian).
