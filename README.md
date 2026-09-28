# lumis-scope-guard

**Your coding agent gets stopped at the boundary, not told about it.**

![One Non-Goal, five clients: Claude Code, Cursor, Codex CLI, Windsurf and Copilot each try `pip install stripe`; the same hook blocks all five before the call runs and names boundary NG-1, set by the founder](demo-block/agents-6.png)

```bash
npx skills add momonanq/lumis-skills --skill lumis-scope-guard --global
```

1. Write ten lines of what your project will NOT do. Or paste them at https://lumis.tools/guard?utm_source=github&utm_medium=readme and get the pack without an account.
2. The agent tries to step over one of them. The hook stops the tool call before it runs and names the boundary and who set it. One script, five clients: Claude Code, Cursor, Codex CLI, Windsurf, Copilot in VS Code.
3. `python scripts/scope_guard.py report` shows what was blocked, what was merely asked for, what was warned, and which agent tried. The log stays in your repo. Nothing leaves it.

The guard also refuses tool calls that would rewrite the guard itself (its script, the five configs, the constitution,
the directories that hold them — also behind `cd`, `./`, `x/../`, a later line of the command, a `find -exec`, a symlink,
or a whole-tree git rewind that git says would change them) and
records them as `tamper`; `doctor` compares fingerprints taken at install, so an edit made outside those tools is visible.
That is a mechanism against a rewrite through the agent, not a security boundary — for the latter, make the files
read-only for the account the agent runs as.

Two layers, both recorded: the agent reads the boundaries and usually refuses before it touches anything (`asked`); when it does not, the hook denies the tool call (`blocked`). The prompt hook only advises: when a request names a forbidden package, path or phrase it tells the agent to check that Non-Goal, and it never refuses a request because one word of a boundary appears in it.

**Three boundary classes, held for you in any project.** A new dependency (`pip install stripe`, `npm install`, `uv add`, …), anything that leaves the machine (`git push`, `gh repo delete`, `npm publish`, a deploy) and a write outside the project root are the founder's decisions whatever the Non-Goals say. Each is set in `.lumis/scope_guard.json`:

```json
"classes": {"dependency": "ask", "outbound": "ask", "outside_root": "ask"}
```

`allow` lets the call through, `ask` (the default) hands it to you, `block` refuses it (exit code 2). A real "ask" — a permission prompt you click — exists in Claude Code and Cursor. Codex CLI and Windsurf have no such answer, and for Copilot one has not been checked yet: there `ask` is a warning (exit code 1), the call proceeds and the reason is logged as `held`. Want a hard stop there? Set the class to `block`. Installing from a lockfile (`npm ci`, `pip install -r`, `uv sync`), a package your manifests already declare and one your stack names are not held; adding a package to `requirements.txt` or `package.json` is. The classes cover a list of verbs, not everything that could leave the machine — a script the agent wrote and runs is not read.

**Observe mode: try the guard without it blocking.** `python scripts/scope_guard.py observe on` turns every refusal and hold into a warning plus a log line marked `observed`; `report` shows how many calls it would have stopped. Changes to the guard's own files are still refused — observe is not an off switch. `observe off` enforces again. Only you switch it: the hook refuses the command to the agent.

`doctor` compares the hook's version (`2026-09-28`) with the `hook_version` in the config and tells you when the hook in `scripts/` is older than the config it reads. `report` prints every count, even at zero, and lists the requests the agent left for you in `.lumis/requests/`.

The recording above is real hook output. Reproduce it with one command from this repository: `python examples/record_block.py` (stdlib only, no account, no model; transcripts in `demo-block/`).

