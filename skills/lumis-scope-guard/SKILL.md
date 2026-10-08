---
name: lumis-scope-guard
description: Turn a list of Non-Goals into enforceable boundaries for the coding agent — deny rules and hooks that block forbidden dependencies, paths and keywords, a CONSTITUTION.md and a .cursorrules section — plus a startup ritual, a drift check for any plan and the same boundaries checked on every pull request (GitHub Actions). No model, no account, stdlib Python.
---

# LUMIS scope guard

Use this skill when the user wants the agent to **stay inside agreed boundaries**: "this product must never have X",
"lock the scope", "the agent keeps adding features", or when a specification exists and only guard rails are missing.
Prompts alone do not hold; this installs hooks that block the change before it happens.

## Commands

- `/lumis-scope-guard init` — ask for the Non-Goals (one per line), optional invariants and stack, then run:
  `python <skill-dir>/scripts/lumis_guard.py init --project "<name>" --non-goals "<a; b; c>" [--invariants "<x; y>"] [--stack "<stack>"] --root <repo root>`
  It writes `.lumis/scope_guard.json`, merges deny rules and hooks into `.claude/settings.json`, writes hook configs for Cursor
  (`.cursor/hooks.json`), Codex
  (`.codex/hooks.json`), Devin Desktop, ex-Windsurf (`.devin/hooks.json`, and the same file at the legacy
  `.windsurf/hooks.json` for older builds) and GitHub Copilot (`.github/hooks/lumis-scope-guard.json`, Copilot's
  camelCase format) — all of them deny on exit code 2, so one script guards every agent — copies `scripts/scope_guard.py`,
  writes `CONSTITUTION.md` (never overwrites a hand-written one — it creates `CONSTITUTION.lumis.md` instead) and marked sections in `.cursorrules` and `CLAUDE.md` (existing content is kept).
  Add `--observe` to install in observe mode, `--unattended` for the unattended profile (both below). The output names the
  hook version, the mode, the profile and the classes: `Hook 2026-10-07 · mode: enforce · profile: attended · classes: ...`.
  Add `--ci` to also write `.github/workflows/lumis-boundary-check.yml`, the same boundaries checked on every pull request
  (see "CI check" below). A different file already at that path is never overwritten: the LUMIS copy goes to
  `.github/lumis-boundary-check.lumis.yml` and the output says so. Without `--ci` the output says how to add it.
  Add `--pre-commit` (or run `python scripts/scope_guard.py install-pre-commit` yourself) for the same check on the staged
  change before each commit: local only — each clone installs it once, `git commit --no-verify` skips it, the pull request
  check is the server-side one; a pre-commit hook that is not LUMIS's is never overwritten (the line to add is printed).
- `/lumis-scope-guard check-diff` — run `python scripts/scope_guard.py check-diff --base <target branch>` from the repository
  and report the verdict and each finding it prints. Read-only: it reads git and prints; do not add `--markdown`, `--sarif` or
  `--json` (writing a file with the hook's command is refused to the agent).
- `/lumis-scope-guard check <plan or diff>` — run `python <skill-dir>/scripts/lumis_guard.py check --text "<text>" --root <repo root>`
  and report every Non-Goal trigger and drift phrase it prints. Exit code 1 means a violation: do not proceed, ask the founder.
  A plan is read as prose (a package named in a sentence counts, as in a request); a unified diff is read as code, each added
  line in its file's language, as the pull request check reads it.
- `/lumis-scope-guard doctor` — run `python <skill-dir>/scripts/scope_guard.py doctor --root <repo root>` (or `python scripts/scope_guard.py doctor`
  from the repository): checks that the hook script, `.lumis/scope_guard.json` and each agent's config are present and valid, and that the
  interpreter they call is on PATH. It checks the wiring only — whether your client actually honours the hook is proven by the self-test below.
  It also prints the mode, the profile, the three classes and the hook's version against the `hook_version` the config was written for (see
  "Hook version" below).
- `/lumis-scope-guard status` — which guard files exist, how many triggers are in force, and what the guard has done so far
  (`.lumis/guard.log`: blocked / held / warned / drift events, last five shown). `python scripts/scope_guard.py report` prints the full summary.

If a boundary was reworded, or the config was written by an older version and arms ordinary words (`python`, `public`,
`production`), the founder runs `python scripts/scope_guard.py rebuild-markers --dry-run` from the repository: it re-derives
`keywords` and `warn_keywords` from the boundaries the config already carries, prints the diff per boundary and writes nothing;
without `--dry-run` it writes and re-baselines the manifest. Everything else — the architecture inventory, the deny lists, and any
marker listed under `pinned_keywords` — is kept. It is the founder's command: the hook refuses it to the agent, `--dry-run` included.

