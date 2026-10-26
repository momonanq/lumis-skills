# Retro calibration, repository B (anonymised)

Run 2026-09-29 by the engineering session, founder decision 10a: both calibration retros re-run on the final hook of
branch `gtm-rework`, before and after, on the same pull requests and the same Non-Goals as the GTM run of 29.09.
Re-run the same evening on the final hook with founder decision 1b (the code-homonym list extended): the column
"final + 1b" below; the "after" column is kept as it was measured. Re-run on 2026-09-30 on hook 2026-09-30 (the
package matcher and the shared lexicon): the column "hook 2026-09-30"; the earlier columns are kept as measured.

Anonymised: no owner or repository name, no pull request number or title, no file path, no code line. A pull request
is named by its position in the list (1 = the newest merge). A line is described by its kind (code, comment) and the
kind of file it sits in. "Own files" are the project's files; "vendored" files are third-party code committed under
its `vendor/` directory.

## What was run

- **Repository B**: a public Go repository that vendors its dependencies, with a CLAUDE.md.
- **Pull requests**: the last 40 merged pull requests, the list the GTM run of 29.09 saved (`gh pr list --json` shape;
  the file is not in this repository). All 40 were merged into the default branch, so the new `--base` default of
  `scripts/retro_report.py` left none out (`left_out: {}` in both runs). Three of them are rebase merges, of which only
  the last commit is read (the report says so for each).
- **Non-Goals**: the five lines of that run, our reading of the repository's CLAUDE.md, unchanged:
  - NG-1: never use `goto`;
  - NG-2: never use a formatted print function for logging (the Non-Goal writes the function as code);
  - NG-3: no persistent connection pool;
  - NG-4: never modify generated mocks by hand;
  - NG-5: never run the formatter on the vendor directory.
- **Tool**: `scripts/retro_report.py` of the tools commit on `gtm-rework` (the same file for both runs), with
  `--prs-json`, `--clone` (a local partial clone from the 29.09 run; objects it lacked would be fetched from the public
  repository without a token) and `--json`. It runs the hook's `check-diff` once per pull request, locally and
  read-only. No model, no gh call, no token.
- **Before**: `scope_guard.py` and `lumis_guard.py` of commit 3dbf752, `HOOK_VERSION = "2026-09-28"` (sha256 of the
  hook `a928329614ecaf0791e6332c04371a148be592ef39ba863f5ebfd3782cc7e4f4`).
- **After**: the same two files at `gtm-rework` c92bd4d (hook rework fe98526 included), `HOOK_VERSION = "2026-09-29"`
  (sha256 `dc90e35fd8d0b99d1f8ca8eaffec98f8c7379f6874bd76a127b2e32839f3401b`).
- **Final + 1b**: the same hook with `CODE_HOMONYMS` extended by decision 1b (`connection(s)`, `pool(s)`,
  `generated`, `generate`, `modify`, `modified`, `manually`, `manual`, `persistent`, `mock(s)`), nothing else changed
  (sha256 `64ae54b1439d7bf7cbb0f2a22a4cb439191b56eb79af7c670c4bd5a57c068460`, `HOOK_VERSION` still `"2026-09-29"`),
  the same `retro_report.py`, the same pull request list and Non-Goals, the same local partial clone (as before, a
  blob it lacked would be fetched from the public repository without a token).
- **First cut** (reference only, not re-run): the 29.09 run on the first cut of hook 2026-09-29 (95ad8d6), read from
  its saved JSON. That run is the source of the table in docs/BOUNDARY_CHECK_CI.md, "Precision".
- **Hook 2026-09-30** (run 2026-09-30 by the engineering session): `scope_guard.py` and `lumis_guard.py` of branch
  `hook-pkg-match` after the review fixes (`HOOK_VERSION = "2026-09-30"`, sha256 of the hook `eff7b1d02a0f386001e40342649aafb305d5bf089d370c348c805afde477e179`), the same
  `retro_report.py` as final + 1b, the same pull request list, Non-Goals and local partial clone, no token.

