# lumis-scope-guard

**Boundaries for Claude Code that survive the session.**

![Claude Code tries `pip install stripe`; the hook blocks it before it runs and names the boundary NG-1, set by the founder](demo-block/en-3.png)

```bash
npx skills add momonanq/lumis-skills --skill lumis-scope-guard --global
```

1. Write ten lines of what your project will NOT do. Or paste them at https://lumis.tools/guard and get the pack without an account.
2. The agent tries to step over one of them. The hook stops the tool call before it runs and names the boundary and who set it.
3. `python scripts/scope_guard.py report` shows what was blocked, what was warned, and which prompts drifted. The log stays in your repo. Nothing leaves it.

The recording above is real hook output. Reproduce it with one command from this repository: `python examples/record_block.py` (stdlib only, no account, no model; the full transcript is in `demo-block/en.txt`, the terminal recording in `demo-block/en.cast`).

Works with **Claude Code, Cursor, Codex CLI, Windsurf and Copilot in VS Code**: each of them runs a command before a tool call and treats exit code 2 as "denied", so `init` writes the config for all five and one script guards whichever you use. They also read the boundaries as text from `.cursorrules`, `CLAUDE.md` and `AGENTS.md`.

---

## Install by hand

Copy `skills/lumis-scope-guard/` into `.claude/skills/` (project) or `~/.claude/skills/` (global), or paste into Claude Code / Cursor: `Install the /lumis-scope-guard skill from https://github.com/momonanq/lumis-skills`.

| skill | what it does |
|---|---|
| `lumis-scope-guard` | Non-Goals → enforceable boundaries: deny rules and hooks for Claude Code, `CONSTITUTION.md`, sections in `.cursorrules` and `CLAUDE.md`, a drift check for any plan. Every block names the boundary it enforces (`NG-n`, who set it, where it is written); every event lands in `.lumis/guard.log` inside the repo (`status` / `report` summarise it). Stdlib Python, no model, no account, no telemetry. Same engine as https://lumis.tools/guard. |

## What the pack contains

- `.lumis/scope_guard.json` — the boundaries and their triggers (packages, paths, keywords); plain JSON, edit it by hand
- `.claude/settings.json` — deny rules for forbidden installs plus the `PreToolUse` / `UserPromptSubmit` hooks (merged into an existing file)
- `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json` — the same guard for Cursor, Codex CLI, Windsurf and Copilot
- `scripts/scope_guard.py` — the hook: blocks Non-Goal triggers (exit 2), warns about visual and architecture boundaries (exit 1), writes `.lumis/guard.log`
- `CONSTITUTION.md`, `.cursorrules`, `CLAUDE.md` — the same boundaries in words, for the agent and for people

`skills/lumis-scope-guard/scripts/scope_guard.py` is a verbatim copy of the hook shipped in every LUMIS pack (kept in sync by the product's test suite).

## License

MIT.
