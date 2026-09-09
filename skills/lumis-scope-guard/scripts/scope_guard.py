#!/usr/bin/env python3
"""LUMIS Scope Guard — hook script shipped inside the starter repository (stdlib only).

One script, five agents. Each of them runs a command before a tool call and treats exit code 2 as "denied",
so the same guard works everywhere; only the config file and the payload shape differ.

  agent            config written by LUMIS               events
  Claude Code      .claude/settings.json                 PreToolUse, UserPromptSubmit
  Cursor           .cursor/hooks.json                    preToolUse, beforeShellExecution, beforeSubmitPrompt
  Codex CLI        .codex/hooks.json                     PreToolUse
  Windsurf/Cascade .windsurf/hooks.json                  pre_run_command, pre_write_code, pre_user_prompt
  Copilot (VS Code) .github/hooks/lumis-scope-guard.json PreToolUse

  * `python scripts/scope_guard.py pre-tool [--agent <name>]`
        blocks (exit 2) when the change or command touches a Non-Goal trigger:
        forbidden packages, paths or keywords listed in .lumis/scope_guard.json — the message names the
        boundary (NG-n), who set it and where it is written (CONSTITUTION.md / DECISION_LOG.md);
        a write to the guard's own files (hook, its configs, CONSTITUTION.md) is refused and logged as `tamper`;
        read-only inspection (grep, git log, ls) that merely mentions a boundary is allowed and logged as `inspected`;
        visual Non-Goals from DESIGN_CONSTITUTION.md only warn (exit 1), they never block;
        architecture boundaries (a route, model or top-level directory absent from ARCHITECTURE.md) only warn too.
  * `python scripts/scope_guard.py prompt [--agent <name>]`
        adds a warning to the context when the prompt contains a drift phrase
        ("quick fix for now", "while I'm in here", ...) — the agent must confirm the task is in scope.
  * `python scripts/scope_guard.py report`   -> what the guard blocked and warned about so far (.lumis/guard.log)
  * `python scripts/scope_guard.py doctor`   -> is the guard wired up here: files, configs, interpreter on PATH,
        and are the guard's own files still the ones that were installed (.lumis/guard.manifest.json)
  * `python scripts/scope_guard.py write-manifest` -> re-baseline those fingerprints after an Amend

`--agent` only picks the shape of the refusal each client renders best; the payload is recognised automatically,
so a missing or wrong flag still blocks with exit 2. Every block and warning is appended to .lumis/guard.log
(one JSON object per line: time, agent, event, tool, path, what was attempted with obvious secrets stripped, hits). The log stays in the repository; nothing is
sent anywhere. Edit .lumis/scope_guard.json to tune; re-run the LUMIS consilium (or Amend) to change the
boundaries themselves.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; the reports carry emoji
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EMPTY_CONFIG = {"non_goals": [], "keywords": [], "deny_packages": [], "deny_paths": [], "drift_phrases": [], "design_non_goals": []}
ORIGIN_LABELS = {
    "founder": "set by the founder",
    "consilium": "added by the consilium for this release (DECISION_LOG.md)",
    "spec": "taken from the founder's specification (SPEC_BASELINE.md)",
    "visual": "visual contract (DESIGN_CONSTITUTION.md, section 5)",
}


def project_root() -> Path:
    for var in ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR", "CODEX_PROJECT_DIR", "WINDSURF_PROJECT_DIR", "GITHUB_WORKSPACE"):
        value = os.environ.get(var)
        if value:
            return Path(value)
    return Path.cwd()


# --- one payload shape out of five ----------------------------------------------------------------------------
WINDSURF_EVENTS = {"pre_run_command": "Bash", "post_run_command": "Bash", "pre_write_code": "Write", "post_write_code": "Write",
                   "pre_read_code": "Read", "pre_mcp_tool_use": "MCP"}


def normalize_payload(payload: dict) -> tuple[str, dict, str, str]:
    """(tool_name, tool_input, prompt, detected_agent) for any of the supported clients.

    Claude Code, Codex, Copilot and Cursor's preToolUse already send {tool_name, tool_input}; Cursor's
    beforeShellExecution sends a flat {command, cwd}; Windsurf wraps everything in {agent_action_name, tool_info}.
    """
    if not isinstance(payload, dict):
        return "", {}, "", ""
    if payload.get("agent_action_name"):  # Windsurf / Cascade
        event = str(payload.get("agent_action_name"))
        info = payload.get("tool_info") or {}
        if event == "pre_user_prompt":
            return "", {}, str(info.get("user_prompt", "")), "windsurf"
        if event.endswith("run_command"):
            return "Bash", {"command": str(info.get("command_line", ""))}, "", "windsurf"
        if event.endswith("mcp_tool_use"):
            args = info.get("mcp_tool_arguments")
            return str(info.get("mcp_tool_name", "MCP")), (args if isinstance(args, dict) else {"arguments": str(args)}), "", "windsurf"
        return WINDSURF_EVENTS.get(event, "Edit"), {"file_path": str(info.get("file_path", "")), "edits": info.get("edits", []) or []}, "", "windsurf"
    if payload.get("tool_name"):  # Claude Code, Codex, Copilot, Cursor preToolUse / beforeMCPExecution
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, str):  # Cursor sends MCP params as a JSON string
            try:
                tool_input = json.loads(tool_input)
            except Exception:
                tool_input = {"arguments": tool_input}
        agent = "cursor" if "mcp_server_name" in payload else ""
        return str(payload["tool_name"]), (tool_input if isinstance(tool_input, dict) else {}), str(payload.get("prompt", "")), agent
    if payload.get("command") is not None:  # Cursor beforeShellExecution
        return "Bash", {"command": str(payload.get("command", ""))}, "", "cursor"
    if payload.get("file_path") is not None:  # Cursor beforeReadFile / afterFileEdit
        return "Edit", {"file_path": str(payload["file_path"]), "edits": payload.get("edits", []) or []}, "", "cursor"
    return "", {}, str(payload.get("prompt") or payload.get("user_prompt") or ""), ""


def emit_denial(agent: str, message: str) -> None:
    """Every client denies on exit 2; those that also render a structured reason get one."""
    sys.stderr.write(message + "\n")
    if agent == "cursor":
        print(json.dumps({"permission": "deny", "user_message": message, "agent_message": message}, ensure_ascii=False))
    elif agent == "copilot":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}, ensure_ascii=False))
    elif agent == "codex":
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": message}, ensure_ascii=False))


def load_config() -> dict:
    root = project_root()
    for candidate in (root / ".lumis" / "scope_guard.json", Path(__file__).resolve().parents[1] / ".lumis" / "scope_guard.json"):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                break
    return dict(EMPTY_CONFIG)


def read_stdin_json() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


# Looking is not doing. A search whose text merely mentions a boundary ("grep -rn stripe .") must not be blocked:
# an agent that cannot inspect the repository is blind, and blocking it produces a false block, not a saved boundary.
READ_ONLY_EXECUTABLES = {"grep", "rg", "egrep", "fgrep", "ag", "ack", "find", "ls", "dir", "cat", "head", "tail",
                         "wc", "tree", "stat", "file", "du", "pwd", "which", "where", "diff", "cmp", "sort", "uniq"}
GIT_READ_ONLY = {"log", "grep", "status", "show", "diff", "blame", "ls-files", "rev-parse", "rev-list", "shortlog",
                 "describe", "cat-file", "config"}
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|]")
WRITES_TO_FILE = re.compile(r">>?\s*(?!/dev/null\b|NUL\b)\S")


def is_read_only_command(command: str) -> bool:
    """True only when every segment is a known inspection command and nothing is redirected into a file.
    Anything we cannot read confidently (substitutions, unknown executables) is treated as not read-only."""
    text = str(command or "").strip()
    if not text or "$(" in text or "`" in text or WRITES_TO_FILE.search(text):
        return False
    for segment in SEGMENT_SPLIT.split(text):
        parts = segment.strip().split()
        if not parts:
            return False
        exe = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        exe = exe[:-4] if exe.endswith(".exe") else exe
        if exe == "git":
            sub = next((p for p in parts[1:] if not p.startswith("-")), "")
            if sub not in GIT_READ_ONLY or "--edit" in parts:
                return False
        elif exe not in READ_ONLY_EXECUTABLES:
            return False
    return True


# --- the guard protects itself ---------------------------------------------------------------------------------
# "anything my user can write, the agent can write, including its own hook script and the config that registers
# it" — u/Foreign-Schedule3996, r/ChatGPTCoding, 2026-09-09. Telling the agent not to touch the guard is a
# promise; refusing the write is a mechanism. This is not a security boundary — a determined process with shell
# access can still reach the files — but no rewrite happens quietly through a tool call.
GUARD_FILES = (
    ".lumis/scope_guard.json", ".lumis/guard.log", ".lumis/guard.manifest.json",
    "scripts/scope_guard.py",
    ".claude/settings.json", ".cursor/hooks.json", ".codex/hooks.json", ".windsurf/hooks.json",
    ".github/hooks/lumis-scope-guard.json",
    "CONSTITUTION.md",
)
# the rules the agent reads are generated by LUMIS too, but users keep their own notes in them: warn, do not block
GUARD_TEXT_FILES = (".cursorrules", "CLAUDE.md", "AGENTS.md")


MANIFEST = ".lumis/guard.manifest.json"
# the log is meant to grow and the manifest cannot fingerprint itself
MANIFEST_FILES = tuple(f for f in GUARD_FILES if f not in (".lumis/guard.log", MANIFEST))


def file_digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_manifest(root: Path) -> dict:
    """Fingerprints of the guard's own files, taken when it is installed or regenerated by Amend."""
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "sha256/16",
        "note": "Written at install and by LUMIS Amend. `scope_guard.py doctor` compares it; a mismatch means the "
                "guard was edited outside Amend. This records tampering, it cannot prevent it.",
        "files": {rel: file_digest(root / rel) for rel in MANIFEST_FILES if (root / rel).is_file()},
    }


