#!/usr/bin/env python3
"""LUMIS scope guard — standalone installer and checker (stdlib only).

    python lumis_guard.py init  --project "Name" --non-goals "no marketplace; no multi-tenancy" [--invariants "..."] [--stack "..."] [--root .]
    python lumis_guard.py check --text "the plan or diff to check" [--root .]
    python lumis_guard.py status [--root .]

`init` writes into the repository root: .lumis/scope_guard.json (triggers), .claude/settings.json (deny rules + hooks,
merged into an existing file), scripts/scope_guard.py (the hook), CONSTITUTION.md (Non-Goals and invariants verbatim)
hook configs for Cursor / Codex / Windsurf / Copilot,
and LUMIS sections in .cursorrules and CLAUDE.md (existing content kept). `check` reports Non-Goal triggers and drift phrases in a text. No network, no model.
Same engine as https://lumis.tools/guard.

Needs `scope_guard.py` in this same folder: the hook it installs is also where the boundary→markers derivation
and the capability lexicon live, so there is one copy of them rather than two.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; the reports carry emoji
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent

# --- the derivation lives in the hook, not here -------------------------------------------------------------
# The capability lexicon and the boundary→markers rules used to be copied into this file, which made three
# copies of the same word lists: the product's (`lumis/core/boundary_markers.py`), the hook's and this one. They
# now live in `scope_guard.py`, the file sitting next to this one — the hook needs them for `rebuild-markers`,
# and a generated pack ships the hook alone, so the hook is the only place both installers can reach.
#
# Loaded by path, not through `sys.path`: `test_skill_pack.py` loads *this* file by spec inside a pytest process,
# where a bare `import scope_guard` would bind to whatever `sys.modules` already holds. `scope_guard.py` is safe
# to import — its only import-time effect is the stdout/stderr reconfigure this file already does itself, and its
# `main()` is behind `if __name__ == "__main__"`.
import importlib.util as _importlib_util

_spec = _importlib_util.spec_from_file_location("lumis_scope_guard_core", HERE / "scope_guard.py")
if _spec is None or _spec.loader is None:  # pragma: no cover - only when the skill folder is broken
    raise SystemExit(f"scope_guard.py is missing next to {Path(__file__).name}: reinstall the skill.")
guard = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

CAPABILITY_TRIGGERS = guard.CAPABILITY_TRIGGERS
FUNCTION_WORDS = guard.FUNCTION_WORDS
GENERIC_ARCHITECTURAL_STOPWORDS = guard.GENERIC_ARCHITECTURAL_STOPWORDS
COMMON_CODE_WORDS = guard.COMMON_CODE_WORDS
TECHNOLOGY_WORDS = guard.TECHNOLOGY_WORDS
SHORT_BOUNDARY_WORDS = guard.SHORT_BOUNDARY_WORDS
MARKERS_PER_BOUNDARY = guard.MARKERS_PER_BOUNDARY
WARN_MARKERS_PER_BOUNDARY = guard.WARN_MARKERS_PER_BOUNDARY
normalize = guard.normalize
glue_technologies = guard.glue_technologies
prescribes = guard.prescribes
stack_vocabulary = guard.stack_vocabulary
markers_for = guard.markers_for

DRIFT_PHRASES = (
    "quick fix for now", "for now", "while i'm in here", "while i am in here", "since i already touched",
    "might as well", "we might as well", "let's also", "lets also", "also add", "bonus:", "nice to have",
    "temporary hack", "temporary workaround", "just in case", "future-proof", "future proof", "to be safe",
    "refactor everything", "rewrite from scratch", "while we're at it", "while we are at it", "one more thing",
    "small addition", "quick win", "easy to add", "it would be nice", "in addition to",
    "пока что", "быстрый фикс", "заодно", "раз уж я здесь", "раз уж полез", "давай ещё", "давай еще", "заодно добавим",
    "на всякий случай", "на будущее", "временный костыль", "временное решение", "перепишу всё", "перепишем с нуля",
    "было бы неплохо", "небольшая доработка", "заодно поправлю", "мелочь, но",
)
GUARD_SELF_PATHS = (".lumis/scope_guard.json", ".lumis/guard.log", ".lumis/guard.manifest.json",
                    "scripts/scope_guard.py", ".claude/settings.json", ".cursor/hooks.json",
                    ".codex/hooks.json", ".windsurf/hooks.json", ".github/hooks/lumis-scope-guard.json",
                    "CONSTITUTION.md")
MARK_START = "# --- LUMIS scope guard (generated; edit .lumis/scope_guard.json instead) ---"
MARK_END = "# --- end LUMIS scope guard ---"
MD_START = "<!-- LUMIS scope guard (generated; edit .lumis/scope_guard.json instead) -->"
MD_END = "<!-- end LUMIS scope guard -->"


def split_items(text: str) -> list[str]:
    parts = re.split(r"[;\n]", text or "")
    out: list[str] = []
    for p in parts:
        t = re.sub(r"^[\s\-*•·\d.)]+", "", p).strip()[:240]
        if len(t) > 2 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:25]


def guard_config(project: str, non_goals: list[str], stack: str = "") -> dict:
    """Triggers for the hook. Two classes leave here: `keywords` stop a tool call (exit 2) — the curated concept
    lexicon, phrases, and the words of a short boundary; `warn_keywords` only warn (exit 1) — a lone word out of a
    long sentence, a possible match for a human to judge. A hook reading a config without the second key behaves
    exactly as it always did."""
    packages: list[str] = []
    paths: list[str] = []
    keywords: list[str] = []
    warn_keywords: list[str] = []
    matched: dict[str, list[str]] = {}
    boundaries = [{"id": f"NG-{i}", "text": ng, "origin": "founder", "source": "CONSTITUTION.md, Article I"} for i, ng in enumerate(non_goals, 1)]
    trigger_sources: dict[str, str] = {}  # trigger -> boundary id, so a block can say which Non-Goal it enforces
    vocabulary = stack_vocabulary(stack)
    for b in boundaries:
        ng = b["text"]
        low = ng.lower()
        for cap, spec in CAPABILITY_TRIGGERS.items():
            if any(m in low for m in spec["match"]):
                packages += spec["packages"]
                paths += spec["paths"]
                keywords += spec["keywords"]
                matched.setdefault(cap, []).append(ng)
                for t in spec["packages"] + spec["paths"] + spec["keywords"]:
                    trigger_sources.setdefault(t.lower(), b["id"])
        blocking, warning = markers_for(ng, vocabulary)
        for text in blocking:
            keywords.append(text)
            trigger_sources.setdefault(text, b["id"])
        for text in warning:
            warn_keywords.append(text)
            trigger_sources.setdefault(text, b["id"])
    dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
    blocking_keywords = dedupe(keywords)[:320]
    # a marker that blocks is never also a warning: the stronger verdict wins, one trigger keeps one meaning
    warn_only = [w for w in dedupe(warn_keywords) if w not in set(blocking_keywords)][:240]
    return {"project": project, "generated": date.today().isoformat(), "source": "lumis-scope-guard skill",
            "non_goals": non_goals, "boundaries": boundaries, "capabilities": matched, "deny_packages": dedupe(packages), "deny_paths": dedupe(paths),
            "keywords": blocking_keywords, "warn_keywords": warn_only,
            "trigger_sources": trigger_sources, "drift_phrases": list(DRIFT_PHRASES), "design_non_goals": [],
            "log": ".lumis/guard.log"}


def explain(cfg: dict, trigger: str) -> str:
    bid = (cfg.get("trigger_sources") or {}).get(trigger.lower())
    for b in cfg.get("boundaries") or []:
        if bid and b.get("id") == bid:
            return f" → {bid} \"{b.get('text', '')}\" (set by the founder; {b.get('source', 'CONSTITUTION.md, Article I')})"
    return ""


def read_log(root: Path, cfg: dict) -> list[dict]:
    target = root / str(cfg.get("log") or ".lumis/guard.log")
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


HOOK_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash|mcp__.*"  # an MCP server writes files too


def hook_command(mode: str, agent: str = "", hook_path: str = "scripts/scope_guard.py", windows: bool = False) -> str:
    """No interpreter exists on every machine: a stock macOS or Debian box has no bare `python` (the hook then never
    starts and the client treats it as a non-blocking error), Windows has no `python3`. The POSIX line asks which one
    is there; the Windows/PowerShell line, where a client offers one, keeps `python`."""
    tail = f"{hook_path} {mode}" + (f" --agent {agent}" if agent else "")
    if windows:
        return f"python {tail}"
    return f"command -v python >/dev/null 2>&1 && exec python {tail} || exec python3 {tail}"


def agent_hook_files(hook_path: str = "scripts/scope_guard.py") -> dict[str, dict]:
    """Hook configs for the agents that can stop a tool call before it runs. All of them deny on exit code 2,
    so one script serves Cursor, Codex, Windsurf and Copilot; Claude Code is configured in .claude/settings.json."""
    pre = hook_command("pre-tool", "cursor", hook_path)
    ws = {"command": hook_command("pre-tool", "windsurf", hook_path),
          "powershell": hook_command("pre-tool", "windsurf", hook_path, windows=True), "show_output": True}
    return {
        ".cursor/hooks.json": {"hooks": {
            "preToolUse": [{"command": pre}],
            "beforeShellExecution": [{"command": pre}],
            "beforeMCPExecution": [{"command": pre}],
            "beforeSubmitPrompt": [{"command": hook_command("prompt", "cursor", hook_path)}],
        }},
        ".codex/hooks.json": {"hooks": {"PreToolUse": [{"command": hook_command("pre-tool", "codex", hook_path)}]}},
        ".windsurf/hooks.json": {"hooks": {
            "pre_run_command": [dict(ws)],
            "pre_write_code": [dict(ws)],
            "pre_mcp_tool_use": [dict(ws)],
            "pre_user_prompt": [{"command": hook_command("prompt", "windsurf", hook_path),
                                 "powershell": hook_command("prompt", "windsurf", hook_path, windows=True), "show_output": True}],
        }},
        ".github/hooks/lumis-scope-guard.json": {"hooks": {"PreToolUse": [{"type": "command", "command": hook_command("pre-tool", "copilot", hook_path), "timeout": 15}]}},
    }


def claude_settings(cfg: dict, existing: dict | None) -> dict:
    deny: list[str] = []
    for pkg in cfg.get("deny_packages", []):
        deny += [f"Bash(npm install {pkg}*)", f"Bash(npm i {pkg}*)", f"Bash(pnpm add {pkg}*)", f"Bash(yarn add {pkg}*)", f"Bash(pip install {pkg}*)", f"Bash(uv add {pkg}*)"]
    for path in cfg.get("deny_paths", []):
        deny += [f"Edit({path}**)", f"Write({path}**)"]
    for own in GUARD_SELF_PATHS:  # the guard's own files: refused by the client before the hook even runs
        deny += [f"Edit({own})", f"Write({own})"]
    pre = {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": hook_command("pre-tool")}]}
    prompt = {"hooks": [{"type": "command", "command": hook_command("prompt")}]}
    settings = dict(existing or {})
    perms = dict(settings.get("permissions") or {})
    perms["deny"] = list(dict.fromkeys(list(perms.get("deny") or []) + deny))
    settings["permissions"] = perms
    hooks = dict(settings.get("hooks") or {})
    for key, entry in (("PreToolUse", pre), ("UserPromptSubmit", prompt)):
        current = list(hooks.get(key) or [])
        if not any("scope_guard.py" in json.dumps(h) for h in current):
            current.append(entry)
        hooks[key] = current
    settings["hooks"] = hooks
    settings.setdefault("$comment", "LUMIS scope guard: Non-Goals as deny rules + hooks. Tune .lumis/scope_guard.json; do not hand-edit the deny list.")
    return settings


def constitution(project: str, non_goals: list[str], invariants: list[str], stack: str) -> str:
    ng = "\n".join(f"- ⛔ **FORBIDDEN:** {x}" for x in non_goals) or "- (none)"
    inv = "\n".join(f"- 🔒 **INVARIANT:** {x}" for x in invariants) or "- (none declared)"
    stack_line = f"- **Approved stack (mandated by the founder):** {stack}" if stack else "- see the project's own specification"
    return f"""# 🏛️ CONSTITUTION: {project}