Every block names the boundary it enforces — `NG-3 "no crypto payments" (set by the founder; CONSTITUTION.md, Article I)` — so the
agent (and the founder) see *which* rule fired and where it is written, not just that something was refused.
The log stays in the repository; nothing is sent anywhere.

### What blocks and what warns

Only high-precision evidence blocks (exit 2): a forbidden package in an install command, an import or a manifest line; a file
under a forbidden path; a name the Non-Goal writes as code (`@Transactional`, anything in backticks), as written and fully
qualified (`@org.springframework.transaction.annotation.Transactional`); a phrase of the Non-Goal (`payment collection`, also
spelled `payment_collection` or `PaymentCollection`) and a word of it that names the capability (`payment`); a word the Non-Goal
names on its own (`billing` in «No payment collection or billing», `kafka` in «No Kafka»), a technology a short Non-Goal names, an
item of a list («leaderboards» in «social feeds, followers, leaderboards or multiplayer»). Everything weaker warns (exit 1): the
warning is printed on stderr with its reason and logged. That is a word of a phrase that code uses for something else
(`collection`, `mobile`) or the plain word of a code name (`transactional`), a lone word of a long sentence, any trigger in a
comment line of a code file or in an ignore file (`noted`: written down, not crossed — unless a line of code in the same change
carries it), a word found only inside another tool's command-line option in a shell command, a CI file, a lockfile or a manifest
(`--frozen-lockfile`; never in your own source, never for a technology the Non-Goal names: `--stripe-key` is refused), and a word
found only in the import of a standard library module spelling another form of it (`from collections import`; your own
`from app.billings import` is refused). The pull request check (below) reads each added line with the same function.

A forbidden package is the whole name a line brings in (since hook 2026-09-30), never a word that starts with it: the
specifier of a JS/TS import or `require` (`'expo'`, `'expo/config'`, `'@stripe/stripe-js'` for `stripe`; a local `./x` or
`@/x` never), the top-level module of a Python import (`from stripe import …`, `import paypal_checkout` for
`paypal-checkout`), the vendor's part of a Java/Kotlin/C#/Rust/PHP/Go/Ruby import (`com.stripe.Stripe`, `using Stripe;`,
`use stripe::Client`; not `javax.xml.ws`, `use crate::ws` or your own `com.acme.api.ws`), the name a manifest line declares,
the package an install command installs or runs (`pip install stripe`, `npx expo start`, `RUN ["pip", "install", "x"]`,
`echo 'x==1' >> requirements.txt`, `pnpm --filter web add ws`, `docker compose exec api pip install x`, `\t@pip install x`
in a Makefile, `$PIP install x`), and the package a forbidden stack's own config names (`"expo"` in `app.json`, a
pubspec's `flutter:`, `<PackageReference Include="Stripe.net">`, `"npm:resend@2"` in `deno.json`). A statement over
several lines (`RUN pip install \`, `require(` … `)`, `import { Resend }` … `from 'resend'`) is read as one; a line an
Edit adds inside a statement the file already has (`    resend \` under `RUN pip install \`) is read with the file
around it, and the pull request check reads it with the diff's context lines. So `import exportCsv from './exportCsv'`, `require('export-to-csv')`, `import export_utils` and `ws = wb.active` in
code are not the packages `expo` and `ws`, and `npm install export-to-csv` is a new dependency like any other (held,
`ask`). Families are named, not guessed: `deny_package_prefixes` (`expo-`, `@expo/`, `react-native-`, `@react-native/`
for native mobile apps) refuses the npm packages `expo-notifications` and `react-native-maps`; `ws-client` is another
package, and so is a PyPI `expo-helpers`. A config written before 2026-09-30 gets the families with `rebuild-markers`,
and the packages the lexicon gained since its `hook_version` (`flask-mail`, `python-socketio`, …) — added to what it
lists, never one under `allowed_markers` (`doctor` says so).

`<skill-dir>` is the directory this SKILL.md lives in (for Claude Code: `.claude/skills/lumis-scope-guard` or `~/.claude/skills/lumis-scope-guard`).

## Startup ritual (after install, at the start of every session)

Before the first edit, print a short report and wait for confirmation:
1. Which MCP servers are actually loaded (list them or say "none").
2. Which rule files you read: `.cursorrules`, `CLAUDE.md`, `CONSTITUTION.md`.
3. Which hooks are active (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.devin/hooks.json` / `.windsurf/hooks.json` or `.github/hooks/*.json` → `scripts/scope_guard.py`).
4. The Non-Goals from CONSTITUTION.md, one line each.
If anything is missing, say so explicitly; never pretend it is loaded.