def verify_manifest(root: Path) -> tuple[list[str], list[str], bool]:
    """(unchanged, changed_or_missing, manifest_present)."""
    path = root / MANIFEST
    if not path.is_file():
        return [], [], False
    try:
        stored = (json.loads(path.read_text(encoding="utf-8")) or {}).get("files") or {}
    except Exception:
        return [], ["the manifest itself is not valid JSON"], True
    same: list[str] = []
    drifted: list[str] = []
    for rel, digest in stored.items():
        target = root / rel
        if not target.is_file():
            drifted.append(f"{rel} — missing now")
        elif file_digest(target) != digest:
            drifted.append(f"{rel} — changed since install")
        else:
            same.append(rel)
    return same, drifted, True


def _mentions_guard_file(text: str, names: tuple[str, ...]) -> list[str]:
    low = str(text or "").replace("\\", "/").lower()
    return [name for name in names if name.lower() in low]


def check_tamper(tool_name: str, tool_input: dict) -> tuple[list[str], list[str]]:
    """(files the call would rewrite, guard text files it would touch). Reading them is always fine."""
    text, path = text_of_tool_input(tool_name, tool_input)
    if is_command(tool_name, tool_input):
        if is_read_only_command(text):
            return [], []
        return _mentions_guard_file(text, GUARD_FILES), _mentions_guard_file(text, GUARD_TEXT_FILES)
    if not path:
        return [], []
    return _mentions_guard_file(path, GUARD_FILES), _mentions_guard_file(path, GUARD_TEXT_FILES)


