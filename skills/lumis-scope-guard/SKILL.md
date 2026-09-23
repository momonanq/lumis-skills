---
name: lumis-scope-guard
description: Turn a list of Non-Goals into enforceable boundaries for the coding agent — deny rules and hooks that block forbidden dependencies, paths and keywords, a CONSTITUTION.md and a .cursorrules section — plus a startup ritual and a drift check for any plan. No model, no account, stdlib Python.
---

# LUMIS scope guard

Use this skill when the user wants the agent to **stay inside agreed boundaries**: "this product must never have X",
"lock the scope", "the agent keeps adding features", or when a specification exists and only guard rails are missing.
Prompts alone do not hold; this installs hooks that block the change before it happens.

## Commands

- `/lumis-scope-guard init` — ask for the Non-Goals (one per line), optional invariants and stack, then run:
  `python <skill-dir>/scripts/lumis_guard.py init --project "<name>" --non-goals "<a; b; c>" [--invariants "<x; y>"] [--stack "<stack>"] --root <repo root>`
  It writes `.lumis/scope_guard.json`, merges deny rules and hooks into `.claude/settings.json`, writes hook configs for Cursor
  (`.cursor/hooks.json`), Codex (`.codex/hooks.json`), Windsurf (`.windsurf/hooks.json`) and Copilot
  (`.github/hooks/lumis-scope-guard.json`) — all of them deny on exit code 2, so one script guards every agent — copies `scripts/scope_guard.py`,
  writes `CONSTITUTION.md` (never overwrites a hand-written one — it creates `CONSTITUTION.lumis.md` instead) and marked sections in `.cursorrules` and `CLAUDE.md` (existing content is kept).
  Add `--observe` to install in observe mode (below). The last line of the output names the hook version, the mode and the classes:
  `Hook 2026-09-23 · mode: enforce · classes: ...`.
- `/lumis-scope-guard check <plan or diff>` — run `python <skill-dir>/scripts/lumis_guard.py check --text "<text>" --root <repo root>`
  and report every Non-Goal trigger and drift phrase it prints. Exit code 1 means a violation: do not proceed, ask the founder.
- `/lumis-scope-guard doctor` — run `python <skill-dir>/scripts/scope_guard.py doctor --root <repo root>` (or `python scripts/scope_guard.py doctor`
  from the repository): checks that the hook script, `.lumis/scope_guard.json` and each agent's config are present and valid, and that the
  interpreter they call is on PATH. It checks the wiring only — whether your client actually honours the hook is proven by the self-test below.
  It also prints the mode, the three classes and the hook's version against the `hook_version` the config was written for (see
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

`<skill-dir>` is the directory this SKILL.md lives in (for Claude Code: `.claude/skills/lumis-scope-guard` or `~/.claude/skills/lumis-scope-guard`).

## Startup ritual (after install, at the start of every session)

Before the first edit, print a short report and wait for confirmation:
1. Which MCP servers are actually loaded (list them or say "none").
2. Which rule files you read: `.cursorrules`, `CLAUDE.md`, `CONSTITUTION.md`.
3. Which hooks are active (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json` or `.github/hooks/*.json` → `scripts/scope_guard.py`).
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

This is **not** a security boundary: a process with shell access still reaches the files. What it guarantees is
that no rewrite happens quietly through a tool call. `.lumis/guard.manifest.json` fingerprints the guard at install,
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
founder, `block` refuses it with exit code 2 like a Non-Goal. Only Claude Code and Cursor have a real permission prompt for `ask`:
the founder sees the reason and clicks. Codex CLI, Windsurf and Copilot have no such answer, so there `ask` is a warning on
stderr (exit code 1): the call proceeds and the reason stays in the transcript and in the log. If you need a hard stop in those
clients, set the class to `block`. (For Copilot this is the cautious reading: its hook schema may have an `ask` too, which has not
been checked against a live client.) A held call is logged as `held`; it is a decision handed to you, not a violation. The agent never
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

## Hook version

The hook carries its release date (`HOOK_VERSION`, now `2026-09-23`) and the config records the version it was written for
(`hook_version`). `doctor` compares them. A config newer than the hook is a problem — `the hook in scripts/ is older than the
config (…): copy scripts/scope_guard.py from the ZIP, then run write-manifest` — because the old hook would ignore the new keys
in silence. A hook newer than the config is fine: keys the config lacks take their defaults. The fingerprint
`hook 2026-09-23 · hook <digest> · config <digest>` ends the first line of `report` and of `doctor`, and closes the file
`request` writes.

## What `report` shows

Every count, even at zero: `stopped: S (blocked: B · tamper: T) · held: H · asked: A · inspected: I · warned: W · possible: P ·
noted: N · drift prompts: D`, then the agents that tried, the events, and a `requests (.lumis/requests): N` section listing up to
ten request files, newest first, each with its reason — the requests the agent wrote with `request --reason` and that are
waiting for you.

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