The pack writes hook configs for five clients (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json`); the same script answers each client's call format with exit code 2. Run `python scripts/scope_guard.py doctor` to check the wiring in your repo. The proof that counts is your own client's refusal: if you see it, send a screenshot and we list the client as verified. Any other editor gets the same boundaries as text rules: `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, plus a manual `check`.

## One workflow for the whole team

The hook stops an agent's tool call in the clients that load it. A pull request is where every change arrives — from any agent, in any client, and from people — so the same boundaries are checked there too: `python scripts/scope_guard.py check-diff` reads the lines the pull request adds, judges them against `.lumis/scope_guard.json` as it is on the base branch, and writes one report. **BLOCK** (the job fails): a Non-Goal trigger in an added line of code, a file added, changed or moved under a forbidden path, a new top-level directory ARCHITECTURE.md does not plan (when the config carries the full pack's architecture inventory), a new dependency when `classes.dependency` is `block`, a change to the hook or this workflow, a config deleted, unreadable or left with no boundary. **WARN**: a trigger in a document or a test, a new dependency held for the reviewer, a route or table ARCHITECTURE.md does not list, a submodule (its content is not read), a change to the boundaries themselves — shown as a diff: which NG-n was removed or added, which other key changed, in which commit, by whom. **INCOMPLETE** (the job fails, exit 1): the diff is larger than the check reads (50 000 lines or 5 MB) and the part read holds no BLOCK — the rest was not judged. **PASS**: nothing of that. Each finding names the boundary, who set it, the file and line, the trigger and the line. One pull request comment (edited on the next push, never duplicated), the job summary, SARIF in the Security tab. No score, no model.

Install it in two steps:

1. `python <skill-dir>/scripts/lumis_guard.py init … --ci` writes `.github/workflows/lumis-boundary-check.yml` (the guard ZIP from https://lumis.tools/guard?utm_source=github&utm_medium=readme and the full LUMIS pack already carry it). Or copy the file below by hand; it needs `scripts/scope_guard.py` and `.lumis/scope_guard.json` in the repository.
2. Commit the workflow with `.lumis/` and `scripts/` to the default branch and open a pull request. To make a BLOCK stop the merge, mark "LUMIS boundary check" as a required status check in branch protection.

```yaml
# LUMIS boundary check - generated by LUMIS (scripts/scope_guard.py). Do not edit. The boundaries live in
# .lumis/scope_guard.json. The check reports a change to this file as BLOCK, but a pull request runs its own copy of
# it: make this job a required status check and put this file under CODEOWNERS.
name: LUMIS boundary check

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write
  security-events: write
  actions: read

jobs:
  boundary-check:
    name: LUMIS boundary check
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      BASE_SHA: ${{ github.event.pull_request.base.sha }}
      HEAD_SHA: ${{ github.event.pull_request.head.sha }}
      PR_NUMBER: ${{ github.event.pull_request.number }}
      PYTHONIOENCODING: utf-8
      LUMIS_NO_BASELINE: "1"
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Check the diff against .lumis/scope_guard.json
        id: check
        run: |
          mkdir -p "$RUNNER_TEMP/lumis"
          checker="$RUNNER_TEMP/lumis/scope_guard.py"
          report="$RUNNER_TEMP/lumis/report.md"
          if git show "$BASE_SHA:scripts/scope_guard.py" > "$checker" 2>/dev/null && grep -q "check-diff" "$checker"; then
            export LUMIS_CHECKER_SOURCE=base
          else
            cp scripts/scope_guard.py "$checker" 2>/dev/null || : > "$checker"
            export LUMIS_CHECKER_SOURCE=head
          fi
          code=1
          if [ -s "$checker" ]; then
            set +e
            python -X utf8 "$checker" check-diff --base "$BASE_SHA" --head "$HEAD_SHA" --root "$GITHUB_WORKSPACE" --markdown "$report" --sarif "$RUNNER_TEMP/lumis/report.sarif" --json "$RUNNER_TEMP/lumis/report.json"
            code=$?
            set -e
          fi
          if [ ! -s "$report" ]; then
            code=1
            echo "<!-- lumis-boundary-check -->" > "$report"
            echo "## LUMIS boundary check - could not run" >> "$report"
            echo "" >> "$report"
            echo "scripts/scope_guard.py is missing on the base commit and in this pull request, or it wrote no report. This is not a PASS: nothing was checked." >> "$report"
          fi
          echo "exit=$code" >> "$GITHUB_OUTPUT"
          cat "$report" >> "$GITHUB_STEP_SUMMARY"
      - name: Upload SARIF (code scanning)
        if: always()
        continue-on-error: true
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: ${{ runner.temp }}/lumis/report.sarif
          category: lumis-boundary-check
      - name: Post or refresh the pull request comment
        if: always()
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          body="$RUNNER_TEMP/lumis/report.md"
          [ -f "$body" ] || exit 0
          id=$(gh api "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" --paginate --jq '.[] | select(.user.login == "github-actions[bot]") | select(.body | startswith("<!-- lumis-boundary-check -->")) | .id' | head -n 1)
          if [ -n "$id" ]; then
            gh api --method PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$id" -F "body=@$body" > /dev/null
          else
            gh api --method POST "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" -F "body=@$body" > /dev/null
          fi
      - name: Verdict
        if: always()
        env:
          CHECK_EXIT: ${{ steps.check.outputs.exit }}
        run: |
          if [ "$CHECK_EXIT" = "0" ]; then exit 0; fi
          if [ "$CHECK_EXIT" = "2" ]; then echo "LUMIS boundary check: BLOCK - see the pull request comment or the job summary"; exit 2; fi
          echo "LUMIS boundary check could not run or could not read the whole diff (exit $CHECK_EXIT) - see the job summary"; exit 1
```

The file is generated from the hook (`CI_WORKFLOW_YAML` in `scripts/scope_guard.py`), so `init --ci` and both ZIPs write exactly this text. It runs the checker from the base commit, so a pull request that rewrites the hook is not judged by its own rewrite; it passes only SHAs and the pull request number to its scripts; it needs no action of ours from the marketplace. Run the same check locally with `python scripts/scope_guard.py check-diff --base main`; exit 0 is PASS or WARN, 2 is BLOCK, 1 is "could not run" or INCOMPLETE, which the report says plainly and never calls a PASS.

**What it does not do.** It reads text: words, paths, packages, manifests and new top-level directories — not meaning, so a home-grown billing module that never says "stripe" passes, and there is no semantic judge in this version. JS/TS are matched as text patterns; AST rules come later, for Python only. What a script runs (`bash -c …` inside it) is not read. Binary files (images, archives, compiled objects) and the content of submodules are not read; the report names them. Outbound actions and writes outside the project are actions, not lines of a diff: the hook holds those, this check lists them as not checked. It runs after the change is written, not before the agent's call. A pull request runs its own copy of the workflow, so one that removes the check step removes the check: make the check required and put the guard's files under CODEOWNERS. A pull request from a fork gets a read-only token: no comment and no SARIF, the job summary and the verdict remain. It is a review aid, not a security boundary.

---

## Install by hand

Copy `skills/lumis-scope-guard/` into `.claude/skills/` (project) or `~/.claude/skills/` (global), or paste into Claude Code / Cursor: `Install the /lumis-scope-guard skill from https://github.com/momonanq/lumis-skills`.

| skill | what it does |
|---|---|
| `lumis-scope-guard` | Non-Goals → enforceable boundaries: hook configs for five agents, `CONSTITUTION.md`, sections in `.cursorrules` and `CLAUDE.md`, a drift check for any plan. Every block names the boundary it enforces (`NG-n`, who set it, where it is written); every event lands in `.lumis/guard.log` inside the repo — `status` and `report` summarise it, `doctor` checks the wiring. Stdlib Python, no model, no account, no telemetry. Same engine as https://lumis.tools/guard?utm_source=github&utm_medium=readme. |

## What the pack contains

- `.lumis/scope_guard.json` — the boundaries and their triggers (packages, paths, keywords), the `mode` (`enforce` | `observe`), the three `classes` and the `hook_version`; plain JSON, edit it by hand
- `.claude/settings.json` — deny rules for forbidden installs plus the `PreToolUse` / `UserPromptSubmit` hooks (merged into an existing file)
- `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json` — the same guard for Cursor, Codex CLI, Windsurf and Copilot
- `scripts/scope_guard.py` — the hook: blocks Non-Goal triggers (exit 2), holds the three boundary classes for you, warns about visual and architecture boundaries (exit 1), writes `.lumis/guard.log`
- `CONSTITUTION.md`, `.cursorrules`, `CLAUDE.md` — the same boundaries in words, for the agent and for people
- `.github/workflows/lumis-boundary-check.yml` (with `init --ci`, and in both LUMIS ZIPs) — the same boundaries checked on every pull request: PASS / WARN / BLOCK, one comment, SARIF

`skills/lumis-scope-guard/scripts/scope_guard.py` is a verbatim copy of the hook shipped in every LUMIS pack (kept in sync by the product's test suite).

## License

MIT.