def is_command(tool_name: str, tool_input: dict) -> bool:
    """A shell call, whatever the client calls the tool (Bash, Shell, run_command, unified exec…)."""
    return bool((tool_input or {}).get("command")) or str(tool_name).lower() in {"bash", "shell", "run_command", "terminal", "exec"}


def text_of_tool_input(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """(searchable text, file path) for a tool call."""
    if is_command(tool_name, tool_input):
        return str(tool_input.get("command", "")), ""
    path = str(tool_input.get("file_path", ""))
    parts = [str(tool_input.get("content", "")), str(tool_input.get("new_string", ""))]
    for edit in tool_input.get("edits", []) or []:
        parts.append(str(edit.get("new_string", "")))
    return "\n".join(parts), path


# --- explainability: which boundary a trigger belongs to -----------------------------------------------------
def boundary_for(cfg: dict, trigger: str) -> dict | None:
    """The boundary (id, text, origin, source) behind a trigger string, when the config records it."""
    bid = (cfg.get("trigger_sources") or {}).get(trigger.lower())
    if not bid:
        return None
    for b in cfg.get("boundaries") or []:
        if b.get("id") == bid:
            return b
    return None


def explain(cfg: dict, trigger: str) -> str:
    b = boundary_for(cfg, trigger)
    if not b:
        return ""
    origin = ORIGIN_LABELS.get(str(b.get("origin", "")), str(b.get("origin", "")))
    source = b.get("source") or "CONSTITUTION.md, Article I"
    return f" → {b.get('id')} \"{b.get('text', '')}\" ({origin}; {source})"


def match_triggers(cfg: dict, text: str, path: str = "") -> list[str]:
    """Non-Goal triggers in any text — a tool call's payload or the user's own prompt. One line per boundary."""
    low = (text or "").lower()
    raw: list[tuple[str, str]] = []  # (what fired, trigger)
    for pkg in cfg.get("deny_packages", []):
        if re.search(rf"(^|[\s'\"/@=])" + re.escape(pkg.lower()) + r"([\s'\"@=:]|$)", low) or f"import {pkg.lower()}" in low or f"from {pkg.lower()}" in low or f"require('{pkg.lower()}" in low or f'require("{pkg.lower()}' in low:
            raw.append((f"forbidden dependency '{pkg}'", pkg))
    for deny_path in cfg.get("deny_paths", []):
        if deny_path and (deny_path.lower() in path.lower() or deny_path.lower() in low):
            raw.append((f"forbidden path '{deny_path}'", deny_path))
    for kw in cfg.get("keywords", []):
        if kw and re.search(r"(?<![\w-])" + re.escape(kw.lower()) + r"(?![\w-])", low):
            raw.append((f"Non-Goal keyword '{kw}'", kw))
    # one line per boundary: "forbidden dependency 'stripe', forbidden path 'billing/' → NG-1 "..." (set by the founder; ...)"
    grouped: dict[str, list[str]] = {}
    for what, trigger in raw:
        grouped.setdefault(explain(cfg, trigger), []).append(what)
    return sorted(", ".join(dict.fromkeys(whats)) + why for why, whats in grouped.items())


def check_pre_tool(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    text, path = text_of_tool_input(tool_name, tool_input)
    return match_triggers(cfg, text, path)


UI_FILE_SUFFIXES = (".css", ".scss", ".html", ".jsx", ".tsx", ".vue", ".svelte", ".astro", ".js", ".ts")


def check_design(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """Visual Non-Goals from DESIGN_CONSTITUTION.md: a warning when UI code contains a lexicon substring."""
    text, path = text_of_tool_input(tool_name, tool_input)
    if is_command(tool_name, tool_input) or (path and not path.lower().endswith(UI_FILE_SUFFIXES)):
        return []
    low = text.lower()
    hits: list[str] = []
    for rule in cfg.get("design_non_goals", []) or []:
        for needle in rule.get("lexicon", []) or []:
            if needle and needle.lower() in low:
                hits.append(f"'{needle}' → {rule.get('rule', 'visual Non-Goal')}")
                break
    return hits


# --- architecture boundaries: routes, models and directories that ARCHITECTURE.md does not know ---------------
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".rb", ".java", ".kt", ".cs", ".php", ".sql", ".prisma")
ALWAYS_ALLOWED_DIRS = {".claude", ".cursor", ".lumis", ".specify", ".github", ".vscode", "docs", "tests", "test", "scripts", "migrations", "alembic", "public", "static", "assets"}
ROUTE_RE = re.compile(r"""\b(?:app|router|api|r|blueprint|bp|server|fastify|express)\s*\.\s*(get|post|put|patch|delete|route)\s*\(\s*['"]([^'"]+)['"]""", re.I)
MODEL_RE = re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]+)\s*\([^)]*\b(?:Base|SQLModel|DeclarativeBase|Model|models\.Model|db\.Model)\b")  # persistence models, not request schemas
TABLE_RE = re.compile(r"""\b(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+["`]?|Table\(\s*['"])([A-Za-z_][A-Za-z0-9_]*)""", re.I)
PRISMA_RE = re.compile(r"^\s*model\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{", re.M)