> Boundaries set by the founder on {date.today().isoformat()} (LUMIS scope guard skill, no model involved — every line is the founder's own).

## 📜 ARTICLE I: EXPLICIT NON-GOALS (set by the founder)
{ng}

## 📜 ARTICLE II: APPROVED STACK
{stack_line}

## 📜 ARTICLE III: REQUIRED INVARIANTS
{inv}

## 📜 ARTICLE IV: DRIFT RULE
If a request or your own plan contains "quick fix for now", "while I'm in here", "might as well" — stop and ask: is this inside the specification? y/n.
A change that touches Article I or III is a Feature Delta: ask the founder, never improvise. The hooks in `.claude/settings.json` run
`scripts/scope_guard.py` on every edit and block the triggers listed in `.lumis/scope_guard.json`.
"""


def cursorrules_section(project: str, non_goals: list[str], invariants: list[str], stack: str) -> str:
    lines = [MARK_START, f"# {project}: boundaries set by the founder", "",
             "## Startup ritual (before the first edit)",
             "List loaded MCP servers, rule files (.cursorrules, CLAUDE.md, CONSTITUTION.md) and active hooks, restate the Non-Goals, then wait for confirmation.",
             "", "## Non-Goals (never implement, never suggest)"]
    lines += [f"- {x}" for x in non_goals] or ["- (none)"]
    if stack:
        lines += ["", "## Stack (user-mandated; do not add servers, frameworks or build steps beyond it)", f"- {stack}"]
    if invariants:
        lines += ["", "## Invariants"] + [f"- {x}" for x in invariants]
    lines += ["", "## Drift rule",
              "If the request or your own plan contains 'quick fix for now', 'while I'm in here', 'might as well', 'заодно', 'на всякий случай' — stop and ask: is this in scope? y/n.",
              MARK_END, ""]
    return "\n".join(lines)


def claude_md_section(project: str, non_goals: list[str], invariants: list[str], stack: str) -> str:
    """The same boundaries for Claude Code's CLAUDE.md (merged into an existing file, never replacing it)."""
    lines = [MD_START, f"## Boundaries of {project} (LUMIS scope guard)", "",
             "Before the first edit: list the loaded rule files (.cursorrules, CLAUDE.md, CONSTITUTION.md) and active hooks, restate the Non-Goals below, wait for confirmation.",
             "", "### Non-Goals (never implement, never suggest)"]
    lines += [f"- {x}" for x in non_goals] or ["- (none)"]
    if stack:
        lines += ["", "### Stack (user-mandated; do not add servers, frameworks or build steps beyond it)", f"- {stack}"]
    if invariants:
        lines += ["", "### Invariants"] + [f"- {x}" for x in invariants]
    lines += ["", "### Guard",
              "`.claude/settings.json` runs `scripts/scope_guard.py` before every edit and command; a Non-Goal trigger is blocked with the boundary named (NG-n). "
              "Events land in `.lumis/guard.log` (`python scripts/scope_guard.py report`). Never edit the hook or the deny rules to get past them.",
              "If the request or your own plan contains 'quick fix for now', 'while I'm in here', 'might as well', 'заодно', 'на всякий случай' — stop and ask: is this in scope? y/n.",
              MD_END, ""]
    return "\n".join(lines)


def upsert_block(path: Path, block: str, start_mark: str = MARK_START, end_mark: str = MARK_END) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if start_mark in text and end_mark in text:
        start, end = text.index(start_mark), text.index(end_mark) + len(end_mark)
        text = text[:start] + block.rstrip("\n") + text[end:]
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    path.write_text(text, encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    non_goals = split_items(args.non_goals)
    if not non_goals:
        print("Add at least one Non-Goal: --non-goals \"no marketplace; no multi-tenancy\"", file=sys.stderr)
        return 2
    invariants = split_items(args.invariants or "")
    stack = (args.stack or "").strip()[:200]
    project = (args.project or root.name).strip()[:60]
    cfg = guard_config(project, non_goals, stack)
    (root / ".lumis").mkdir(parents=True, exist_ok=True)
    (root / ".lumis" / "scope_guard.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # the log records what an agent attempted (secrets stripped): local evidence, shared deliberately, not by accident
    (root / ".lumis" / ".gitignore").write_text("# local evidence, not telemetry: keep the guard log out of commits\nguard.log\n", encoding="utf-8")
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    settings_path = root / ".claude" / "settings.json"
    existing = None
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
    settings_path.write_text(json.dumps(claude_settings(cfg, existing), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "scope_guard.py").write_text((HERE / "scope_guard.py").read_text(encoding="utf-8"), encoding="utf-8")
    for rel, content in agent_hook_files().items():  # Cursor, Codex, Windsurf, Copilot — same hook, same exit code 2
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        merged = content
        if target.exists():  # keep the user's own hooks, add ours per event
            try:
                current = json.loads(target.read_text(encoding="utf-8"))
                hooks = dict(current.get("hooks") or {})
                for event, entries in content["hooks"].items():
                    existing_entries = list(hooks.get(event) or [])
                    if not any("scope_guard.py" in json.dumps(h) for h in existing_entries):
                        existing_entries += entries
                    hooks[event] = existing_entries
                current["hooks"] = hooks
                merged = current
            except Exception:
                merged = content
        target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    const_path = root / "CONSTITUTION.md"
    if const_path.exists() and "LUMIS" not in const_path.read_text(encoding="utf-8"):
        const_path = root / "CONSTITUTION.lumis.md"  # never overwrite a hand-written constitution
    const_path.write_text(constitution(project, non_goals, invariants, stack), encoding="utf-8")
    upsert_block(root / ".cursorrules", cursorrules_section(project, non_goals, invariants, stack))
    upsert_block(root / "CLAUDE.md", claude_md_section(project, non_goals, invariants, stack), MD_START, MD_END)
    # fingerprints of the guard's own files, read back from disk so newline handling cannot skew them
    import hashlib
    from datetime import datetime, timezone
    tracked = {}
    for rel in GUARD_SELF_PATHS:
        target = root / rel
        if target.is_file() and rel not in (".lumis/guard.log", ".lumis/guard.manifest.json"):
            tracked[rel] = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    (root / ".lumis" / "guard.manifest.json").write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "sha256/16",
        "note": "Written at install and by LUMIS Amend. `scope_guard.py doctor` compares it; a mismatch means the "
                "guard was edited outside Amend. This records tampering, it cannot prevent it.",
        "files": tracked,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # the same fingerprints, copied outside the repository by the installed hook (~/.lumis/baselines/<repo-id>/):
    # one edit of the repository can rewrite the hook and its manifest together, it cannot reach this copy
    import os
    import subprocess
    outside = subprocess.run([sys.executable, "-X", "utf8", str(root / "scripts" / "scope_guard.py"), "write-manifest"], cwd=root,
                             env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, capture_output=True, text=True, encoding="utf-8")
    print(f"LUMIS scope guard installed in {root}")
    for line in (outside.stdout or "").splitlines():
        if line.startswith("baseline outside the repository"):
            print("  " + line)
    print(f"  Non-Goals: {len(non_goals)} · invariants: {len(invariants)} · deny packages: {len(cfg['deny_packages'])} · deny paths: {len(cfg['deny_paths'])} · keywords: {len(cfg['keywords'])} · warn-only markers: {len(cfg['warn_keywords'])}")
    print("  Files: .lumis/scope_guard.json, .claude/settings.json (merged), scripts/scope_guard.py, " + const_path.name + ", .cursorrules (section), CLAUDE.md (section)")
    print("  Agents: Claude Code (.claude/settings.json), Cursor (.cursor/hooks.json), Codex (.codex/hooks.json), Windsurf (.windsurf/hooks.json), Copilot (.github/hooks/lumis-scope-guard.json)")
    print("  Self-test: ask the agent to add something from the Non-Goals list — it must refuse or ask.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    cfg_path = root / ".lumis" / "scope_guard.json"
    if not cfg_path.exists():
        print("No .lumis/scope_guard.json here — run `init` first.", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    text = args.text or sys.stdin.read()
    low = text.lower()

    def matches(trigger: str) -> bool:
        """The same spelling tolerance the hook has: the phrase `push notifications` also finds
        `push_notifications`, `push-notifications`, `PushNotifications` and `send_push_notifications`
        (the text is lower-cased first). A single word keeps the strict word boundary."""
        words = trigger.lower().split()
        if len(words) > 1:
            body = r"[\s._\-/]*".join(re.escape(w) for w in words)
            return bool(re.search(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", low))
        return bool(re.search(r"(?<![\w-])" + re.escape(words[0]) + r"(?![\w-])", low))

    hits: list[str] = []
    for kw in cfg.get("keywords", []):
        if kw and matches(kw):
            hits.append(f"Non-Goal keyword '{kw}'" + explain(cfg, kw))
    for pkg in cfg.get("deny_packages", []):
        if re.search(r"(^|[\s'\"/@=])" + re.escape(pkg.lower()) + r"([\s'\"@=:]|$)", low):
            hits.append(f"forbidden dependency '{pkg}'" + explain(cfg, pkg))
    for dp in cfg.get("deny_paths", []):
        if dp and dp.lower() in low:
            hits.append(f"forbidden path '{dp}'" + explain(cfg, dp))
    # warn-only markers: a single word out of a long Non-Goal sentence. Reported, never counted as a violation,
    # and never part of the exit code — the founder judges, the tool does not.
    possible = [f"possible match with '{kw}'" + explain(cfg, kw) for kw in cfg.get("warn_keywords", []) or [] if kw and matches(kw)]
    drift = [p for p in cfg.get("drift_phrases", []) if p.lower() in low]
    print("Non-Goals in force:")
    for ng in cfg.get("non_goals", []):
        print(f"  - {ng}")
    if hits:
        print("\n⛔ Scope violations:")
        for h in sorted(set(hits)):
            print(f"  - {h}")
    if possible:
        print("\n🔎 Possible matches — for you to judge, not violations:")
        for h in sorted(set(possible)):
            print(f"  - {h}")
    if drift:
        print("\n⚠️ Drift phrases: " + ", ".join(f"'{p}'" for p in drift[:6]) + " — confirm the task is in scope (y/n) before changing code.")
    if not hits and not drift and not possible:
        print("\n✅ No Non-Goal triggers or drift phrases found.")
    return 1 if hits else 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    for rel in (".lumis/scope_guard.json", ".claude/settings.json", "scripts/scope_guard.py", "CONSTITUTION.md", ".cursorrules", "CLAUDE.md", ".lumis/guard.manifest.json",
                ".cursor/hooks.json", ".codex/hooks.json", ".windsurf/hooks.json", ".github/hooks/lumis-scope-guard.json"):
        print(("✓ " if (root / rel).exists() else "✗ ") + rel)
    cfg_path = root / ".lumis" / "scope_guard.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        print(f"Non-Goals: {len(cfg.get('non_goals', []))} · deny packages: {len(cfg.get('deny_packages', []))} · keywords: {len(cfg.get('keywords', []))}"
              f" · warn-only markers: {len(cfg.get('warn_keywords') or [])}")
        entries = read_log(root, cfg)
        counts: dict[str, int] = {}
        for e in entries:
            counts[e.get("event", "")] = counts.get(e.get("event", ""), 0) + 1
        print(f"Guard log ({cfg.get('log', '.lumis/guard.log')}): blocked {counts.get('blocked', 0)} · warned {counts.get('warned', 0)}"
              f" · possible {counts.get('possible', 0)} · drift prompts {counts.get('drift', 0)}")
        for e in entries[-5:]:
            where = f" {e.get('path')}" if e.get("path") else ""
            print(f"  {e.get('ts', '')} {e.get('event', ''):7} {e.get('tool', '')}{where}: " + "; ".join(e.get("hits", [])))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="LUMIS scope guard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--project", default="")
    i.add_argument("--non-goals", required=True, help="semicolon- or newline-separated")
    i.add_argument("--invariants", default="")
    i.add_argument("--stack", default="")
    i.add_argument("--root", default=".")
    i.set_defaults(fn=cmd_init)
    c = sub.add_parser("check")
    c.add_argument("--text", default="")
    c.add_argument("--root", default=".")
    c.set_defaults(fn=cmd_check)
    st = sub.add_parser("status")
    st.add_argument("--root", default=".")
    st.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