## Drift rule

If the request or your own plan contains "quick fix for now", "while I'm in here", "might as well", "заодно", "на всякий случай" —
stop and ask: is this inside the specification? y/n. A new dependency, table or route that is not in the spec is a change of
boundaries, never a side effect of another task. A change that touches a Non-Goal or an invariant is a Feature Delta: ask, do not improvise.

## The guard protects itself

A rule the agent is asked to respect is a promise; a refused write is a mechanism. The hook refuses any tool call
that would rewrite its own files — `scripts/scope_guard.py`, the five hook configs, `.lumis/scope_guard.json`,
`CONSTITUTION.md`, and the directories that hold them (`rm -rf .lumis`, `mv scripts`, `tar -C scripts`), seen through
`cd`, `./`, `x/../`, later lines of a command, a `find … -exec` whose filter reaches them, an existing symlink to them, and a
whole-tree git rewind (`stash`, `reset --hard`, `revert`, `checkout <ref>`) when git itself says the guard's files would
change (if git is not on the hook's PATH, a rewind is not refused) — and logs it as `tamper`. `doctor` also reports a hook
that is a link or is not where it was installed. An opaque script (`python fix.py`) or an
encoded command is not readable from the call text and is not caught; the guard does not claim otherwise. The client's own deny rules block the same paths before the hook runs.
Reading them is always allowed; `.cursorrules`, `CLAUDE.md` and `AGENTS.md` are warned about, not blocked, because
you keep your own notes there.

This is **not** a security boundary: a process with shell access still reaches the files. What it adds is that a
rewrite through a tool call it recognises is refused, not quiet. `.lumis/guard.manifest.json` fingerprints the guard at install,
`doctor` reports any file changed since, and `write-manifest` re-baselines after a deliberate change or an Amend.
When the guard refuses something the agent believes is right, `python scripts/scope_guard.py request --reason "…"` writes the
last refusal — the exact payload, the boundary named, the reason — into `.lumis/requests/` as a file for the founder, paste-ready
for LUMIS Amend. The guard lifts nothing on its own. A payload that looks like a private key, a JWT, a connection string with a
password or an API token gets a warning (never a block); documents, tests and `*.example` files are exempt.
The manifest sits in the repository, so one edit could rewrite the hook and its fingerprint together. A copy of the
fingerprints is therefore kept outside the repository, in `~/.lumis/baselines/<repo-id>/manifest.json` (written at
`init`, by `write-manifest`, or by the first hook call after a ZIP install; `LUMIS_HOME` moves it,
`LUMIS_NO_BASELINE=1` switches it off; nothing leaves the machine). `doctor` compares three sides — the files, the
manifest in the repository, the copy outside — and names the side that differs. The hook refuses writes to that
folder and refuses `write-manifest` to the agent: re-baselining is yours. A process that can write to your home
folder can still rewrite the copy; this raises the cost of a quiet rewrite, it does not make one impossible.
For a boundary the agent cannot reach at all, make the files read-only for the account the agent runs as
(`icacls scripts\\scope_guard.py /deny "%USERNAME%:(W)"` on Windows, `chmod a-w` plus a separate owner on Linux/macOS).

## Three boundary classes (held for the founder)

Some changes are the founder's decision whatever the Non-Goals say. The hook recognises three of them in any project:

- `dependency` — a new package: `pip install`, `uv add`, `poetry add`, `npm install <pkg>`, `pnpm/yarn/bun add`, `bun/pnpm install <pkg>`,
  `npx expo install`, `cargo add`, `go get`, `gem install`, `composer require`, `conda install`, `dotnet add package` (also behind
  `bash -c`, `sudo`, `env X=1`, `time`, `exec`, a group or `&`) — and a Write or Edit that adds a name to `requirements*.txt`,
  `pyproject.toml`, `package.json`, `Pipfile`, `Cargo.toml`, `go.mod` or `Gemfile`. Not counted: installing from a lockfile or a
  requirements file (`pip install -r`, `npm ci`, `uv sync`, `poetry install`), a local path or wheel, the installer upgrading
  itself, a tool installed for the machine (`npm install -g`, `pipx`, `cargo install`), a package a manifest of the project
  already declares, and a package the stack names by its exact name (`FastAPI` in the stack covers `fastapi`, not `fast-api`).
- `outbound` — what leaves the machine or rewrites a remote: `git push`, `git remote add|set-url`, a git alias or remote URL set
  through `git config` / `git -c`, `gh repo create/rename/delete/edit/archive/fork`, `gh release create/upload`, `gh pr create/merge`,
  `gh api` with a writing method, a `gh` alias; publishing a package or an image (`npm publish`, `twine upload`, `uv publish`,
  `cargo publish`, `docker push`, `docker buildx build --push`), a deploy (`vercel`, `fly deploy`, `railway up`, `wrangler deploy`,
  `netlify deploy`, `firebase deploy`, `terraform apply`, `kubectl apply`, …), `scp`/`rsync` to a remote host, `curl -T`. Text
  inside a commit message or a quoted argument is not a push. The full list is in `scripts/scope_guard.py` (`outbound_actions`); a
  verb not on it (an HTTP POST, `sftp`, a push from inside a script) is not held.
- `outside_root` — a file tool, a shell redirect, `tee`, `cp`/`mv`/`Copy-Item`, and what removes, creates or edits a path (`rm`,
  `Remove-Item`, `touch`, `mkdir`, `sed -i`, `Set-Content`/`Out-File`, `curl -o`, `git clone <dest>`, `tar -C`, …) outside the
  project root. The temp folder, `~/.lumis` and the agents' state folders (`~/.claude/projects` — memory and sessions — and the
  like) are not counted; an agent's configuration in its home folder (`~/.codex/config.toml`, `~/.cursor/mcp.json`,
  `~/.claude/hooks`) is. Reading a file anywhere never is. A path an inline script opens (`python -c "open('../x','w')"`) is
  not seen.