def _normalize_path(p: str) -> str:
    p = re.sub(r"\{[^}]*\}|:[A-Za-z_]+|<[^>]*>", "{}", p.strip())
    return re.sub(r"/+$", "", p.lower()) or "/"


def _entity_forms(name: str) -> set[str]:
    low = name.lower()
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    forms = {low, snake, low.replace("_", ""), snake.replace("_", "")}
    return forms | {f.rstrip("s") for f in forms} | {f + "s" for f in forms}


def check_architecture(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    arch = cfg.get("architecture") or {}
    if not any(arch.get(k) for k in ("entities", "endpoints", "top_level")):
        return []
    text, path = text_of_tool_input(tool_name, tool_input)
    if is_command(tool_name, tool_input) or not path:
        return []
    hits: list[str] = []
    # 1) a new top-level directory outside the file plan (Write of a new file only; edits touch existing files)
    top_level = {str(d).strip("/").lower() for d in arch.get("top_level") or []}
    if tool_name in ("Write", "create_file", "apply_patch") and top_level:
        rel: Path | None
        if Path(path).is_absolute():
            try:
                rel = Path(path).resolve().relative_to(project_root().resolve())
            except Exception:
                rel = None  # outside the repository: not this guard's business
        else:
            rel = Path(path)
        parts = [p for p in rel.parts if p not in ("", ".")] if rel is not None else []
        if len(parts) > 1 and not str(rel).startswith("..") and not Path(path).exists():
            head = parts[0].lower()
            if head not in top_level and head not in ALWAYS_ALLOWED_DIRS:
                hits.append(f"new top-level directory '{parts[0]}/' is not in the file plan of ARCHITECTURE.md")
    if not path.lower().endswith(CODE_SUFFIXES):
        return hits
    # 2) a route the architecture does not declare
    known_paths = {_normalize_path(e.split(" ", 1)[-1]) for e in arch.get("endpoints") or [] if e}
    if known_paths:
        for method, route in ROUTE_RE.findall(text):
            if route.startswith("/") and _normalize_path(route) not in known_paths and not any(_normalize_path(route).startswith(k + "/") for k in known_paths if k != "/"):
                hits.append(f"route {method.upper()} {route} is not in ARCHITECTURE.md (API contracts)")
    # 3) a model or table the architecture does not declare
    known = set()
    for e in arch.get("entities") or []:
        known |= _entity_forms(str(e))
    if known:
        found = MODEL_RE.findall(text) + TABLE_RE.findall(text) + (PRISMA_RE.findall(text) if path.lower().endswith(".prisma") else [])
        for name in found:
            if name.lower() not in known and name.lower() not in {"base", "model", "table", "meta"}:
                hits.append(f"new model/table '{name}' is not among the entities of ARCHITECTURE.md")
    return sorted(set(hits))


# --- the local log: what the guard did, kept in the repository ------------------------------------------------
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(authorization|api[-_]?key|token|secret|password|passwd|pwd)\b(\s*[:=]\s*|\s+)\S+"), r"\1=***"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "bearer ***"),
    (re.compile(r"\b(sk|pk|ghp|gho|xox[abps])[-_][A-Za-z0-9_\-]{8,}"), r"\1-***"),
    (re.compile(r"\b[A-Fa-f0-9]{24,}\b"), "***"),
]


