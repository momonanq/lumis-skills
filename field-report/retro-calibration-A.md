# Retro calibration, repository A (anonymised)

Run 2026-09-29 by the engineering session, founder decision 10a: both calibration retros re-run on the final hook of
branch `gtm-rework`, before and after, on the same pull requests and the same Non-Goals as the GTM run of 29.09.
Re-run the same evening on the final hook with founder decision 1b (the code-homonym list extended): the column
"final + 1b" below; the "after" column is kept as it was measured. Re-run on 2026-09-30 on hook 2026-09-30 (the
package matcher and the shared lexicon): the column "hook 2026-09-30"; the earlier columns are kept as measured.

Anonymised: no owner or repository name, no pull request number or title, no file path, no code line. A pull request
is named by its position in the list (1 = the newest merge). A line is described by its kind (code, comment, ignore
file) and the kind of file it sits in.

## What was run

- **Repository A**: a public Java/TypeScript repository (server and web client) with a CLAUDE.md.
- **Pull requests**: the last 40 merged pull requests, the list the GTM run of 29.09 saved (`gh pr list --json` shape;
  the file is not in this repository). All 40 were merged into the default branch, so the new `--base` default of
  `scripts/retro_report.py` left none out (`left_out: {}` in both runs).
- **Non-Goals**: the five lines of that run, our reading of the repository's CLAUDE.md, unchanged:
  - NG-1: a ban on one transaction annotation on service methods (the Non-Goal writes the annotation as code);
  - NG-2: a ban on role assignment through an identity provider's admin API;
  - NG-3: a ban on taking authorities from token claims;
  - NG-4: a ban on renaming two identity-provider groups;
  - NG-5: no npm or yarn lockfiles.
- **Tool**: `scripts/retro_report.py` of the tools commit on `gtm-rework` (the same file for both runs), with
  `--prs-json`, `--clone` (a local clone from the 29.09 run, no network needed) and `--json`. It runs the hook's
  `check-diff` once per pull request, locally and read-only. No model, no gh call, no token.
- **Before**: `scope_guard.py` and `lumis_guard.py` of commit 3dbf752, `HOOK_VERSION = "2026-09-28"` (sha256 of the
  hook `a928329614ecaf0791e6332c04371a148be592ef39ba863f5ebfd3782cc7e4f4`, equal to `git show
  3dbf752:lumis/exports/scope_guard.py`).
- **After**: the same two files at `gtm-rework` c92bd4d (hook rework fe98526 included), `HOOK_VERSION = "2026-09-29"`
  (sha256 `dc90e35fd8d0b99d1f8ca8eaffec98f8c7379f6874bd76a127b2e32839f3401b`, byte-identical in `lumis/exports/` and
  `skills/lumis-scope-guard/scripts/`).
- **Final + 1b**: the same hook with `CODE_HOMONYMS` extended by decision 1b (`connection(s)`, `pool(s)`,
  `generated`, `generate`, `modify`, `modified`, `manually`, `manual`, `persistent`, `mock(s)`), nothing else changed
  (sha256 `64ae54b1439d7bf7cbb0f2a22a4cb439191b56eb79af7c670c4bd5a57c068460`, `HOOK_VERSION` still `"2026-09-29"`),
  the same `retro_report.py`, pull request list, Non-Goals and local clone.
- **First cut** (reference only, not re-run): the 29.09 run on the first cut of hook 2026-09-29 (95ad8d6), read from
  its saved JSON. That run is the source of the table in docs/BOUNDARY_CHECK_CI.md, "Precision".
- **Hook 2026-09-30** (run 2026-09-30 by the engineering session): `scope_guard.py` and `lumis_guard.py` of branch
  `hook-pkg-match` after the review fixes (a forbidden package matched as a whole name, the free pack's lexicon fixes
  in the shared lexicon; `HOOK_VERSION = "2026-09-30"`, sha256 of the hook `eff7b1d02a0f386001e40342649aafb305d5bf089d370c348c805afde477e179`, byte-identical in
  `lumis/exports/` and `skills/lumis-scope-guard/scripts/`), the same `retro_report.py` as final + 1b, the same pull
  request list, Non-Goals and local clone.

## Verdicts per pull request (the report's verdicts)

The report leaves out findings in generated files (lockfiles, SBOMs) and LUMIS's own guard files and recomputes the
verdict on what is kept (retro_report.py docstring).