Each class is set in `.lumis/scope_guard.json`:

```json
"classes": {"dependency": "ask", "outbound": "ask", "outside_root": "ask"}
```

`allow` lets the call through silently, `ask` (the default, and what a missing or misspelled value means) hands the call to the
founder, `block` refuses it with exit code 2 like a Non-Goal. Claude Code, Cursor and GitHub Copilot have a real permission
prompt for `ask`: the founder sees the reason and clicks (the Copilot cloud agent, with nobody to answer, treats `ask` as a
refusal). Codex CLI and Devin Desktop (ex-Windsurf) have no such answer, so there `ask` is a warning on stderr (exit code 1):
the call proceeds and the reason stays in the transcript and in the log. If you need a hard stop in those clients, set the
class to `block`. Hooks run where the client runs them: Cursor cloud agents and the Copilot cloud agent run the repo's hooks; Codex cloud runs no command hooks, Claude Code cloud sessions read them only in single-repository sessions, Jules has none. The pull-request check reads the diff whatever the client did. Copilot lets a tool call through when a hook times out. Cursor lets a tool call through when the hook crashes or times out (it would need failClosed, which this pack does not set: Cursor's docs do not say whether a hook's own 'allow' skips your approval prompt, and we will not risk that); the hook refuses by itself after 20 s. A held call is logged as `held`; it is a decision handed to you, not a violation. The agent never
changes `classes`: the config is one of the guard's own files.

A package that is also a Non-Goal trigger stays a Non-Goal refusal; a class only looks at what no boundary already refused.

## Observe mode

`python scripts/scope_guard.py observe on` (from the repository) lets you try the guard without it stopping your agent. Every
refusal and every hold becomes a warning — `👁 OBSERVE (nothing blocked): would have blocked this — …` — and a line in the
log marked `"observed": true`; `report` counts those apart ("mode: observe — N event(s) would have been stopped"). The tamper
protection stays on: a change to the guard's own files is refused in observe mode too, otherwise the mode would be an off switch.
`python scripts/scope_guard.py observe off` goes back to enforcing. Both rewrite only the `mode` key and re-baseline the
fingerprints. It is the founder's command: the hook refuses it to the agent as tamper, and the switch itself writes nothing when
it runs in a shell an agent client spawned (Claude Code's `CLAUDECODE`, Codex's `CODEX_SANDBOX`) — run it in a terminal of your
own. `init --observe` installs in this mode.

