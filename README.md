# lumis-scope-guard

From the makers of LUMIS: https://lumis.tools/?utm_source=github&utm_medium=readme

**Your coding agent gets stopped at the boundary, not told about it.**

![Recorded hook output, one Non-Goal: the hook script is fed a `pip install stripe` call in each client's documented hook format (Claude Code, Cursor, Codex CLI, Windsurf, Copilot) and refuses each one, naming boundary NG-1, set by the founder; a script-level recording, not five live clients](demo-block/agents-6.png)

Install it one way, not both (in Claude Code the plugin and a skills CLI copy would both load):

**skills CLI**

```bash
npx skills add momonanq/lumis-skills --skill lumis-scope-guard --global
```

**Claude Code plugin**, from this repository's own marketplace

```bash
claude plugin marketplace add momonanq/lumis-skills
claude plugin install lumis-scope-guard@lumis-skills
```

Then, in your project, run `/lumis-scope-guard init` (from the plugin: `/lumis-scope-guard:lumis-scope-guard init`). Installing changes no project; `init` does, and [Permissions this changes](#permissions-this-changes) lists every file it writes.

1. Write ten lines of what your project will NOT do. Or paste them at https://lumis.tools/guard?utm_source=github&utm_medium=readme and get the pack without an account.
2. The agent tries to step over one of them. The hook stops the tool call before it runs and names the boundary and who set it. One script, five clients: Claude Code, Cursor, Codex CLI, Windsurf, Copilot in VS Code.
3. `python scripts/scope_guard.py report` shows what was blocked, what was merely asked for, what was warned, and which agent tried. The log stays in your repo. Nothing leaves it.

**Where it has been checked**

| Where | Status |
|---|---|
| Claude Code | Live, 2026-09-08: in real sessions the agent refused by the written rules, and the hook ran on real tool calls and logged what it refused. That was the hook of that date; the rules for what blocks changed on 2026-09-29 and 2026-09-30 and have not been run live since. |
| Cursor, Codex CLI, Windsurf, Copilot in VS Code | Config written and answered by the same script (each client's call format is covered by tests); not yet confirmed in a live client. |
| CI on pull requests | Seen on a private probe repository on 2026-09-28, with the template and hook of that day (pull requests only): one pull request comment, edited in place on the next push, and the check red on BLOCK, green after the next push removed the crossing. The SARIF upload has not been seen working on a live repository (code scanning was off in the private probe). The push trigger and the `upload-sarif@v4` pin of the workflow below, and the Marketplace action, have not yet run on GitHub. |

**CI for pull requests:** the same boundaries on every pull request — see [One workflow for the whole team](#one-workflow-for-the-whole-team).

## Permissions this changes

Installing with the commands above adds the skill and changes no project. The plugin is this repository: the skill (`SKILL.md` and two stdlib Python scripts), the examples and the recording, and no hooks of its own, so nothing of it runs in a project you have not set up. The guard's hooks are project-level on purpose: `init` writes them into the one repository you run it in, after you give it your Non-Goals.

What `init` writes, in the repository root unless noted:

- `.claude/settings.json`: `permissions.deny` rules (installs of the packages your Non-Goals forbid, edits under the paths they forbid, edits of the guard's own files) and `PreToolUse` and `UserPromptSubmit` hooks that run `scripts/scope_guard.py` before edits, shell commands and MCP tool calls, and on each prompt. Merged into your file: your rules and hooks stay; a file that is not valid JSON is replaced.
- `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json`: the same hook for Cursor, Codex CLI, Windsurf and Copilot, merged the same way.
- `scripts/scope_guard.py` (the hook); `.lumis/` (the config, the fingerprints and a `.gitignore` that keeps the log out of commits; later the log and `requests/`); `CONSTITUTION.md` (`CONSTITUTION.lumis.md` next to a hand-written one); marked sections in `.cursorrules` and `CLAUDE.md`, your text kept.
- With `--ci`: `.github/workflows/lumis-boundary-check.yml`.
- With `--pre-commit`: `pre-commit` in git's hooks folder (`.git/hooks/`, or the folder `core.hooksPath` names), only when no other pre-commit hook is there and that folder belongs to this repository.
- Outside the repository: a copy of the fingerprints in `~/.lumis/baselines/<repo-id>/manifest.json` (`LUMIS_HOME` moves it, `LUMIS_NO_BASELINE=1` switches it off).

From then on the hook refuses the agent's edits to the guard's own files — the deny rules and hooks above included, and `.claude/settings.local.json`, where `disableAllHooks` would switch the hook off — and logs them as `tamper` (see [The guard protects itself](#the-guard-protects-itself)). Changing them is yours. `.cursorrules`, `CLAUDE.md` and `AGENTS.md` only get a warning. No network access and no telemetry: the scripts are stdlib Python, they run nothing but `git` and Python on your machine, and the log stays in your repository. The optional workflow runs on GitHub with the job's own token: it posts one pull request comment and uploads SARIF.

## How the guard works

### Two layers

Two layers, both recorded: the agent reads the boundaries and usually refuses before it touches anything (`asked`); when it does not, the hook denies the tool call (`blocked`). The prompt hook only advises: when a request names a forbidden package, path or phrase it tells the agent to check that Non-Goal, and it never refuses a request because one word of a boundary appears in it.

### The guard protects itself

The guard also refuses tool calls that would rewrite the guard itself (its script, the five configs, the constitution,
the directories that hold them — also behind `cd`, `./`, `x/../`, a later line of the command, a `find -exec`, a symlink,
or a whole-tree git rewind that git says would change them) and
records them as `tamper`; `doctor` compares fingerprints taken at install, so an edit made outside those tools is visible.
That is a mechanism against a rewrite through the agent, not a security boundary — for the latter, make the files
read-only for the account the agent runs as.

### Three boundary classes, held for you in any project

A new dependency (`pip install stripe`, `npm install`, `uv add`, …), anything that leaves the machine (`git push`, `gh repo delete`, `npm publish`, a deploy) and a write outside the project root are the founder's decisions whatever the Non-Goals say. Each is set in `.lumis/scope_guard.json`:

```json
"classes": {"dependency": "ask", "outbound": "ask", "outside_root": "ask"}
```

`allow` lets the call through, `ask` (the default) hands it to you, `block` refuses it (exit code 2). A real "ask" — a permission prompt you click — exists in Claude Code and Cursor. Codex CLI and Windsurf have no such answer, and for Copilot one has not been checked yet: there `ask` is a warning (exit code 1), the call proceeds and the reason is logged as `held`. Want a hard stop there? Set the class to `block`. Installing from a lockfile (`npm ci`, `pip install -r`, `uv sync`), a package your manifests already declare and one your stack names are not held; adding a package to `requirements.txt` or `package.json` is. The classes cover a list of verbs, not everything that could leave the machine — a script the agent wrote and runs is not read.

### Observe mode: try the guard without it blocking

`python scripts/scope_guard.py observe on` turns every refusal and hold into a warning plus a log line marked `observed`; `report` shows how many calls it would have stopped. Changes to the guard's own files are still refused — observe is not an off switch. `observe off` enforces again. Only you switch it: the hook refuses the command to the agent.

### Five clients, one script

The pack writes hook configs for five clients (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json`); the same script answers each client's call format with exit code 2. Run `python scripts/scope_guard.py doctor` to check the wiring in your repo. The proof that counts is your own client's refusal: if you see it, send a screenshot and we list the client as verified. Any other editor gets the same boundaries as text rules: `.cursorrules` and `CLAUDE.md` (the pack from lumis.tools/guard also writes `AGENTS.md`), plus a manual `check`.

**What blocks and what only warns.** A refusal needs high-precision evidence: a forbidden package in an install command, an import or a manifest line; a file under a forbidden path; a name your Non-Goal writes as code (`@Transactional`, anything in backticks), as written or fully qualified (`@org.springframework.transaction.annotation.Transactional`); a phrase of the Non-Goal (`payment collection`, also as `payment_collection` or `PaymentCollection`) and a word of it that names the capability (`payment`); a word the Non-Goal names on its own (`billing` in "No payment collection or billing"). Everything weaker is a warning with its reason, printed and logged, never a refusal: a word of a phrase that code uses for something else (`collection`, `mobile`), a lone word of a long sentence, any trigger in a comment line or in `.gitignore` and its kin (`noted`: written down, not crossed — unless a line of code in the same change carries it), a word found only inside another tool's option in a shell command, a CI file, a lockfile or a manifest (`pnpm install --frozen-lockfile`; never in your own source, never for a technology your Non-Goal names), and a word found only in the import of a standard library module spelling another form of it (`from collections import defaultdict`; your own `from app.billings import charge` is refused). The hook and the pull request check below read each line with the same function.

**A package is a whole name (hook 2026-09-30).** A forbidden package is the name a line actually brings in, never a word that starts with it: the specifier of a JS/TS import or `require` (`'expo'`, `'expo/config'`, `'@stripe/stripe-js'` for `stripe`; a local `./exportCsv` never), the top-level module of a Python import (`import paypal_checkout` for `paypal-checkout`, not `import export_utils` for `expo`), the vendor's part of a Java, Kotlin, C#, Rust, PHP, Go or Ruby import (`com.stripe.Stripe`, `using Stripe;`; not `javax.xml.ws` or your own `com.acme.api.ws`), the name a manifest line declares, and the package an install command installs or runs (`pip install stripe`, `npx expo start`, `RUN ["pip", "install", "stripe"]`, `echo 'stripe==5' >> requirements.txt`, `pnpm --filter web add ws`, `docker compose exec api pip install stripe`, a Makefile's `@pip install stripe`, `$PIP install stripe`), the package a forbidden stack's own config names (`"expo"` in `app.json`, a pubspec's `flutter:`, a `.csproj` `<PackageReference Include="Stripe.net">`), also written over several lines (`RUN pip install \`, `import { Resend }` … `from 'resend'`) — and a line an Edit adds inside such a statement is read with the file around it (`    resend \` under an existing `RUN pip install \`), as the pull request check reads it with the diff's context lines. `ws = wb.active` is not the package `ws`, and `npm install export-to-csv` is a new dependency like any other (held for you, not refused). A family is named, never guessed from a hyphen, and read in npm names only: `deny_package_prefixes` (`expo-`, `@expo/`, `react-native-`, `@react-native/` under a native-mobile Non-Goal) refuses `expo-notifications`; `ws-client` is another package, and so is a PyPI `expo-helpers`. A config written before 2026-09-30 keeps working and gets the families from `rebuild-markers`, with the packages the lexicon gained since its `hook_version` (added to what it lists; `doctor` names them).

The recording above is real hook output. Reproduce it with one command from this repository: `python examples/record_block.py` (stdlib only, no account, no model; transcripts in `demo-block/`).

### doctor and report

`doctor` compares the hook's own version (its `HOOK_VERSION`) with the `hook_version` in the config and tells you when the hook in `scripts/` is older than the config it reads. `report` prints every count, even at zero, and lists the requests the agent left for you in `.lumis/requests/`.

## One workflow for the whole team

The hook stops an agent's tool call in the clients that load it. A pull request is where every change arrives — from any agent, in any client, and from people — so the same boundaries are checked there too: `python scripts/scope_guard.py check-diff` reads the lines the pull request adds, judges them against `.lumis/scope_guard.json` as it is on the base branch, and writes one report. **BLOCK** (the job fails): a Non-Goal trigger on an added line of code (not a comment line), a file added, changed or moved under a forbidden path, a new top-level directory ARCHITECTURE.md does not plan (when the config carries the full pack's architecture inventory), a new dependency when `classes.dependency` is `block`, a change to the hook or this workflow, a config deleted, unreadable or left with no boundary. **WARN**: a trigger in a document, a test, a comment line or an ignore file, a word of a Non-Goal phrase that code uses every day for something else (`collection`, `session`, `token`, …) or a lone word out of a long Non-Goal, a single word found only inside a command-line option of a shell command, a CI file or a lockfile, or inside the import of a well-known library (`from collections import …`), a new dependency held for the reviewer, a route or table ARCHITECTURE.md does not list, a submodule (its content is not read), a change to the boundaries themselves — shown as a diff: which NG-n was removed or added, which other key changed, in which commit, by whom. **INCOMPLETE** (the job fails, exit 1): the diff is larger than the check reads (50 000 added and removed lines, 5 MB, or 60 s of reading) and the part read holds no BLOCK — the rest was not judged. **PASS**: nothing of that. Each finding names the boundary, who set it, the file and line, the trigger and the line. One pull request comment (edited on the next push), the job summary, and a SARIF file for code scanning; its upload has not yet been seen on a live repository. No score, no model.

Install it in two steps:

1. `python <skill-dir>/scripts/lumis_guard.py init … --ci` writes `.github/workflows/lumis-boundary-check.yml` (the guard ZIP from https://lumis.tools/guard?utm_source=github&utm_medium=readme and the full LUMIS pack already carry it). Or copy the file below by hand; it needs `scripts/scope_guard.py` and `.lumis/scope_guard.json` in the repository.
2. Commit the workflow with `.lumis/` and `scripts/` to the default branch and open a pull request. To make a BLOCK stop the merge, mark "LUMIS boundary check" as a required status check in branch protection.

<details>
<summary>The workflow file, <code>.github/workflows/lumis-boundary-check.yml</code></summary>

```yaml
# LUMIS boundary check - generated by LUMIS (scripts/scope_guard.py). Do not edit. The boundaries live in
# .lumis/scope_guard.json. The check reports a change to this file as BLOCK, but a pull request runs its own copy of
# it: make this job a required status check and put this file under CODEOWNERS.
# Runs on every pull request, and on a push to main/master so code scanning has an analysis of the base branch.
name: LUMIS boundary check

on:
  pull_request:
  push:
    branches: [main, master]

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
      EVENT_NAME: ${{ github.event_name }}
      BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}
      HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
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
          sarif="$RUNNER_TEMP/lumis/report.sarif"
          if [ "$EVENT_NAME" = "push" ] && ! git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null; then
            BASE_SHA=$(git rev-parse -q --verify "$HEAD_SHA^" || true)
          fi
          if [ -z "$BASE_SHA" ]; then
            echo "exit=0" >> "$GITHUB_OUTPUT"
            echo "<!-- lumis-boundary-check -->" > "$report"
            echo "## LUMIS boundary check - nothing to compare" >> "$report"
            echo "" >> "$report"
            echo "The first commit on this branch has no parent: nothing was checked." >> "$report"
            echo '{"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": [{"tool": {"driver": {"name": "LUMIS scope guard"}}, "results": []}]}' > "$sarif"
            cat "$report" >> "$GITHUB_STEP_SUMMARY"
            exit 0
          fi
          if git show "$BASE_SHA:scripts/scope_guard.py" > "$checker" 2>/dev/null && grep -q "check-diff" "$checker"; then
            export LUMIS_CHECKER_SOURCE=base
          else
            cp scripts/scope_guard.py "$checker" 2>/dev/null || : > "$checker"
            export LUMIS_CHECKER_SOURCE=head
          fi
          code=1
          if [ -s "$checker" ]; then
            set +e
            python -X utf8 "$checker" check-diff --base "$BASE_SHA" --head "$HEAD_SHA" --root "$GITHUB_WORKSPACE" --markdown "$report" --sarif "$sarif" --json "$RUNNER_TEMP/lumis/report.json"
            code=$?
            set -e
          fi
          if [ ! -s "$report" ]; then
            code=1
            echo "<!-- lumis-boundary-check -->" > "$report"
            echo "## LUMIS boundary check - could not run" >> "$report"
            echo "" >> "$report"
            echo "scripts/scope_guard.py is missing on the base commit and in this change, or it wrote no report. This is not a PASS: nothing was checked." >> "$report"
          fi
          echo "exit=$code" >> "$GITHUB_OUTPUT"
          cat "$report" >> "$GITHUB_STEP_SUMMARY"
      - name: Upload SARIF (code scanning)
        if: always()
        continue-on-error: true
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: ${{ runner.temp }}/lumis/report.sarif
          category: lumis-boundary-check
      - name: Post or refresh the pull request comment
        if: always() && github.event_name == 'pull_request'
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

</details>

The file is generated from the hook (`CI_WORKFLOW_YAML` in `scripts/scope_guard.py`), so `init --ci` and both ZIPs write exactly this text. It runs on every pull request and on a push to `main`/`master` (so code scanning has the base branch to compare with; code scanning is free in public repositories and needs GitHub Advanced Security in private ones — without it the upload step only logs that, the comment and the job summary remain). It runs the checker from the base commit, so a pull request that rewrites the hook is not judged by its own rewrite; it passes only SHAs and the pull request number to its scripts; it needs no action of ours from the marketplace. Run the same check locally with `python scripts/scope_guard.py check-diff --base main`; exit 0 is PASS or WARN, 2 is BLOCK, 1 is "could not run" or INCOMPLETE, which the report says plainly and never calls a PASS.

### What it does not do

It reads text: words, paths, packages, manifests and new top-level directories — not meaning, so a home-grown billing module that never says "stripe" passes, and there is no semantic judge in this version. JS/TS are matched as text patterns; AST rules come later, for Python only. What a script runs (`bash -c …` inside it) is not read. Binary files (images, archives, compiled objects) and the content of submodules are not read; the report names them. Outbound actions and writes outside the project are actions, not lines of a diff: the hook holds those, this check lists them as not checked. It runs after the change is written, not before the agent's call. A pull request runs its own copy of the workflow, so one that removes the check step removes the check: make the check required and put the guard's files under CODEOWNERS. A pull request from a fork gets a read-only token: no comment and no SARIF, the job summary and the verdict remain. It is a review aid, not a security boundary.

---

## Install by hand

Copy `skills/lumis-scope-guard/` into `.claude/skills/` (project) or `~/.claude/skills/` (global), or paste into Claude Code / Cursor: `Install the /lumis-scope-guard skill from https://github.com/momonanq/lumis-skills`.

| skill | what it does |
|---|---|
| `lumis-scope-guard` | Non-Goals → enforceable boundaries: hook configs for five agents, `CONSTITUTION.md`, sections in `.cursorrules` and `CLAUDE.md`, a drift check for any plan. Every block names the boundary it enforces (`NG-n`, who set it, where it is written); every event lands in `.lumis/guard.log` inside the repo — `status` and `report` summarise it, `doctor` checks the wiring. Stdlib Python, no model, no account, no telemetry. Same engine as https://lumis.tools/guard?utm_source=github&utm_medium=readme. |

### As a Claude Code plugin

- `.claude-plugin/marketplace.json` makes this repository a plugin marketplace named `lumis-skills` with one plugin, `lumis-scope-guard`, whose root is the repository itself; `.claude-plugin/plugin.json` describes it. The plugin loads the same `skills/lumis-scope-guard/` folder the skills CLI installs.
- Updates: `claude plugin update lumis-scope-guard@lumis-skills` (a restart applies them).
- The plugin adds the skill to Claude Code and nothing else: no plugin-level hooks, no MCP server, nothing that runs in every project. The guard's hooks are project-level and written by `init` into the repository you run it in; that is the intended behaviour.
- The guard needs a repository and a shell, which is Claude Code (the terminal, the IDE extensions, the desktop app's Code tab). claude.ai chat and Cowork load plugin skills too; the guard has not been tried there.

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