## Verdicts per pull request (the report's verdicts)

| verdict | before (2026-09-28) | after (final 2026-09-29) | final + 1b | first cut (reference) | hook 2026-09-30 |
|---|---|---|---|---|---|
| BLOCK | 11 | 8 | 2 | 2 | 2 |
| WARN | 7 | 10 | 12 | 12 | 12 |
| PASS | 22 | 22 | 24 | 24 | 24 |
| INCOMPLETE | 0 | 0 | 2 | 2 | 2 |
| skipped / error | 0 | 0 | 0 | 0 | 0 |

The checker's own verdicts are the same as the report's in all five runs (the two findings in generated files, both
in a checksum file, do not change a verdict).

## BLOCK findings

| | before | after | final + 1b | first cut | hook 2026-09-30 |
|---|---|---|---|---|---|
| BLOCK findings | 853 | 324 | 11 | 11 | 11 |
| on own files | 94 | 74 | 0 | 0 | 0 |
| on vendored files | 759 | 250 | 11 | 11 | 11 |
| BLOCK pull requests with a BLOCK on an own file | 6 | 4 | 0 | 0 | 0 |

Where the 74 own-file BLOCK findings of the final hook (the "after" column) sit; on final + 1b every one of them is a
possible match (WARN), none blocks:

| pull request | findings | what the lines are |
|---|---|---|
| 36 of 40 | 69 | 68 lines of code of a regenerated mock file (package and type names carry the word `mocks`), 1 code-generation directive line naming the mocks (a tool directive counts as code) |
| 5 of 40 | 1 | a module requirement in the Go module file whose name contains `connections` (a dependency bump) |
| 17 of 40 | 2 | lines of code whose trailing comment mentions a connection (a trailing comment counts as code) |
| 39 of 40 | 2 | a header line of a man page written by a document converter (its comment marker is not one the checker knows), a task name in a test fixture containing the word `modify` |

None of them is judged a real crossing of the Non-Goals: the checker cannot tell a regenerated mock from a hand edit,
and the rest are ordinary words.

On vendored files the final hook still blocks: the word `connection` or `pool` on lines of third-party code (NG-3),
`generated` in comment lines of assembly files and in license texts (the checker knows no comment marker for those
files), `goto` in two vendored libraries (NG-1, also on the first cut) and the print function in a vendored linter
configuration (NG-2, also on the first cut). On final + 1b the 11 vendored BLOCK findings left are those of the first
cut: `goto` in two vendored libraries (4), the print function in the vendored linter configuration (1) and the phrase
"connection pool" in an identifier of vendored third-party code (6).

## Why the final hook differs from the first cut

Founder decision 1a (29.09): a word of a short Non-Goal blocks again unless it is on the curated list of code
homonyms. NG-3 and NG-4 are short Non-Goals (at most four words once the negation is removed, `SHORT_BOUNDARY_WORDS`), and `persistent`, `connection`, `pool`, `modify`, `generated`, `mocks`, `manually` are not on that list. On the
first cut they only warned. The derivation of the final hook for NG-3 and NG-4 is the same as before (2026-09-28);
what still differs from 2026-09-28 is the line reading: a comment line of a code file is noted, not blocked.

