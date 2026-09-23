# lumis-scope-guard

**Boundaries your coding agent can't step over.**

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

`doctor` compares the hook's version (`2026-09-23`) with the `hook_version` in the config and tells you when the hook in `scripts/` is older than the config it reads. `report` prints every count, even at zero, and lists the requests the agent left for you in `.lumis/requests/`.

The recording above is real hook output. Reproduce it with one command from this repository: `python examples/record_block.py` (stdlib only, no account, no model; transcripts in `demo-block/`).

The pack writes hook configs for five clients (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json`); the same script answers each client's call format with exit code 2. Run `python scripts/scope_guard.py doctor` to check the wiring in your repo. The proof that counts is your own client's refusal: if you see it, send a screenshot and we list the client as verified. Any other editor gets the same boundaries as text rules: `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, plus a manual `check`.

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

`skills/lumis-scope-guard/scripts/scope_guard.py` is a verbatim copy of the hook shipped in every LUMIS pack (kept in sync by the product's test suite).

## License

MIT.
