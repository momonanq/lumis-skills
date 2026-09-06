# LUMIS skills

Enforceable boundaries for AI coding agents (Claude Code, Cursor, Windsurf). From the makers of https://lumis.tools.

Agent skills in the [skills.sh](https://skills.sh) format (`skills/<name>/SKILL.md`), installable with the skills CLI:

```bash
npx skills add momonanq/lumis-skills --skill lumis-scope-guard --global
```

or by pasting into Claude Code / Cursor: `Install the /lumis-scope-guard skill from https://github.com/momonanq/lumis-skills`.

| skill | what it does |
|---|---|
| `lumis-scope-guard` | Non-Goals → enforceable boundaries: deny rules and hooks for Claude Code, `CONSTITUTION.md`, a `.cursorrules` section, a drift check for any plan. Stdlib Python, no model, no account. Same engine as https://lumis.tools/guard. |

`skills/lumis-scope-guard/scripts/scope_guard.py` is a verbatim copy of `lumis/exports/scope_guard.py` (kept in sync by `test_skill_pack.py`).