def redact(text: str, limit: int = 160) -> str:
    """What was attempted, safe to keep in a file the user may commit: obvious secrets stripped, then truncated."""
    out = " ".join(str(text or "").split())
    for pattern, replacement in SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out[:limit] + ("…" if len(out) > limit else "")


def log_event(cfg: dict, event: str, tool_name: str, tool_input: dict, hits: list[str], agent: str = "", attempted: str = "") -> None:
    rel = cfg.get("log", ".lumis/guard.log")
    if not rel:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "agent": agent or "unknown",
        "tool": tool_name or "prompt",
        "path": str((tool_input or {}).get("file_path", ""))[:200],
        # what the agent actually asked for: without it the log says "something was blocked" and no more
        "attempted": redact(attempted or (tool_input or {}).get("command", "")),
        "hits": [h[:300] for h in hits][:8],
    }
    try:
        target = project_root() / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_log(cfg: dict) -> list[dict]:
    rel = cfg.get("log", ".lumis/guard.log")
    target = project_root() / rel if rel else None
    if not target or not target.exists():
        return []
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def report(cfg: dict) -> int:
    entries = read_log(cfg)
    counts = {"blocked": 0, "warned": 0, "drift": 0}
    for e in entries:
        counts[e.get("event", "")] = counts.get(e.get("event", ""), 0) + 1
    agents = sorted({str(e.get("agent") or "unknown") for e in entries})
    print(f"LUMIS Scope Guard — {len(entries)} events in {cfg.get('log', '.lumis/guard.log')}")
    print(f"  blocked: {counts.get('blocked', 0)} · asked: {counts.get('asked', 0)} · inspected: {counts.get('inspected', 0)} · warned: {counts.get('warned', 0)} · drift prompts: {counts.get('drift', 0)}"
          + (f" · agents: {', '.join(agents)}" if entries else ""))
    if counts.get("inspected"):
        print("  ('inspected' is a read-only command — grep, git log, ls — that merely mentions a boundary: allowed, never a violation.)")
    if counts.get("asked") and not counts.get("blocked"):
        print("  ('asked' without 'blocked' means the agent was told to cross a boundary and stopped before touching a tool —")
        print("   the written rules held; the hook never had to. Both are the guard doing its job.)")
    for e in entries[-10:]:
        where = f" {e.get('path')}" if e.get("path") else ""
        who = f"[{e.get('agent')}] " if e.get("agent") else ""
        print(f"  {e.get('ts', '')} {e.get('event', ''):7} {who}{e.get('tool', '')}{where}: " + "; ".join(e.get("hits", [])))
        if e.get("attempted"):
            print(f"      attempted: {e['attempted']}")
    if not entries:
        print("  nothing yet — the guard has not had to step in.")
    return 0


