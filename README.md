# lumis-scope-guard

**Boundaries your coding agent can't step over.**

![One Non-Goal, five clients: Claude Code, Cursor, Codex CLI, Windsurf and Copilot each try `pip install stripe`; the same hook blocks all five before the call runs and names boundary NG-1, set by the founder](demo-block/agents-6.png)

```bash
npx skills add momonanq/lumis-skills --skill lumis-scope-guard --global
```

1. Write ten lines of what your project will NOT do. Or paste them at https://lumis.tools/guard and get the pack without an account.
2. The agent tries to step over one of them. The hook stops the tool call before it runs and names the boundary and who set it. One script, five clients: Claude Code, Cursor, Codex CLI, Windsurf, Copilot in VS Code.
3. `python scripts/scope_guard.py report` shows what was blocked, what was merely asked for, what was warned, and which agent tried. The log stays in your repo. Nothing leaves it.

Two layers, both recorded: the agent reads the boundaries and usually refuses before it touches anything (`asked`); when it does not, the hook denies the tool call (`blocked`).

The recording above is real hook output. Reproduce it with one command from this repository: `python examples/record_block.py` (stdlib only, no account, no model; transcripts in `demo-block/`).

The pack writes hook configs for five clients (`.claude/settings.json`, `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json`); the same script answers each client's call format with exit code 2. Run `python scripts/scope_guard.py doctor` to check the wiring in your repo. The proof that counts is your own client's refusal: if you see it, send a screenshot and we list the client as verified. Any other editor gets the same boundaries as text rules: `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, plus a manual `check`.

---

## Install by hand

Copy `skills/lumis-scope-guard/` into `.claude/skills/` (project) or `~/.claude/skills/` (global), or paste into Claude Code / Cursor: `Install the /lumis-scope-guard skill from https://github.com/momonanq/lumis-skills`.

| skill | what it does |
|---|---|
| `lumis-scope-guard` | Non-Goals → enforceable boundaries: hook configs for five agents, `CONSTITUTION.md`, sections in `.cursorrules` and `CLAUDE.md`, a drift check for any plan. Every block names the boundary it enforces (`NG-n`, who set it, where it is written); every event lands in `.lumis/guard.log` inside the repo — `status` and `report` summarise it, `doctor` checks the wiring. Stdlib Python, no model, no account, no telemetry. Same engine as https://lumis.tools/guard. |

## What the pack contains

- `.lumis/scope_guard.json` — the boundaries and their triggers (packages, paths, keywords); plain JSON, edit it by hand
- `.claude/settings.json` — deny rules for forbidden installs plus the `PreToolUse` / `UserPromptSubmit` hooks (merged into an existing file)
- `.cursor/hooks.json`, `.codex/hooks.json`, `.windsurf/hooks.json`, `.github/hooks/lumis-scope-guard.json` — the same guard for Cursor, Codex CLI, Windsurf and Copilot
- `scripts/scope_guard.py` — the hook: blocks Non-Goal triggers (exit 2), warns about visual and architecture boundaries (exit 1), writes `.lumis/guard.log`
- `CONSTITUTION.md`, `.cursorrules`, `CLAUDE.md` — the same boundaries in words, for the agent and for people

`skills/lumis-scope-guard/scripts/scope_guard.py` is a verbatim copy of the hook shipped in every LUMIS pack (kept in sync by the product's test suite).

## License

MIT.
