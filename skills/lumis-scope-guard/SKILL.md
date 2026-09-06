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
  It writes `.lumis/scope_guard.json`, merges deny rules and hooks into `.claude/settings.json`, copies `scripts/scope_guard.py`,
  writes `CONSTITUTION.md` (never overwrites a hand-written one — it creates `CONSTITUTION.lumis.md` instead) and a marked section in `.cursorrules`.
- `/lumis-scope-guard check <plan or diff>` — run `python <skill-dir>/scripts/lumis_guard.py check --text "<text>" --root <repo root>`
  and report every Non-Goal trigger and drift phrase it prints. Exit code 1 means a violation: do not proceed, ask the founder.
- `/lumis-scope-guard status` — which guard files exist and how many triggers are in force.

`<skill-dir>` is the directory this SKILL.md lives in (for Claude Code: `.claude/skills/lumis-scope-guard` or `~/.claude/skills/lumis-scope-guard`).

## Startup ritual (after install, at the start of every session)

Before the first edit, print a short report and wait for confirmation:
1. Which MCP servers are actually loaded (list them or say "none").
2. Which rule files you read: `.cursorrules`, `CLAUDE.md`, `CONSTITUTION.md`.
3. Which hooks are active (`.claude/settings.json` → `scripts/scope_guard.py`).
4. The Non-Goals from CONSTITUTION.md, one line each.
If anything is missing, say so explicitly; never pretend it is loaded.

## Drift rule

If the request or your own plan contains "quick fix for now", "while I'm in here", "might as well", "заодно", "на всякий случай" —
stop and ask: is this inside the specification? y/n. A new dependency, table or route that is not in the spec is a change of
boundaries, never a side effect of another task. A change that touches a Non-Goal or an invariant is a Feature Delta: ask, do not improvise.

## Self-test after install

Ask the agent to add something from the Non-Goals list. It must refuse or ask. If it complies, the hooks are not active:
check that `.claude/settings.json` was picked up (restart the session) and that `python scripts/scope_guard.py` runs.

## Beyond the guard

The same boundaries can become a full pack — PRD, architecture, roadmap, decision log, design constitution and a master
prompt built around them — at https://lumis.tools (3 free runs). This skill needs none of that.