AGENT_CONFIGS = {
    "Claude Code": (".claude/settings.json", "hooks"),
    "Cursor": (".cursor/hooks.json", "hooks"),
    "Codex CLI": (".codex/hooks.json", "hooks"),
    "Windsurf": (".windsurf/hooks.json", "hooks"),
    "Copilot (VS Code)": (".github/hooks/lumis-scope-guard.json", "hooks"),
}


def doctor() -> int:
    """Is the guard actually wired up here? Checks the files, the interpreter each config calls and the boundaries.
    It cannot prove your client loaded the config — only the client can, by refusing. Run the self-test after this."""
    root = project_root()
    problems: list[str] = []
    print(f"LUMIS Scope Guard — checking {root}")
    script = root / "scripts" / "scope_guard.py"
    print(("  ✓ " if script.exists() else "  ✗ ") + "scripts/scope_guard.py")
    if not script.exists():
        problems.append("the hook script itself is missing")
    cfg_path = root / ".lumis" / "scope_guard.json"
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            print(f"  ✓ .lumis/scope_guard.json — {len(cfg.get('non_goals', []))} Non-Goals, "
                  f"{len(cfg.get('deny_packages', []))} forbidden packages, {len(cfg.get('keywords', []))} keywords")
            if not (cfg.get("deny_packages") or cfg.get("deny_paths") or cfg.get("keywords")):
                problems.append("no triggers in .lumis/scope_guard.json: nothing would ever be blocked")
        except Exception as exc:
            problems.append(f".lumis/scope_guard.json is not valid JSON ({exc})")
            print("  ✗ .lumis/scope_guard.json — invalid JSON")
    else:
        problems.append(".lumis/scope_guard.json is missing")
        print("  ✗ .lumis/scope_guard.json")
    interpreters: set[str] = set()
    for agent, (rel, key) in AGENT_CONFIGS.items():
        path = root / rel
        if not path.exists():
            print(f"  – {agent}: {rel} not present (fine if you do not use it)")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            problems.append(f"{rel} is not valid JSON ({exc})")
            print(f"  ✗ {agent}: {rel} — invalid JSON")
            continue
        blob = json.dumps(data.get(key) or data)
        if "scope_guard.py" not in blob:
            problems.append(f"{rel} exists but does not call scope_guard.py")
            print(f"  ✗ {agent}: {rel} — no scope_guard.py in it")
            continue
        # Windsurf carries a separate "powershell" command for Windows; check only what this OS would run
        win = os.name == "nt"
        for entries in (data.get(key) or {}).values() if isinstance(data.get(key), dict) else []:
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                for hook in (entry.get("hooks") or [entry]):
                    line = str((hook.get("powershell") if win and hook.get("powershell") else hook.get("command")) or "")
                    if "scope_guard.py" in line:
                        interpreters.add(line.split()[0])
        print(f"  ✓ {agent}: {rel}")
    for exe in sorted(interpreters):
        found = shutil.which(exe)
        print(("  ✓ " if found else "  ✗ ") + f"interpreter '{exe}'" + (f" → {found}" if found else " is not on PATH — the hook would fail to start"))
        if not found:
            problems.append(f"'{exe}' is not on PATH; the agent cannot run the hook")
    same, drifted, has_manifest = verify_manifest(root)
    if not has_manifest:
        print(f"  – {MANIFEST} — absent: install or Amend writes it; without it a silent edit of the guard leaves no trace")
    elif drifted:
        for item in drifted:
            print(f"  ✗ {item}")
            problems.append(f"the guard's own file changed outside Amend: {item}")
        print("    (regenerate through LUMIS Amend, or re-baseline with `scope_guard.py write-manifest` if the change was yours)")
    else:
        print(f"  ✓ {MANIFEST} — {len(same)} guard file(s) unchanged since install")
    events = read_log({"log": ".lumis/guard.log"})
    if events:
        agents = sorted({str(e.get("agent") or "unknown") for e in events})
        print(f"  ✓ .lumis/guard.log — {len(events)} events so far, from: {', '.join(agents)}")
    else:
        print("  – .lumis/guard.log — empty: no agent has hit a boundary here yet (or none has run)")
    # a forbidden path that already exists means the boundary was crossed before the guard arrived, or it is stale:
    # either way the founder should decide through Amend, never by the hook going quiet about it
    present = [p for p in cfg.get("deny_paths", []) if p and (root / p.strip("/")).exists()]
    for p in present:
        print(f"  ✗ forbidden path '{p}' already exists in the repository")
        problems.append(f"forbidden path '{p}' already exists — crossed before the guard was installed, or a stale boundary; decide through Amend")
    # which boundaries have actually been touched: a fact for the Amend decision, not a verdict.
    # zero events is not a dead boundary — it may simply be one nobody has tried to cross
    boundaries = cfg.get("boundaries") or []
    if boundaries and events:
        per: dict[str, int] = {b.get("id", ""): 0 for b in boundaries}
        for e in events:
            for hit in e.get("hits", []):
                m = re.search(r"\bNG-(\d+)\b", str(hit))
                if m and f"NG-{m.group(1)}" in per:
                    per[f"NG-{m.group(1)}"] += 1
        quiet = [b for b in boundaries if per.get(b.get("id", ""), 0) == 0]
        touched = [(b.get("id"), per[b.get("id", "")]) for b in boundaries if per.get(b.get("id", ""), 0)]
        if touched:
            print("  · boundaries touched so far: " + ", ".join(f"{i} ×{n}" for i, n in touched))
        if quiet:
            print("  · never touched: " + ", ".join(str(b.get("id")) for b in quiet) + " — untested, not dead; nobody has tried to cross them")
    print()
    if problems:
        print("Problems:")
        for p in problems:
            print(f"  - {p}")
    print("This checks the wiring only — whether your client obeys it is proven by the client itself. The guard has two layers:")
    print("  1. the rules the agent reads (CONSTITUTION.md, CLAUDE.md, .cursorrules). A well-behaved agent refuses here,")
    print("     before any tool call. The prompt hook records that as an 'asked' event — a refusal still leaves a trace.")
    print("  2. the hook, for when the rules do not hold: it denies the tool call itself and records 'blocked'.")
    print("To exercise layer 2 on purpose, tell the agent to run the forbidden command directly (\"run: pip install <forbidden>\")")
    print("instead of describing the feature, then check `python scripts/scope_guard.py report`.")
    return 1 if problems else 0