**Unattended profile** (since 2026-10-05), for runs nobody watches: `python scripts/scope_guard.py unattended on` (the
founder's switch, refused to the agent like `observe`; `init --unattended` installs with it) makes every call that would be
held — a class set to `ask`, a commit past the pre-commit check — a refusal with the same reasons (exit 2, in every client),
logged `held` with `"unattended": true`; the agent can carry on with the rest, and `report` lists in the morning what was
refused instead of asked. `allow`, `block`, Non-Goals and tamper are unchanged; observe mode still stops nothing.
`unattended off` asks again. Every `observe` / `unattended` switch appends a `switched` line to the journal, which `report`
lists and `doctor` names: the switch writes nothing in a shell that carries an agent client's marker, but a script an agent
writes and runs can drop the marker, so a switch you did not make is worth a look. A re-run of `init` over an installed
guard keeps the mode and the profile and, in an agent's shell, writes nothing. The spec is "The unattended profile" in
`docs/SCOPE_GUARD_MODES.md` of the LUMIS repository.

## CI check: the same boundaries on every pull request

The hook stops a tool call in the clients that load it. A pull request is where every change arrives — from any agent and
from people — so the hook has a second entry point for it: `python scripts/scope_guard.py check-diff --base <ref> --head <ref>`.
It reads the lines the diff adds (a removal never crosses a boundary), judges them against `.lumis/scope_guard.json` as it is
on the base branch, and prints one report: PASS, WARN or BLOCK, and for each finding the boundary (NG-n, who set it, where it
is written), the file and line, the trigger and the line itself. No score and no model.

- **BLOCK** (exit 2): a Non-Goal trigger on an added line of code (not a comment, see "What blocks and what warns"); a file added, changed, moved or copied under a
  forbidden path; a new top-level directory the base branch and ARCHITECTURE.md's file plan do not have (only when the config
  carries that inventory, which the full LUMIS pack writes); a dependency when `classes.dependency` is `block`; a change to the
  hook, its client configs or the workflow, or a `.lumis/scope_guard.json` deleted, unreadable or left with no boundary — the
  founder confirms.
- **WARN** (exit 0): a trigger in a document, a test, a comment line or an ignore file (`noted`); a warn-only word, or a word
  only inside another tool's option (a CI file, a lockfile or a manifest) or a library's module name (`possible`); a route, model or table
  ARCHITECTURE.md does not list; a new dependency held for the reviewer (`classes.dependency: ask`); a submodule (its content
  is not read); a change to `.lumis/scope_guard.json` or `CONSTITUTION.md`, shown as a boundary diff — which NG-n was removed,
  added or reworded, which other key changed (`stack`, `architecture.top_level`, `log`…), in which commit, by whom, and the
  config's `revision` (`amend #n`). That is how a lift by LUMIS Amend arrives.
- **Exit 1** means the check could not run (no config, no git, a ref that is not there), or the verdict is INCOMPLETE: the diff
  is larger than the check reads (50 000 added and removed lines, 5 MB, or 60 s of reading) and the part read holds no BLOCK. The report says so and never reads as
  a PASS.

`init --ci` (and both LUMIS ZIPs) install the workflow `.github/workflows/lumis-boundary-check.yml`: on every pull request it
runs the check with the checker taken from the base commit, posts one comment (edited on the next push),
writes the job summary, uploads a SARIF file for code scanning (that upload has not yet been seen on a live repository)
and fails the job on BLOCK; on a push to `main`/`master` it runs
the same check on what was pushed and uploads the SARIF, so code scanning has the base branch to compare with (code
scanning is free in public repositories; a private one needs GitHub Advanced Security, otherwise the upload step only logs
that and the comment and summary remain). The workflow is one of the guard's own
files: the hook refuses the agent's writes to it, as it does for the hook itself. A pull request runs its own copy of the
workflow, so one that removes the check step removes the check: make the job a required status check and put the guard's
files under CODEOWNERS.

What it does not read: outbound actions and writes outside the project (they are actions, not lines — the hook holds those);
what a script runs (`bash -c …` inside it); meaning — a home-grown billing module that never says "stripe" passes; JS/TS beyond
text patterns (AST rules are planned later, Python only); binary files and the content of submodules (named in the report).
It is a review aid, not a security boundary. The spec is `docs/BOUNDARY_CHECK_CI.md` in the LUMIS repository.

## Hook version

