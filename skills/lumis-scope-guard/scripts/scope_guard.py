#!/usr/bin/env python3
"""LUMIS Scope Guard — hook script shipped inside the starter repository (stdlib only).

Wired from .claude/settings.json (Claude Code hooks):
  * PreToolUse (Edit/Write/MultiEdit/Bash)  -> `python scripts/scope_guard.py pre-tool`
        blocks (exit 2) when the change or command touches a Non-Goal trigger:
        forbidden packages, paths or keywords listed in .lumis/scope_guard.json
        visual Non-Goals from DESIGN_CONSTITUTION.md only warn (exit 1), they never block
  * UserPromptSubmit                         -> `python scripts/scope_guard.py prompt`
        adds a warning to the context when the prompt contains a drift phrase
        ("quick fix for now", "while I'm in here", ...) — the agent must confirm the task is in scope.

The same config feeds `sentry_cli.py` and the LUMIS Convergence Audit. Edit .lumis/scope_guard.json to tune;
re-run the consilium to regenerate it from the Constitution.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; the reports carry emoji
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_config() -> dict:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    for candidate in (root / ".lumis" / "scope_guard.json", Path(__file__).resolve().parents[1] / ".lumis" / "scope_guard.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                break
    return {"non_goals": [], "keywords": [], "deny_packages": [], "deny_paths": [], "drift_phrases": [], "design_non_goals": []}


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def text_of_tool_input(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """(searchable text, file path) for a tool call."""
    if tool_name == "Bash":
        return str(tool_input.get("command", "")), ""
    path = str(tool_input.get("file_path", ""))
    parts = [str(tool_input.get("content", "")), str(tool_input.get("new_string", ""))]
    for edit in tool_input.get("edits", []) or []:
        parts.append(str(edit.get("new_string", "")))
    return "\n".join(parts), path


def check_pre_tool(cfg: dict, payload: dict) -> list[str]:
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    text, path = text_of_tool_input(tool_name, tool_input)
    low = text.lower()
    hits: list[str] = []
    for pkg in cfg.get("deny_packages", []):
        if re.search(rf"(^|[\s'\"/@=])" + re.escape(pkg.lower()) + r"([\s'\"@=:]|$)", low) or f"import {pkg.lower()}" in low or f"from {pkg.lower()}" in low or f"require('{pkg.lower()}" in low or f'require("{pkg.lower()}' in low:
            hits.append(f"forbidden dependency '{pkg}'")
    for deny_path in cfg.get("deny_paths", []):
        if deny_path and (deny_path.lower() in path.lower() or deny_path.lower() in low):
            hits.append(f"forbidden path '{deny_path}'")
    for kw in cfg.get("keywords", []):
        if kw and re.search(r"(?<![\w-])" + re.escape(kw.lower()) + r"(?![\w-])", low):
            hits.append(f"Non-Goal keyword '{kw}'")
    return sorted(set(hits))


UI_FILE_SUFFIXES = (".css", ".scss", ".html", ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".js", ".ts")


def check_design(cfg: dict, payload: dict) -> list[str]:
    """Visual Non-Goals from DESIGN_CONSTITUTION.md: a warning when UI code contains a lexicon substring."""
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    text, path = text_of_tool_input(tool_name, tool_input)
    if tool_name == "Bash" or (path and not path.lower().endswith(UI_FILE_SUFFIXES)):
        return []
    low = text.lower()
    hits: list[str] = []
    for rule in cfg.get("design_non_goals", []) or []:
        for needle in rule.get("lexicon", []) or []:
            if needle and needle.lower() in low:
                hits.append(f"'{needle}' → {rule.get('rule', 'visual Non-Goal')}")
                break
    return hits


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre-tool"
    cfg = load_config()
    payload = read_stdin_json()
    if mode == "prompt":
        prompt = str(payload.get("prompt", ""))
        phrases = [p for p in cfg.get("drift_phrases", []) if p.lower() in prompt.lower()]
        if phrases:
            print(
                "⚠️ LUMIS Scope Guard: the request contains drift phrases "
                + ", ".join(f"'{p}'" for p in phrases[:4])
                + ". Before changing code, confirm the task is inside PRD.md scope and does not touch a Non-Goal from CONSTITUTION.md; "
                "if it is not in scope, say so and stop."
            )
        return 0
    design_hits = check_design(cfg, payload)
    if design_hits:
        sys.stderr.write(
            "🎨 LUMIS Design Constitution warning (DESIGN_CONSTITUTION.md, section 5): "
            + "; ".join(design_hits)
            + ". Keep the visual contract or record a Feature Delta.\n"
        )
    hits = check_pre_tool(cfg, payload)
    if hits:
        sys.stderr.write(
            "⛔ LUMIS Scope Guard blocked this change (CONSTITUTION.md, Article I — Non-Goals): "
            + "; ".join(hits)
            + ". Re-run the LUMIS consilium to change the boundaries instead of bypassing them.\n"
        )
        return 2
    return 1 if design_hits else 0  # 1 = non-blocking: the warning is shown, the change proceeds


if __name__ == "__main__":
    raise SystemExit(main())