| pull request | before | after | final + 1b | first cut | why |
|---|---|---|---|---|---|
| 4 of 40 | BLOCK | WARN | WARN | WARN | NG-4 word on comment lines of vendored code, now noted |
| 5 of 40 | BLOCK | BLOCK | INCOMPLETE | INCOMPLETE | NG-3/NG-4 words on lines of code (own module file, vendored code, a license text, assembly comments); diff past the cap |
| 10 of 40 | BLOCK | WARN | WARN | WARN | NG-3 word on a comment line of an own file, now noted |
| 11 of 40 | WARN | WARN | PASS | PASS | NG-4 word in a test file: a warn-only word in a test is not reported, a blocking one is noted |
| 17 of 40 | BLOCK | BLOCK | INCOMPLETE | INCOMPLETE | NG-3 word on own lines of code with a trailing comment, and on vendored code; diff past the cap |
| 19 of 40 | BLOCK | WARN | WARN | WARN | NG-3/NG-4 words on comment lines of vendored code, now noted |
| 30 of 40 | WARN | WARN | PASS | PASS | NG-3 word in a documentation file, noted as in 11 of 40 |
| 32 of 40 | BLOCK | BLOCK | WARN | WARN | NG-3 word on lines of vendored code |
| 36 of 40 | BLOCK | BLOCK | WARN | WARN | the regenerated mock file above |
| 37 of 40 | BLOCK | BLOCK | WARN | WARN | NG-3/NG-4 words on lines of vendored code and scripts; its own-file BLOCK before (a comment line) is now noted |
| 39 of 40 | BLOCK | BLOCK | WARN | WARN | the man page and test fixture lines above |

Pull requests 8 and 22 of 40 are BLOCK on all four hooks (vendored `goto`, the vendored linter configuration and
vendored code naming a connection pool).

## Decision 1b (29.09, evening)

The founder extended the code-homonym list instead of keeping decision 1a as it was: `connection(s)`, `pool(s)`,
`generated`, `generate`, `modify`, `modified`, `manually`, `manual`, `persistent` and `mock(s)` joined it. None of
them is a capability word of the lexicon or a technology (the test that pins the list checks it). NG-3 now blocks on
its phrases only (`persistent connection`, `connection pool`) and warns on its three words; NG-4 blocks on
`modify generated`, `generated mocks` and `mocks manually` and warns on its four words. NG-1, NG-2 and NG-5 derive
the same triggers as on the final hook.

Result on the same 40 pull requests: the final + 1b hook gives the first cut's verdict on every pull request
(BLOCK 2 · WARN 12 · PASS 24 · INCOMPLETE 2) and the first cut's 11 BLOCK findings, all on vendored third-party code,
none on the project's own files (74 on the final hook). The 74 lines are possible matches now: the regenerated mock
file warns on `mocks`, the module requirement, the trailing comments, the man page header and the test fixture on
`connection`, `generated` or `modify`. The cost is noise: weak single-word matches (WARN possible) went from 207 to
1 025, most of them the words `connection`, `generated` and `pool` in vendored code; the report counts them and does
not list them.

## Hook 2026-09-30 (30.09)

No verdict moved. On each of the 40 pull requests the hook 2026-09-30 gives final + 1b's verdict and the same
findings, one for one (verdict, kind, trigger, file and line compared): BLOCK 2 · WARN 12 · PASS 24 · INCOMPLETE 2, the
same 11 BLOCK findings on vendored third-party code and none on the project's own files, WARN possible 1 025. As in
repository A this was expected rather than shown to be general: none of the five Non-Goals matches a capability of the
lexicon, so the config forbids no package and the new package matcher has nothing to read. The run shows that the
hook's other readings did not change on this repository; it measures nothing about packages.

## The real finding

None in repository B: every BLOCK of the final hook is on vendored third-party code or on the own-file lines listed
above, and every BLOCK of final + 1b is on vendored third-party code. The one real finding of the two calibration
repositories is in repository A (see [retro-calibration-A.md](retro-calibration-A.md)).

## What this does not show

- The Non-Goals are our reading of the repository's rules, not rules its maintainers wrote in this form.
- 40 pull requests of one repository; no rate is derived from it.
- Weak single-word matches (WARN possible: 207 before and after, 1 025 on final + 1b and on hook 2026-09-30) are counted
  by the report, not listed or judged.
- Nothing about the package matcher of hook 2026-09-30: these Non-Goals forbid no package.
- The per-line raw output (`--json`, file paths and code lines) stays outside the repository; this file is its
  anonymised summary.