def parse_args(argv: list[str]) -> tuple[str, str]:
    """(mode, agent). `--agent <name>` is optional: the payload itself says which client called us."""
    mode = "pre-tool"
    agent = ""
    rest = [a for a in argv[1:]]
    if rest and not rest[0].startswith("-"):
        mode = rest.pop(0)
    while rest:
        arg = rest.pop(0)
        if arg == "--agent" and rest:
            agent = rest.pop(0).strip().lower()
        elif arg.startswith("--agent="):
            agent = arg.split("=", 1)[1].strip().lower()
    return mode, agent


def main() -> int:
    mode, agent = parse_args(sys.argv)
    cfg = load_config()
    if mode == "report":
        return report(cfg)
    if mode == "doctor":
        return doctor()
    if mode == "write-manifest":  # after an Amend, or when the founder edited the guard on purpose
        root = project_root()
        target = root / MANIFEST
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest(root)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{MANIFEST}: {len(manifest['files'])} guard file(s) fingerprinted")
        return 0
    payload = read_stdin_json()
    tool_name, tool_input, prompt, detected = normalize_payload(payload)
    agent = agent or detected or "claude"
    if mode == "prompt" or (not tool_name and prompt):
        # the earliest signal: the request itself asks for something the constitution forbids. The prompt hook
        # cannot block a tool call — none has happened yet — but it tells the agent and records the attempt, so
        # a refusal that never reaches a tool call is still counted.
        asked = match_triggers(cfg, prompt)
        if asked:
            print(
                "⛔ LUMIS Scope Guard: this request asks for something CONSTITUTION.md forbids — "
                + "; ".join(asked)
                + ". Say so and stop: do not plan it, do not start it. Only the founder can lift a boundary (LUMIS Amend)."
            )
            log_event(cfg, "asked", "prompt", {}, asked, agent, attempted=prompt)
        phrases = [p for p in cfg.get("drift_phrases", []) if p.lower() in prompt.lower()]
        if phrases:
            print(
                "⚠️ LUMIS Scope Guard: the request contains drift phrases "
                + ", ".join(f"'{p}'" for p in phrases[:4])
                + ". Before changing code, confirm the task is inside PRD.md scope and does not touch a Non-Goal from CONSTITUTION.md; "
                "if it is not in scope, say so and stop."
            )
            log_event(cfg, "drift", "prompt", {}, [f"drift phrase '{p}'" for p in phrases[:4]], agent, attempted=prompt)
        return 0
    warnings: list[str] = []
    design_hits = check_design(cfg, tool_name, tool_input)
    if design_hits:
        warnings.append(
            "🎨 LUMIS Design Constitution warning (DESIGN_CONSTITUTION.md, section 5): "
            + "; ".join(design_hits)
            + ". Keep the visual contract or record a Feature Delta."
        )
    arch_hits = check_architecture(cfg, tool_name, tool_input)
    if arch_hits:
        warnings.append(
            "🏗️ LUMIS architecture warning: "
            + "; ".join(arch_hits)
            + ". A route, table or directory absent from ARCHITECTURE.md is a change of boundaries, not a side effect: "
            "confirm it with the founder (Feature Delta) or add it to the architecture first."
        )
    command = str((tool_input or {}).get("command", ""))
    tampered, touched_rules = check_tamper(tool_name, tool_input)
    if tampered:  # refusing the write is a mechanism; telling the agent not to touch the guard is only a promise
        emit_denial(agent,
                    "⛔ LUMIS Scope Guard blocked a change to the guard itself: " + ", ".join(tampered)
                    + ". The boundaries are lifted by the founder through LUMIS Amend, which regenerates these files together — "
                    "not by editing the hook, its config or the constitution. Ask the founder instead of working around it.")
        log_event(cfg, "tamper", tool_name, tool_input, [f"write to {f}" for f in tampered], agent, attempted=text_of_tool_input(tool_name, tool_input)[0])
        return 2
    if touched_rules:
        warnings.append("📄 LUMIS: this change rewrites the rules the agent reads (" + ", ".join(touched_rules)
                        + "). Keep your own notes, but the LUMIS section is regenerated by Amend — edits to it are lost and the boundaries stay.")
    for w in warnings:
        sys.stderr.write(w + "\n")
    hits = check_pre_tool(cfg, tool_name, tool_input)
    if hits and is_command(tool_name, tool_input) and is_read_only_command(command):
        # the agent is looking, not building: allow it and record that a boundary area was inspected
        log_event(cfg, "inspected", tool_name, tool_input, hits, agent, attempted=command)
        return 1 if warnings else 0
    if hits:
        emit_denial(agent,
                    "⛔ LUMIS Scope Guard blocked this change (CONSTITUTION.md, Article I — Non-Goals): "
                    + "; ".join(hits)
                    + ". The boundary can be lifted only by the founder (LUMIS Amend / a new consilium run), never by bypassing the hook.")
        log_event(cfg, "blocked", tool_name, tool_input, hits, agent, attempted=text_of_tool_input(tool_name, tool_input)[0])
        return 2
    if warnings:
        log_event(cfg, "warned", tool_name, tool_input, design_hits + arch_hits, agent, attempted=text_of_tool_input(tool_name, tool_input)[0])
    return 1 if warnings else 0  # 1 = non-blocking: the warning is shown, the change proceeds


if __name__ == "__main__":
    raise SystemExit(main())