| verdict | before (2026-09-28) | after (final 2026-09-29) | final + 1b | first cut (reference) | hook 2026-09-30 |
|---|---|---|---|---|---|
| BLOCK | 5 | 1 | 1 | 1 | 1 |
| WARN | 12 | 15 | 15 | 15 | 15 |
| PASS | 23 | 23 | 23 | 23 | 23 |
| INCOMPLETE | 0 | 1 | 1 | 1 | 1 |
| skipped / error | 0 | 0 | 0 | 0 | 0 |

The checker's own verdicts, generated files included: before BLOCK 7 · WARN 11 · PASS 22; after BLOCK 2 · WARN 15 ·
PASS 22 · INCOMPLETE 1; final + 1b the same as after. The second BLOCK after is a dependency name in a generated SBOM file (pull request 37 of 40).

## BLOCK findings

| hook | BLOCK findings | where |
|---|---|---|
| before | 11 | NG-1: 2 comment lines in main source files, 2 comment lines in test files, 1 line of code in a main source file. NG-5: 2 lines in an ignore file, 2 comment lines in CI workflow files, 1 line of code in a CI workflow file (a package-manager option), 1 comment line in a script |
| after | 1 | NG-1: 1 line of code in a main source file |
| final + 1b | 1 | the same line |
| hook 2026-09-30 | 1 | the same line |

What moved (derivation of the triggers): NG-1 blocked on the bare word of the annotation before; now the annotation
as written blocks and the bare word only warns. NG-5 blocked on each of its two words before; now only the phrase
blocks and the two words warn (both are on the code-homonym list). NG-2, NG-3 and NG-4 derive the same triggers on
both hooks.

## Pull requests whose verdict changed

| pull request | before | after | why |
|---|---|---|---|
| 2 of 40 | BLOCK | WARN | the annotation's bare word on comment lines (a main source file and a test file) now warns |
| 5 of 40 | BLOCK | WARN | the same kind of comment lines |
| 22 of 40 | BLOCK | WARN | a package-manager option in a CI workflow file and two lines of an ignore file now warn; a note in a documentation file stays |
| 31 of 40 | BLOCK | INCOMPLETE | its BLOCKs were comment lines naming a lockfile option; without them the part read holds no BLOCK, and the diff is larger than the check reads (50 000 diff lines), so the verdict is INCOMPLETE, not PASS |

The final hook and the first cut give the same verdict on all 40 pull requests and the same single BLOCK finding.

## Decision 1b (29.09, evening)

None of the words decision 1b added to the code-homonym list is a word of repository A's five Non-Goals, so every
boundary derives the same triggers as on the final hook. Final + 1b gives the final hook's verdict, the same checker
verdict and the same number of findings on each of the 40 pull requests: BLOCK 1 · WARN 15 · PASS 23 · INCOMPLETE 1,
one BLOCK finding (the real one below), WARN possible 1 292.

## Hook 2026-09-30 (30.09)

No verdict moved. On each of the 40 pull requests the hook 2026-09-30 gives final + 1b's verdict and the same
findings, one for one (verdict, kind, trigger, file and line compared): BLOCK 1 · WARN 15 · PASS 23 · INCOMPLETE 1, the
checker's own BLOCK 2 · WARN 15 · PASS 22 · INCOMPLETE 1, one BLOCK finding (the real one below), WARN possible 1 292.
This was expected rather than shown to be general: none of repository A's five Non-Goals matches a capability of the
lexicon, so the config forbids no package (`deny_packages` is empty) and the new package matcher has nothing to read;
the lexicon changes of 2026-09-30 touch none of these boundaries either. The run shows that the hook's other readings
(phrases, code names, comment lines, options) did not change on this repository; it measures nothing about packages.

## The one real finding, kept

Pull request 8 of 40 adds the annotation NG-1 forbids to a method of a service class, on a line of code in a main
source file. BLOCK on both hooks.

## What this does not show

- The Non-Goals are our reading of the repository's rules, not rules its maintainers wrote in this form.
- 40 pull requests of one repository; no rate is derived from it.
- Weak single-word matches (WARN possible: 1 283 before, 1 292 after, on final + 1b and on hook 2026-09-30) are counted by the report, not listed or judged.
- Nothing about the package matcher of hook 2026-09-30: these Non-Goals forbid no package.
- The per-line raw output (`--json`, file paths and code lines) stays outside the repository; this file is its
  anonymised summary.