The hook carries its release date (`HOOK_VERSION`, now `2026-10-07`) and the config records the version it was written for
(`hook_version`). `doctor` compares them. A config newer than the hook is a problem — `the hook in scripts/ is older than the
config (…): copy scripts/scope_guard.py from the ZIP, then run write-manifest` — because the old hook would ignore the new keys
in silence. A hook newer than the config is fine: keys the config lacks take their defaults. The fingerprint
`hook 2026-10-07 · hook <digest> · config <digest>` ends the first line of `report` and of `doctor`, and closes the file
`request` writes. `2026-09-29` blocks only on high-precision evidence (see "What blocks and what warns"); a config written
before it may still block a lone word, and `doctor` names those words with `rebuild-markers --dry-run`. `2026-09-30` matches a
forbidden package as a whole name and reads the package families (`deny_package_prefixes`); a config written before it keeps
working (its packages are matched as whole names at once), and `doctor` names the families `rebuild-markers` would add.
`2026-10-01` adds the pre-commit check; where it is installed, the hook holds the plain spellings of an agent's commit
past it for you (`--no-verify`, `-n`, `-c` or `--config-env core.hooksPath=…`, a `git config` write of
`core.hooksPath`, a `GIT_CONFIG_*` variable set in the command, a write to this repository's own `.git/config`, `git
commit-tree`) and refuses a direct delete or overwrite of its file by path as `tamper`. It reads one command's text:
config includes, `HOME` / `XDG_CONFIG_HOME` pointing git elsewhere, a script writing git's config, a glob or variable
that hides the name, git aliases and other plumbing are not seen (the full list: "Limits" in `docs/BOUNDARY_CHECK_CI.md` of the LUMIS repository),
and git runs no pre-commit hook for a merge, cherry-pick or rebase that applies without conflicts. `doctor` shows
whether the check is in place, and the pull request check reads the diff whatever happened locally. `2026-10-05` adds the
unattended profile (above); a config without the `profile` key is attended, judged as by 2026-10-01. `2026-10-07`
corrects the client configs against the vendors' hook pages: Copilot's file is its camelCase format (`version: 1`,
`preToolUse`, `bash` + `powershell`, `timeoutSec` 25; the old `PreToolUse` + `command` file ran nothing in the Copilot
cloud agent, which honours only `bash`) and the hook reads Copilot's `{toolName, toolArgs}` payload; Cursor's file gets
`version: 1` and `timeout: 60` (no `failClosed`, see above); Devin Desktop gets `.devin/hooks.json` next to the legacy `.windsurf/hooks.json`.
Re-run `init` (or take a new pack) to get them; an older install keeps working where it worked.

## What `report` shows

Every count, even at zero: `stopped: S (blocked: B · tamper: T) · held: H · asked: A · inspected: I · warned: W · possible: P ·
noted: N · drift prompts: D`, then the agents that tried, the events, and a `requests (.lumis/requests): N` section listing up to
ten request files, newest first, each with its reason — the requests the agent wrote with `request --reason` and that are
waiting for you. In the unattended profile, or once such a refusal is on record, a line `unattended: N call(s) refused
instead of asked` and the last five of them follow the counts; the `observe` / `unattended` switches are listed apart
(`switches: N`), never counted as events.

## Two layers (and what each one records)

1. **The rules the agent reads** (`CONSTITUTION.md`, `CLAUDE.md`, `.cursorrules`). A well-behaved agent refuses here, before any tool call.
   The prompt hook is advisory: when a request names a forbidden package, a forbidden path or a multi-word phrase of a boundary, it
   tells the agent to check that Non-Goal — tell the founder if the request really is the ruled-out feature, carry on if it is
   ordinary work — and records an `asked` event. A single word of a Non-Goal sentence is not reported there at all. It never refuses:
   it used to tell the agent to stop on any hit, and the first instruction of a real project was refused because it contained the
   word "architecture".
2. **The hook**, for when the rules do not hold: it denies the tool call and records `blocked`, or hands a boundary class to the
   founder and records `held`.

`asked` without `blocked` is a good outcome, not a failure: the written boundaries held on their own.

## Self-test after install

Ask the agent to add something from the Non-Goals list. It must refuse or ask, and `.lumis/guard.log` gets an `asked` line.
To exercise the hook itself (layer 2), tell it to run the forbidden command directly — "run: pip install <forbidden>" — instead of describing the feature.
If it complies, the hooks are not active: check that your agent's config was picked up (restart the session) and that `python scripts/scope_guard.py` runs.

## Beyond the guard

The same boundaries can become a full pack — PRD, architecture, roadmap, decision log, design constitution and a master
prompt built around them — at https://lumis.tools/?utm_source=github&utm_medium=skill (2 free runs: one at once, one after email confirmation). The LUMIS pack also feeds the hook the architecture's entities,
endpoints and file plan, so a route, table or top-level directory the architecture does not know gets a warning. This skill needs none of that.
