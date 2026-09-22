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
        a write to the guard's own files (hook, its configs, CONSTITUTION.md) or to the directories that hold them
        is refused and logged as `tamper`, also behind `cd`, `./`, `x/../`, a shell glob (`scripts/*.py`),
        a wrapper (`powershell -c …`, `cmd /c …`, `sudo …`), a PowerShell cmdlet (`Remove-Item -Recurse .lumis`)
        and on a later line of the command;
        read-only inspection (grep, git log, ls, an MCP read tool) that merely mentions a boundary is allowed and
        logged as `inspected`; a write that only *names* a boundary in prose — an ADR, a README line, a test that
        asserts the feature is absent — is allowed and logged as `noted`, never blocked;
        visual Non-Goals from DESIGN_CONSTITUTION.md only warn (exit 1), they never block;
        architecture boundaries (a route, model or top-level directory absent from ARCHITECTURE.md) only warn too;
        `warn_keywords` — a single word out of a long Non-Goal sentence — only warn as well (exit 1, logged as
        `possible`): the word names the boundary it came from and leaves the judgement to you.
  * `python scripts/scope_guard.py prompt [--agent <name>]`
        adds a warning to the context when the prompt contains a drift phrase
        ("quick fix for now", "while I'm in here", ...) — the agent must confirm the task is in scope.
  * `python scripts/scope_guard.py report`   -> what the guard blocked and warned about so far (.lumis/guard.log)
  * `python scripts/scope_guard.py request --reason "…"` -> the last refusal as a request file for the founder
        (.lumis/requests/, the exact payload and the boundary named; paste-ready for LUMIS Amend)
  * `python scripts/scope_guard.py doctor`   -> is the guard wired up here: files, configs, interpreter on PATH,
        and are the guard's own files still the ones that were installed (.lumis/guard.manifest.json, and the
        copy of it outside the repository: ~/.lumis/baselines/<repo-id>/manifest.json)
  * `python scripts/scope_guard.py write-manifest` -> re-baseline those fingerprints, in the repository and outside
        it, after an Amend or a deliberate change. Run it yourself: the hook refuses it to the agent.
  * `python scripts/scope_guard.py rebuild-markers [--dry-run]` -> re-derive `keywords` / `warn_keywords` from the
        boundaries this config already carries, in place, for a config you edited by hand — the architecture
        inventory, the deny lists, `pinned_keywords` and everything else are kept. `--dry-run` prints the diff and
        writes nothing; the real run saves the file as it was to `.lumis/scope_guard.prev.json` and re-baselines
        the manifest afterwards. Yours to run: the hook refuses it to the agent, `--dry-run` included.

`--agent` only picks the shape of the refusal each client renders best; the payload is recognised automatically,
so a missing or wrong flag still blocks with exit 2. Every block and warning is appended to .lumis/guard.log
(one JSON object per line: time, agent, event, tool, path, what was attempted with obvious secrets stripped, hits). The log stays in the repository; nothing is
sent anywhere. Edit .lumis/scope_guard.json to tune; re-run the LUMIS consilium (or Amend) to change the
boundaries themselves.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; the reports carry emoji
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EMPTY_CONFIG = {"non_goals": [], "keywords": [], "warn_keywords": [], "deny_packages": [], "deny_paths": [], "drift_phrases": [], "design_non_goals": []}
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
                         # moving around and printing change nothing (a redirect is caught by WRITES_TO_FILE): an agent
                         # that wrote `cd repo && cat .claude/settings.json` was logged as tampering (field report 2026-09-21)
                         "cd", "echo", "printf", "findstr", "set-location", "sl", "write-output", "write-host",
                         "wc", "tree", "stat", "file", "du", "pwd", "which", "where", "diff", "cmp", "sort", "uniq",
                         # the same looks spelled in PowerShell: the agent on Windows must be able to read too
                         "get-content", "gc", "type", "get-childitem", "gci", "select-string", "sls", "get-item",
                         "gi", "test-path", "resolve-path", "measure-object", "get-location", "compare-object"}
GIT_READ_ONLY = {"log", "grep", "status", "show", "diff", "blame", "ls-files", "rev-parse", "rev-list", "shortlog",
                 "describe", "cat-file", "config"}
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|\n]")
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
        elif exe == "find":
            # `find` reads — until -exec/-delete hands what it found to a program that writes (u/northbridgedev, case 41)
            low = [p.lower() for p in parts[1:]]
            if "-delete" in low:
                return False
            for i, p in enumerate(low):
                if p in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(low):
                    if low[i + 1].rsplit("/", 1)[-1] not in READ_ONLY_EXECUTABLES:
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
# the directories that hold the guard: `rm -rf .lumis`, `mv scripts scripts_old`, `tar -C scripts` rewrite it just as
# surely as a write to the file (the 2026-09-11 tamper test: five of eleven passes were directory-level)
GUARD_DIRS = (".lumis", "scripts", ".claude", ".cursor", ".codex", ".windsurf", ".github/hooks")
# executables that replace, remove or unpack over a directory; `ls scripts` and `git add scripts` are not these
DIR_MUTATORS = {"rm", "rmdir", "rd", "del", "erase", "mv", "move", "ren", "rename", "cp", "copy", "xcopy", "robocopy",
                "rsync", "tar", "unzip", "7z", "chmod", "chown", "chattr", "ln", "truncate", "shred", "unlink",
                # the same five verbs in PowerShell. Windows is where these agents actually run, and
                # `Remove-Item -Recurse -Force .lumis` used to pass where `rm -rf .lumis` was refused (audit 2026-09-15)
                "remove-item", "move-item", "copy-item", "rename-item", "new-item", "set-content", "add-content",
                "clear-content", "out-file", "set-itemproperty", "ri", "rni", "mi", "cpi", "ni", "sc", "ac"}
# a wrapper hides the real command from a one-string reading: `powershell -c "Remove-Item …"`, `cmd /c rd /s /q .lumis`,
# `sudo rm -rf .lumis`, `timeout 5 sed -i …`. What the wrapper runs is checked as a command of its own.
SHELL_WRAPPERS = {"sh", "bash", "zsh", "dash", "ksh", "powershell", "pwsh", "cmd", "env", "nohup", "timeout", "sudo", "doas"}
# a glob is expanded by the shell, so the tool call never shows the literal name: `sed -i … scripts/*.py`
GLOB_CHARS = ("*", "?", "[")
GIT_MUTATORS = {"rm", "mv", "checkout", "restore", "clean", "reset"}
# programs a `find -exec` can run against whatever it finds; with a filter that reaches a guard file, that is a rewrite
FIND_MUTATORS = DIR_MUTATORS | {"sed", "perl", "tee", "python", "python3", "sh", "bash", "xargs"}
GUARD_BASENAMES = tuple(sorted({f.rsplit("/", 1)[-1] for f in GUARD_FILES}))
# whole-tree git rewinds: they rewrite the guard's files when git says those files differ
GIT_REWINDS = {"stash", "reset", "revert", "checkout", "switch", "restore"}
# verbs that take a tree away. `rm -rf .`, `rm -rf "$PWD"`, `rm -rf ~` never name the guard, and hold it all the same
# (Skillkeel/tamper-cases, 2026-09-17). Copying or chmod-ing the project is not in this set: only what removes or moves.
TREE_REMOVERS = {"rm", "rmdir", "rd", "del", "erase", "shred", "mv", "move", "remove-item", "ri", "move-item", "mi"}
# producers whose output `xargs` turns into arguments: what they list is what gets rewritten
XARGS_VALUE_FLAGS = {"-n", "-i", "-p", "-d", "-l", "-s", "-e", "-a", "--max-args", "--max-procs", "--delimiter", "--arg-file", "--replace"}
LISTING_EXECUTABLES = {"ls", "dir", "get-childitem", "gci"}
# Running the guard is not rewriting it: `python scripts/scope_guard.py report` is the documented way to read the
# log. Exactly four words are read-only, and every other word naming this file — `write-manifest`,
# `rebuild-markers`, with or without `--dry-run` — stays a `tamper` refusal: re-baselining and re-deriving the
# markers are the founder's, run by them in their own shell.
# The separator is either slash: on Windows, where these agents mostly run, PowerShell tab-completion produces
# `.\scripts\scope_guard.py`, and the two documented read-only commands were refused to the agent for the spelling
# alone (review 2026-09-21). Everything else in this file already normalises backslashes; this pattern did not.
GUARD_SELF_RUN = re.compile(r"^\s*(?:python3?|py)(?:\s+-X\s+utf8)?\s+(?:\.[\\/])?scripts[\\/]scope_guard\.py\s+(?:pre-tool|prompt|report|doctor|request)\b[^>|;&\n]*$", re.I)


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


# --- the baseline outside the repository ----------------------------------------------------------------------
# "the manifest sits in the repo: one edit rewrites the hook and its hash" — u/northbridgedev, r/ClaudeCode,
# 2026-09-14. So a copy of the fingerprints is kept where a rewrite of the repository does not reach it: the user's
# home. It is recorded by the first hook call after install (before any tool call of the agent is let through), by
# the skill's `init` and by `write-manifest`. Nothing leaves the machine. This raises the cost of a quiet rewrite,
# it is not a security boundary: a process that can write to your home folder can rewrite this file too.
# LUMIS_HOME moves it; LUMIS_NO_BASELINE=1 switches it off.
def baseline_home() -> Path:
    return Path(os.environ.get("LUMIS_HOME") or (Path.home() / ".lumis")) / "baselines"


def repo_id(root: Path) -> str:
    """A stable name for this checkout: the hash of where it really is. A moved repository gets a new baseline."""
    import hashlib

    return hashlib.sha256(os.path.normcase(os.path.realpath(root)).encode("utf-8")).hexdigest()[:16]


def baseline_path(root: Path) -> Path:
    return baseline_home() / repo_id(root) / "manifest.json"


def baseline_disabled() -> bool:
    if str(os.environ.get("LUMIS_NO_BASELINE", "")).strip().lower() in ("1", "true", "yes"):
        return True
    try:
        baseline_home()
        return False
    except Exception:
        return True  # no home folder in this environment (a bare CI shell): nothing to write to


def write_baseline(root: Path, files: dict[str, str]) -> Path | None:
    """The fingerprints, copied outside the repository. None when the home folder cannot be written (then doctor says so)."""
    if baseline_disabled():
        return None
    try:
        target = baseline_path(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({
            "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "root": str(Path(os.path.realpath(root))),
            "algorithm": "sha256/16",
            "note": "A copy of .lumis/guard.manifest.json kept outside the repository, so that one edit cannot rewrite "
                    "the hook and its fingerprint together. `scope_guard.py doctor` compares the files, the manifest "
                    "in the repository and this copy. A process with access to this folder can rewrite it too.",
            "files": dict(files),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target
    except Exception:
        return None


def record_baseline_if_absent(root: Path) -> Path | None:
    """First contact: when there is no baseline yet and the guard's files still match the manifest they were
    installed with, that state is recorded. A guard that already differs from its manifest is never recorded."""
    if baseline_disabled():
        return None
    try:
        if baseline_path(root).is_file():
            return None
        same, drifted, present = verify_manifest(root)
        if not present or drifted or not same:
            return None
        return write_baseline(root, {rel: file_digest(root / rel) for rel in same})
    except Exception:
        return None


def verify_baseline(root: Path) -> tuple[str, list[str], str]:
    """(state, findings, recorded). state: off | absent | unreadable | match | differs. Each finding names the side
    that differs: the file, the manifest in the repository, or both at once (the rewrite the baseline exists for)."""
    if baseline_disabled():
        return "off", [], ""
    path = baseline_path(root)
    if not path.is_file():
        return "absent", [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
        outside = data.get("files") or {}
        recorded = str(data.get("recorded") or "")
    except Exception:
        return "unreadable", [], ""
    try:
        inside = (json.loads((root / MANIFEST).read_text(encoding="utf-8")) or {}).get("files") or {}
    except Exception:
        inside = {}
    findings: list[str] = []
    for rel in sorted(set(outside) | set(inside)):
        target = root / rel
        now = file_digest(target) if target.is_file() else ""
        out, ins = outside.get(rel, ""), inside.get(rel, "")
        if out and now == out and ins == out:
            continue
        if not out:
            findings.append(f"{rel} — in the repository manifest, not in the baseline: added after the baseline was recorded")
        elif not now:
            findings.append(f"{rel} — missing now")
        elif now != out and ins == now:
            findings.append(f"{rel} — the file AND the manifest in the repository were rewritten together; only the baseline still has the installed fingerprint")
        elif now != out:
            findings.append(f"{rel} — the file differs from the baseline (and from the manifest in the repository)")
        else:
            findings.append(f"{rel} — the file is the installed one, the manifest in the repository was edited")
    return ("differs" if findings else "match"), findings, recorded


def _touches_baseline(text: str) -> bool:
    """A command or a path that reaches the baseline folder outside the repository."""
    low = str(text or "").replace("\\", "/").lower()
    if re.search(r"(?:~|\$\{?home\}?|\$env:userprofile|%userprofile%)/\.lumis(?:/|\b)", low):
        return True
    try:
        home = str(baseline_home().parent).replace("\\", "/").lower().rstrip("/")
        return bool(home) and home in low
    except Exception:
        return False


def _clean_path(token: str) -> str:
    """One path as the file system will see it: quotes off, backslashes to slashes, `./` and `x/../` resolved,
    lower-cased. `./scripts/../scripts/./scope_guard.py` and `SCRIPTS/scope_guard.py` are the same file."""
    t = str(token or "").strip().strip("'\"`").replace("\\", "/")
    absolute = t.startswith("/")
    parts: list[str] = []
    for seg in t.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append("..")
            continue
        parts.append(seg)
    return ("/" if absolute else "") + "/".join(parts).lower()


def _clean_text(text: str) -> str:
    """The whole command with every path in it normalised, for the substring check."""
    low = str(text or "").replace("\\", "/").lower()
    low = re.sub(r"(^|[\s'\"=])\./", r"\1", low).replace("/./", "/")
    for _ in range(4):
        low = re.sub(r"(^|[\s'\"=/])[^/\s'\"]+/\.\./", r"\1", low)
    return low


def command_segments(text: str) -> list[tuple[str, list[str], str]]:
    """(executable, cleaned arguments, directory prefix) per shell segment, with `cd` applied to what follows:
    in `cd scripts && sed -i … scope_guard.py` the second segment's `scope_guard.py` is scripts/scope_guard.py."""
    prefix = ""
    out: list[tuple[str, list[str], str]] = []
    for segment in SEGMENT_SPLIT.split(str(text or "")):
        parts = segment.strip().split()
        if not parts:
            continue
        exe = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        exe = exe[:-4] if exe.endswith(".exe") else exe
        if exe == "cd":
            target = _clean_path(parts[1]) if len(parts) > 1 else ""
            prefix = target if (target.startswith("/") or not prefix) else _clean_path(prefix + "/" + target)
            continue
        args: list[str] = []
        for tok in parts[1:]:
            raw = tok.split("=", 1)[1] if ("=" in tok and not tok.startswith("-")) else tok  # f=scripts/x.py
            p = _clean_path(raw)
            if not p or p.startswith("-"):
                continue
            args.append(_clean_path(prefix + "/" + p) if (prefix and not p.startswith("/")) else p)
        out.append((exe, args, prefix))
    return out


def _mentions_guard_file(text: str, names: tuple[str, ...]) -> list[str]:
    """Guard file names the text names as a path: whole, or as the tail of one. A name glued to letters, digits, `_`,
    `-` or `.` in front of it is another file — `DESIGN_CONSTITUTION.md`, `my.cursorrules` — not the guard's. A plain
    substring test refused the founder's agent an edit of DESIGN_CONSTITUTION.md as a rewrite of CONSTITUTION.md
    (field report 2026-09-22)."""
    low = _clean_text(text)
    return [name for name in names
            if re.search(r"(?<![A-Za-z0-9_.\-])" + re.escape(name.lower()) + r"(?![A-Za-z0-9_\-])", low)]


def _resolves_to_guard(token: str, root: Path | None = None) -> str | None:
    """The guard file a path really is, through symlinks: `sed -i … /tmp/x` where /tmp/x → scripts/scope_guard.py is an
    edit of the guard (u/northbridgedev, case 43). Only paths that exist are resolved; nothing is created."""
    raw = str(token or "").strip().strip("'\"`")
    if not raw or raw.startswith("-") or len(raw) > 512:
        return None
    try:
        base = root or project_root()
        candidate = Path(raw) if os.path.isabs(raw) else base / raw
        if not os.path.lexists(candidate):
            return None
        real = os.path.realpath(candidate)
        for name in GUARD_FILES:
            target = base / name
            if os.path.lexists(target) and os.path.realpath(target) == real:
                return name
    except Exception:
        return None
    return None


def _find_reaches_guard(args: list[str]) -> str | None:
    """`find <start> -name <pattern> -exec <mutator> {} +` / `-delete`: refused when the filter can match a guard file
    and the action rewrites. `find . -name '*.pyc' -delete` passes; `find . -name '*.py' -exec sed -i …` does not."""
    low = [a.lower() for a in args]
    acts = {"-exec", "-execdir", "-ok", "-okdir", "-delete"}
    if not any(a in acts for a in low):
        return None
    mutating = "-delete" in low
    for i, a in enumerate(low):
        if a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(low):
            prog = low[i + 1].rsplit("/", 1)[-1]
            if prog in FIND_MUTATORS:
                mutating = True
    if not mutating:
        return None
    starts = [a for a in low[: next((i for i, a in enumerate(low) if a.startswith("-")), len(low))]] or ["."]
    patterns = [low[i + 1] for i, a in enumerate(low) if a in ("-name", "-iname", "-path", "-ipath", "-wholename", "-regex") and i + 1 < len(low)]
    import fnmatch
    for start in starts:
        st = start.rstrip("/")
        covers_guard_dir = st in (".", "/", "") or any(st == d or d.startswith(st + "/") or st.startswith(d + "/") or st == d.split("/")[0] for d in GUARD_DIRS)
        if not covers_guard_dir:
            continue
        if not patterns:
            return f"find over {start} with a rewriting action reaches the guard's files"
        for pat in patterns:
            for f in GUARD_FILES:
                base = f.rsplit("/", 1)[-1].lower()
                if fnmatch.fnmatch(base, pat) or fnmatch.fnmatch(f.lower(), pat) or fnmatch.fnmatch("./" + f.lower(), pat):
                    return f"find -name {pat} reaches {f}"
    return None


def _git_rewind_touches_guard(exe: str, args: list[str], raw_parts: list[str]) -> str | None:
    """`git stash`, `git reset --hard`, `git revert`, a whole-tree `git checkout <ref>`, `git checkout -- .`: a rewind
    of the tree rewinds the guard's files with it. Refused only when git itself says those files would change; a
    rewind that leaves the guard as it is passes. (u/northbridgedev, cases 44–46; Skillkeel/tamper-cases for `-- .`.)"""
    if exe != "git" or not args:
        return None
    sub = next((a for a in args if not a.startswith("-")), "")
    if sub not in GIT_REWINDS:
        return None
    if sub == "stash" and any(a in ("list", "show", "drop", "clear", "branch") for a in args[1:3]):
        return None
    rest = [a.strip().strip("'\"`") for a in raw_parts[2:]]  # the case of a ref matters to git on Linux: not lower-cased
    whole_tree = ("", ".", ":/", "*")
    has_pathspec = "--" in rest
    paths = [p for p in rest[rest.index("--") + 1:]] if has_pathspec else []
    before = rest[:rest.index("--")] if has_pathspec else rest
    names = [a for a in before if not a.startswith("-") and a not in ("push", "save")]
    if not has_pathspec:
        if sub == "restore" and names:
            has_pathspec, paths, names = True, names, []  # `git restore <paths>`: everything that is not a flag is a path
        elif sub == "checkout" and any(_clean_path(a) in whole_tree for a in names):
            has_pathspec, paths = True, [a for a in names if _clean_path(a) in whole_tree]  # `git checkout .`
            names = [a for a in names if a not in paths]
    if has_pathspec and paths:
        # a rewind limited to paths that cannot hold the guard is not a rewind of the guard
        covers = [p for p in paths if _clean_path(p) in whole_tree or any(_clean_path(p).rstrip("/") == d or _clean_path(p).startswith(d + "/") or d.startswith(_clean_path(p).rstrip("/") + "/") for d in GUARD_DIRS) or _clean_path(p) in [f.lower() for f in GUARD_FILES]]
        if not covers:
            return None
    over_tree = has_pathspec and any(_clean_path(p) in whole_tree for p in paths)
    if sub in ("checkout", "switch", "restore") and has_pathspec and not over_tree:
        return None  # `git checkout <ref> -- scripts` names the guard's directory: the directory/file rule refuses it
    if sub == "reset" and not any(a in ("--hard", "--merge") for a in args):
        return None  # a soft/mixed reset leaves the working tree alone
    if sub == "restore" and "--staged" in args and "--worktree" not in args:
        return None  # unstaging only
    try:
        root = project_root()
        guard = [f for f in GUARD_FILES if (root / f).exists()]
        if not guard:
            return None

        def git(*a: str) -> str:
            res = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip()[:200])
            return res.stdout

        # an untracked file is not rewound by anything here, except a stash that was asked to take them
        takes_untracked = sub == "stash" and any(a in ("-u", "--include-untracked", "-a", "--all") for a in args)

        def dirty_guard() -> list[str]:
            lines = [l for l in git("status", "--porcelain", "--", *guard).splitlines() if l.strip()]
            return [l[3:].strip().strip('"') for l in lines if takes_untracked or not l.startswith("??")]

        ref = names[0] if names and sub != "stash" else ""
        if sub == "restore":
            ref = next((a.split("=", 1)[1] for a in rest if a.startswith("--source=")), "") or next((rest[i + 1] for i, a in enumerate(rest[:-1]) if a in ("-s", "--source")), "")
        discards = sub in ("stash", "reset") or over_tree or any(a in ("-f", "--force", "--discard-changes") for a in args)
        changed: list[str] = []
        if discards:
            # a plain `git checkout <branch>` carries an uncommitted change over (or git refuses): nothing is lost there
            changed += dirty_guard()
        if sub in ("reset", "checkout", "switch", "restore") and ref:
            changed += [l.strip() for l in git("diff", "--name-only", ref, "HEAD", "--", *guard).splitlines() if l.strip()]
        elif sub == "revert":
            target = ref or "HEAD"
            changed += [l.strip() for l in git("diff", "--name-only", f"{target}~1", target, "--", *guard).splitlines() if l.strip()]
        changed = sorted(set(changed))
        if changed:
            return f"git {sub} would rewind the guard's files: {', '.join(changed)} (commit the guard change first, or rewind with paths that exclude it)"
    except Exception:
        return None  # not a repository, git missing, or a ref that does not exist: the command itself would fail
    return None


def _holds_project_tree(token: str, prefix: str = "") -> bool:
    """True when the path is the project root or a directory above it: `.`, `./`, `$PWD`, `~`, `/`, `..`, the absolute
    path of the repository. `cd src && rm -rf .` is src, not the tree. Resolved on the file system, nothing is created."""
    raw = str(token or "").strip().strip("'\"`")
    if not raw or raw.startswith("-") or len(raw) > 512 or any(ch in raw for ch in GLOB_CHARS):
        return False
    try:
        root = Path(os.path.realpath(project_root()))
        home = os.path.expanduser("~")
        raw = re.sub(r"^\$\{?(?:PWD|CLAUDE_PROJECT_DIR)\}?(?=$|[/\\])", lambda _m: str(root), raw)
        raw = re.sub(r"^(?:~|\$\{?HOME\}?|\$env:USERPROFILE|%USERPROFILE%)(?=$|[/\\])", lambda _m: home, raw, flags=re.I)
        if "$" in raw or "%" in raw:
            return False  # a variable we cannot read: the opaque class, not this rule
        if os.path.isabs(raw) or raw.startswith("/"):
            candidate = Path(raw)
        else:
            base = Path(prefix) if (prefix and (os.path.isabs(prefix) or prefix.startswith("/"))) else (root / prefix if prefix else root)
            candidate = base / raw
        real = Path(os.path.realpath(candidate))
        return real == root or real in root.parents
    except Exception:
        return False


def _tree_removal_reaches_guard(exe: str, raw_args: list[str], prefix: str) -> str | None:
    """`rm -rf .`, `rm -rf "$PWD"`, `Remove-Item -Recurse ~`: the target holds the whole project, the guard with it."""
    if exe not in TREE_REMOVERS:
        return None
    targets = raw_args[:-1] if (exe in ("mv", "move", "move-item", "mi") and len([a for a in raw_args if not a.startswith("-")]) > 1) else raw_args
    for a in targets:
        if _holds_project_tree(a, prefix):
            return f"{exe} over {a} takes the whole project tree, the guard's files with it"
    return None


def _xargs_program(raw_args: list[str]) -> tuple[str, bool]:
    """(the program xargs runs, True when its input comes from a file and not from the pipe)."""
    i, from_file = 0, False
    while i < len(raw_args) and raw_args[i].startswith("-"):
        flag = raw_args[i].lower()
        from_file = from_file or flag in ("-a", "--arg-file") or flag.startswith("--arg-file=")
        i += 2 if (flag in XARGS_VALUE_FLAGS and "=" not in flag) else 1
    prog = raw_args[i].rsplit("/", 1)[-1].lower() if i < len(raw_args) else "echo"
    return prog, from_file


def _xargs_reaches_guard(raw_args: list[str], producer: list[str], prefix: str) -> str | None:
    """`ls | xargs rm -rf`, `git ls-files -z | xargs -0 rm -fr`: the path is produced by a program, like `find -exec`.
    Refused when the program xargs runs rewrites and what the producer lists can hold the guard. `echo build | xargs
    rm -f` names its one target and passes; a producer the hook cannot read (`cat list.txt`) is the opaque class."""
    prog, from_file = _xargs_program(raw_args)
    if from_file or prog not in (FIND_MUTATORS - {"xargs"}) or not producer:
        return None
    p_exe = producer[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower().removesuffix(".exe")
    p_args = [t.strip().strip("'\"`") for t in producer[1:]]
    names = [a for a in p_args if not a.startswith("-")]
    if p_exe in ("echo", "printf"):
        for a in names:
            clean = _clean_path(prefix + "/" + a) if (prefix and not a.startswith("/")) else _clean_path(a)
            literal = [f for f in GUARD_FILES if clean == f.lower()] + [f"directory {d}/" for d in GUARD_DIRS if clean.rstrip("/") == d]
            literal += _glob_reaches_guard(clean, True)
            if literal:
                return f"xargs {prog} on {literal[0]}"
            if _holds_project_tree(a, prefix):
                return f"xargs {prog} over {a} takes the whole project tree, the guard's files with it"
        return None
    if p_exe in LISTING_EXECUTABLES:
        starts = names or ["."]
        for a in starts:
            clean = _clean_path(a).rstrip("/")
            if _holds_project_tree(a, prefix) or (not prefix and any(clean == d or d.startswith(clean + "/") for d in GUARD_DIRS)):
                return f"{p_exe} {a if names else ''}| xargs {prog}: the listing holds the guard's files".replace("  ", " ")
        return None
    if p_exe == "find":
        reach = _find_reaches_guard(p_args + ["-delete"])
        return f"find | xargs {prog}: {reach}" if reach else None
    if p_exe == "git" and next((a for a in names), "") == "ls-files":
        try:
            root = project_root()
            guard = [f for f in GUARD_FILES if (root / f).exists()]
            spec = [a for a in names[1:]]
            res = subprocess.run(["git", "ls-files", "--", *(spec or guard)], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
            listed = {l.strip().lower() for l in res.stdout.splitlines() if l.strip()}
            held = [f for f in guard if f.lower() in listed]
            if res.returncode == 0 and held:
                return f"git ls-files | xargs {prog}: git lists the guard's files: {', '.join(held)}"
        except Exception:
            return None
    return None


def _git_clean_reaches_guard(exe: str, raw_args: list[str]) -> str | None:
    """`git clean -fdx` removes what git does not track: the guard's log always, the whole guard when it was installed
    and not yet committed. Decided by git's own dry run with the same flags, so `git clean -fd build` passes."""
    if exe != "git":
        return None
    words = [a for a in raw_args if not a.startswith("-")]
    if not words or words[0].lower() != "clean":
        return None
    rest = raw_args[raw_args.index(words[0]) + 1:]
    flags = [a for a in rest if a.startswith("-") and not a.startswith("--")]
    forced = any("f" in a[1:] for a in flags) or "--force" in rest
    if not forced or any(a in ("-n", "--dry-run") or (a.startswith("-") and not a.startswith("--") and "n" in a[1:]) for a in rest):
        return None  # without -f git refuses by default; with -n it only prints
    try:
        root = project_root()
        dry = [a for a in rest if a not in ("-i", "--interactive")]
        res = subprocess.run(["git", "clean", "-n", *dry], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        if res.returncode != 0:
            return None
        gone: list[str] = []
        for line in res.stdout.splitlines():
            if not line.startswith("Would remove "):
                continue
            item = line[len("Would remove "):].strip().strip('"').replace("\\", "/")
            for f in GUARD_FILES:
                if (item.rstrip("/").lower() == f.lower() or (item.endswith("/") and f.lower().startswith(item.lower()))) and f not in gone:
                    gone.append(f)
        if gone:
            return f"git clean would remove the guard's files: {', '.join(gone)} (commit them, or clean with paths that exclude them)"
    except Exception:
        return None
    return None


def _glob_matches(name: str, pattern: str) -> bool:
    """Shell semantics, segment by segment: `*` and `?` never cross a `/`, so `*.py` is this directory only and
    `scripts/*.py` is the one that holds the hook."""
    parts, pat = name.split("/"), pattern.split("/")
    return len(parts) == len(pat) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pat))


def _glob_reaches_guard(arg: str, mutates_dirs: bool) -> list[str]:
    """The guard's own files a shell glob would expand to. The shell resolves `scripts/*.py` before the tool ever
    shows a literal name, so a hook that only compares exact strings never sees the rewrite (audit 2026-09-15)."""
    if not any(ch in arg for ch in GLOB_CHARS):
        return []
    pattern = arg.rstrip("/")
    hits = [name for name in GUARD_FILES if _glob_matches(name.lower(), pattern)]
    if mutates_dirs:
        hits += [f"directory {d}/" for d in GUARD_DIRS if _glob_matches(d, pattern)]
    return hits


def _wrapped_command(segment: str) -> str:
    """The command a wrapper runs: `powershell -c "Remove-Item -Recurse .lumis"` -> `Remove-Item -Recurse .lumis`.
    Empty when the segment is not a wrapper."""
    parts = str(segment or "").strip().split()
    if not parts:
        return ""
    exe = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    exe = exe[:-4] if exe.endswith(".exe") else exe
    if exe not in SHELL_WRAPPERS:
        return ""
    rest = parts[1:]
    while rest and (rest[0].startswith("-") or rest[0].isdigit() or (rest[0].startswith("/") and len(rest[0]) <= 3)):
        rest.pop(0)  # -c, -Command, -NoProfile, /c, the seconds of `timeout 5 …`
    return " ".join(rest).strip().strip("'\"`")


def _guard_targets_of_command(text: str, depth: int = 0) -> list[str]:
    """Guard files and directories a shell command would rewrite, seen through `cd`, `./`, `x/../`, symlinks,
    globs, wrappers (`powershell -c`, `sudo`), `find -exec` and whole-tree git rewinds."""
    hits: list[str] = []
    if depth < 2:
        for segment in SEGMENT_SPLIT.split(str(text or "")):
            inner = _wrapped_command(segment)
            if inner:
                for hit in _guard_targets_of_command(inner, depth + 1):
                    if hit not in hits:
                        hits.append(hit)
    segments = command_segments(text)
    pieces = re.split(r"(\|\||&&|[;|\n])", str(text or ""))
    # (tokens, the separator in front of the segment): a `|` in front means the previous segment feeds this one
    raw_with_sep = [(pieces[i].strip().split(), pieces[i - 1] if i else "") for i in range(0, len(pieces), 2) if pieces[i].strip()]
    raw_with_sep = [(p, sep) for p, sep in raw_with_sep if (p[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower().removesuffix(".exe")) != "cd"]
    raw_segments = [p for p, _sep in raw_with_sep]
    for idx, (exe, args, _prefix) in enumerate(segments):
        mutates_dirs = exe in DIR_MUTATORS or (exe == "git" and any(a in GIT_MUTATORS for a in args[:2]))
        for a in args:
            for name in GUARD_FILES:
                if a == name.lower() and name not in hits:
                    hits.append(name)
            for hit in _glob_reaches_guard(a, mutates_dirs):
                if hit not in hits:
                    hits.append(hit)
            if mutates_dirs:
                for d in GUARD_DIRS:
                    if a.rstrip("/") == d and f"directory {d}/" not in hits:
                        hits.append(f"directory {d}/")
            if exe not in READ_ONLY_EXECUTABLES:
                linked = _resolves_to_guard(a)
                if linked and f"{linked} (through a link)" not in hits and linked not in hits:
                    hits.append(f"{linked} (through a link)")
        raw = raw_segments[idx] if idx < len(raw_segments) else []
        raw_args = [t.strip().strip("'\"`") for t in raw[1:]]  # flags included: the cleaned args drop anything that starts with '-'
        if exe == "find":
            reach = _find_reaches_guard(raw_args)
            if reach and reach not in hits:
                hits.append(reach)
        rewind = _git_rewind_touches_guard(exe, [a.lower() for a in raw_args], raw)
        if rewind and rewind not in hits:
            hits.append(rewind)
        producer = raw_segments[idx - 1] if (exe == "xargs" and idx and idx < len(raw_with_sep) and raw_with_sep[idx][1] == "|") else []
        for reach in (_tree_removal_reaches_guard(exe, raw_args, _prefix),
                      _xargs_reaches_guard(raw_args, producer, _prefix) if exe == "xargs" else None,
                      _git_clean_reaches_guard(exe, raw_args)):
            if reach and reach not in hits:
                hits.append(reach)
    return hits


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_MESSAGE_ARG = re.compile(r"(\s(?:-m|-am|--message)(?:\s+|=))(\"(?:[^\"\\]|\\.)*\"|'[^']*')")


def _write_target_of_line(line: str) -> str:
    """Where a shell line sends its data: the redirect target, or what `tee` writes."""
    m = re.search(r">>?\s*([^\s|;&]+)", line) or re.search(r"\btee\b\s+(?:-a\s+)?([^\s|;&]+)", line)
    return m.group(1).strip("'\"") if m else ""


def _command_without_data(text: str) -> str:
    """The command minus the data it carries into a document: a heredoc body written to a prose file, a commit
    message. A note in DECISION_LOG.md that names CONSTITUTION.md is a note about the guard, not a change to it —
    the founder's agent was refused three times in a row for exactly that (field report 2026-09-22). A heredoc fed
    to an interpreter, or written anywhere but a prose file, keeps its body: that is a script, and a script is read
    as a command."""
    raw = str(text or "")
    if "<<" not in raw and "-m" not in raw and "--message" not in raw:
        return raw
    lines = raw.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC.search(line)
        target = _write_target_of_line(line) if m else ""
        if m and target and is_prose_path(target) and not _mentions_guard_file(_clean_path(target), GUARD_FILES):
            out.append(line)
            j = i + 1
            while j < len(lines) and lines[j].strip() != m.group(2):
                j += 1
            i = j + 1  # the body and its terminator: data, not commands
            continue
        out.append(line)
        i += 1
    return _MESSAGE_ARG.sub(lambda mm: mm.group(1) + '""', "\n".join(out))


def _only_guard_self_run(text: str) -> bool:
    """`cd repo && python scripts/scope_guard.py doctor`: running the guard the documented way, with nothing around it
    but a look (`cd`, `ls`, `pwd`). A redirect, a substitution or any other segment makes it a command like any other.
    The founder's agent could not run `doctor` from outside the project (field report 2026-09-22)."""
    raw = str(text or "")
    if not raw.strip() or "$(" in raw or "`" in raw or WRITES_TO_FILE.search(raw):
        return False
    segments = [seg for seg in SEGMENT_SPLIT.split(raw) if seg.strip()]
    return (any(GUARD_SELF_RUN.match(seg) for seg in segments)
            and all(GUARD_SELF_RUN.match(seg) or is_read_only_command(seg) for seg in segments))


def check_tamper(tool_name: str, tool_input: dict) -> tuple[list[str], list[str]]:
    """(files or directories the call would rewrite, guard text files it would touch). Reading them is always fine."""
    text, path = text_of_tool_input(tool_name, tool_input)
    if is_read_only_tool(tool_name, tool_input):
        return [], []
    if is_command(tool_name, tool_input):
        if is_read_only_command(text) or _only_guard_self_run(text):
            return [], []
        command = _command_without_data(text)
        files = list(_guard_targets_of_command(command))
        for name in _mentions_guard_file(command, GUARD_FILES):
            # named in the text but not a target the parser can see: the refusal says so, so the agent knows whether
            # to reword a note or to stop (the field report: «three rounds to find out which»)
            if not any(name in hit for hit in files):
                files.append(f"{name} (named in the command text)")
        if _touches_baseline(command):
            files.append("the guard's baseline outside the repository (~/.lumis)")
        return files, _mentions_guard_file(command, GUARD_TEXT_FILES)
    if not path:
        return [], []
    files = _mentions_guard_file(_clean_path(path), GUARD_FILES)
    if _touches_baseline(path) or _touches_baseline(os.path.realpath(os.path.expanduser(str(path)))):
        files.append("the guard's baseline outside the repository (~/.lumis)")
    linked = _resolves_to_guard(path)
    if linked and linked not in files:
        files.append(f"{linked} (through a link)")
    return files, _mentions_guard_file(_clean_path(path), GUARD_TEXT_FILES)


def is_command(tool_name: str, tool_input: dict) -> bool:
    """A shell call, whatever the client calls the tool (Bash, Shell, run_command, unified exec…)."""
    return bool((tool_input or {}).get("command")) or str(tool_name).lower() in {"bash", "shell", "run_command", "terminal", "exec"}


# every MCP filesystem/editor server names its fields differently; `file_path` alone left the whole class invisible
PATH_KEYS = ("file_path", "path", "filePath", "filepath", "target_file", "targetFile", "notebook_path", "absolute_path")
BODY_KEYS = ("content", "contents", "new_string", "new_str", "newText", "new_text", "code", "patch")
EDIT_BODY_KEYS = ("new_string", "new_str", "newText", "new_text")
# a tool that only looks. `Read`, `mcp__filesystem__read_text_file`, `list_directory`: reading the guard — or a
# forbidden path — is never a violation, and the hook now sees these calls because the matcher includes MCP tools.
READ_TOOL_WORDS = {"read", "get", "list", "search", "grep", "glob", "view", "show", "describe", "stat", "cat", "fetch", "inspect"}
WRITE_TOOL_WORDS = {"write", "edit", "create", "update", "delete", "remove", "move", "rename", "patch", "apply",
                    "replace", "insert", "append", "put", "set", "modify", "copy", "mkdir", "touch", "save", "exec", "run"}


def tool_words(tool_name: str) -> list[str]:
    """`mcp__filesystem__read_text_file` and `ReadFile` both come back as ['read', ...]."""
    return re.findall(r"[a-z]+", re.sub(r"(?<!^)(?=[A-Z])", "_", str(tool_name or "")).lower())


def is_read_only_tool(tool_name: str, tool_input: dict) -> bool:
    """True for a tool call that carries no new content and whose name says it reads."""
    tool_input = tool_input or {}
    if is_command(tool_name, tool_input) or any(tool_input.get(k) for k in BODY_KEYS) or tool_input.get("edits"):
        return False
    words = tool_words(tool_name)
    return bool(words) and any(w in READ_TOOL_WORDS for w in words) and not any(w in WRITE_TOOL_WORDS for w in words)


def text_of_tool_input(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """(searchable text, file path) for a tool call, whatever the client or the MCP server calls its fields."""
    tool_input = tool_input or {}
    if is_command(tool_name, tool_input):
        return str(tool_input.get("command", "")), ""
    path = next((str(tool_input[k]) for k in PATH_KEYS if tool_input.get(k)), "")
    parts = [str(tool_input.get(k, "")) for k in BODY_KEYS]
    for edit in tool_input.get("edits", []) or []:
        if isinstance(edit, dict):
            parts += [str(edit.get(k, "")) for k in EDIT_BODY_KEYS]
    return "\n".join(p for p in parts if p), path


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


# What fired, per kind. A multi-word trigger ("smart contract", "react native") is a phrase, a single token is a
# keyword; both are matched by the same word-boundary search, so the refusal message calls them the same thing.
TRIGGER_LABELS = {"package": "forbidden dependency", "path": "forbidden path",
                  "keyword": "Non-Goal keyword", "phrase": "Non-Goal keyword"}

_KEYWORD_PATTERNS: dict[str, "re.Pattern[str]"] = {}


def keyword_pattern(trigger: str) -> "re.Pattern[str]":
    """A Non-Goal keyword matched the way code actually spells it: the phrase `push notifications` also finds
    `push_notifications`, `push-notifications`, `PushNotifications` (the text is lower-cased first, so the camel
    form arrives as one word) and `send_push_notifications`. A phrase is specific enough to survive that — the
    separators it steps over are the ones an identifier is made of. A single word keeps the exact word-boundary
    match it has always had: widening it would put `notifications` back inside `push_notifications`."""
    low = str(trigger or "").lower().strip()
    pattern = _KEYWORD_PATTERNS.get(low)
    if pattern is None:
        words = low.split()
        if len(words) > 1:
            body = r"[\s._\-/]*".join(re.escape(word) for word in words)
            pattern = re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])")
        else:
            # one word, as an identifier part and in either number: the marker `leaderboards` must find
            # `leaderboard_service`, `/api/leaderboards` and (camel case is split by the caller) `LeaderboardService`.
            # Letters and digits still bound it: `school` is not inside `preschool`, `rbac` not inside `rbacks`.
            stem = low[:-1] if (len(low) > 4 and low.endswith("s") and not low.endswith("ss")) else low
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(stem) + r"(?:s|es)?(?![a-z0-9])")
        _KEYWORD_PATTERNS[low] = pattern
    return pattern


def _spelled_out(text: str) -> str:
    """The text lower-cased with camel case opened up: `LeaderboardService` -> `leaderboard service`."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or "")).lower()


def trigger_hits(cfg: dict, text: str, path: str = "") -> list[tuple[str, str]]:
    """(kind, trigger) for every **blocking** Non-Goal trigger the text contains — the single place where a
    forbidden package, path, keyword or phrase is recognised. Pure: no I/O, no state, the config is read-only.

    `warn_keywords` are deliberately not here: they are a possible match for a human to judge, and a caller that
    reads this function is asking what stops a tool call. `warn_triggers` answers the other question.

    The hook renders these as refusal lines (`match_triggers`); LUMIS Studio reads the same hits line by line
    (`lumis/core/boundary_check.py`) so the pasted fragment is judged by exactly the matcher that will run in the
    repository — a studio answer the hook would not repeat is a lie about the guard."""
    low = (text or "").lower()
    hits: list[tuple[str, str]] = []
    for pkg in cfg.get("deny_packages", []):
        if not pkg:
            continue
        if re.search(rf"(^|[\s'\"/@=])" + re.escape(pkg.lower()) + r"([\s'\"@=:]|$)", low) or f"import {pkg.lower()}" in low or f"from {pkg.lower()}" in low or f"require('{pkg.lower()}" in low or f'require("{pkg.lower()}' in low:
            hits.append(("package", pkg))
    for deny_path in cfg.get("deny_paths", []):
        if deny_path and (deny_path.lower() in path.lower() or deny_path.lower() in low):
            hits.append(("path", deny_path))
    spelled = _spelled_out(text)
    for kw in cfg.get("keywords", []):
        if kw and (keyword_pattern(kw).search(low) or keyword_pattern(kw).search(spelled)):
            hits.append(("phrase" if " " in kw.strip() else "keyword", kw))
    return hits


def warn_triggers(cfg: dict, text: str) -> list[tuple[str, str]]:
    """(kind, trigger) for the warn-only markers — a single word out of a long Non-Goal sentence.

    They exist because the config generator used to make every such word blocking: on the founder's run of
    2026-09-21 the hook would have refused `python -m pytest`, a file whose docstring said "canonical
    curriculum", and the project's own `services/` package. A word out of a sentence is a hint for a human;
    it is reported, it never stops a tool call, and a config written before this key existed simply has none."""
    low, spelled = (text or "").lower(), _spelled_out(text)
    return [("phrase" if " " in str(kw).strip() else "keyword", kw)
            for kw in cfg.get("warn_keywords", []) or [] if kw and (keyword_pattern(kw).search(low) or keyword_pattern(kw).search(spelled))]


def match_triggers(cfg: dict, text: str, path: str = "") -> list[str]:
    """Non-Goal triggers in any text — a tool call's payload or the user's own prompt. One line per boundary."""
    raw = [(f"{TRIGGER_LABELS[kind]} '{trigger}'", trigger) for kind, trigger in trigger_hits(cfg, text, path)]
    # one line per boundary: "forbidden dependency 'stripe', forbidden path 'billing/' → NG-1 "..." (set by the founder; ...)"
    grouped: dict[str, list[str]] = {}
    for what, trigger in raw:
        grouped.setdefault(explain(cfg, trigger), []).append(what)
    return sorted(", ".join(dict.fromkeys(whats)) + why for why, whats in grouped.items())


def check_pre_tool(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    text, path = text_of_tool_input(tool_name, tool_input)
    return match_triggers(cfg, text, path)


def check_warn_markers(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """One line per warn-only marker, each naming its boundary — the same `→ NG-n "…" (origin; source)` tail a
    refusal carries, so `report`, `doctor` and LUMIS Amend attribute a warning to a boundary exactly as they
    attribute a block. Runs for commands too: a lone word out of a long sentence shows up in `python -m …`
    more often than anywhere else."""
    text, _path = text_of_tool_input(tool_name, tool_input)
    return sorted({f"possible match with '{trigger}'" + explain(cfg, trigger) for _kind, trigger in warn_triggers(cfg, text)})


# --- boundary → markers, the stdlib derivation ------------------------------------------------------------------
# A deliberate, stdlib-only port of lumis/core/boundary_markers.py (the product's own derivation, shared there by
# the blueprint audit and the config generator). It lives HERE, in the hook, and not in the skill's installer,
# because `rebuild-markers` below re-derives the markers of an already-installed repository, where this file is
# the only one of the two that exists: a generated pack ships `scripts/scope_guard.py` and nothing else. The
# skill's `lumis_guard.py` sits next to this file and imports it, so the word lists exist in two places (the
# product and the hook) instead of three; `test_skill_pack.py` pins the hook's derivation against the product's.
#
# Why these rules exist: until 2026-09-21 every Latin word of five letters or more became a *blocking* keyword, so a
# guard built from "a complete Python-to-backend-engineer curriculum" refused `python -m pytest` and any file whose
# docstring said "curriculum" — in the founder's own repository. Function words carry no boundary; adjacent content
# words inside one clause make a phrase, which is what actually blocks; a short boundary is its own words; a lone
# word out of a long sentence is a hint for a human and only warns; an item of an enumeration is a boundary of its own.
CAPABILITY_TRIGGERS = {
    "crypto": {"match": ["crypto", "web3", "blockchain", "крипт", "блокчейн", "токен", "smart contract", "смарт-контракт"],
               "packages": ["web3", "ethers", "solana", "wagmi", "viem", "bitcoinlib", "hardhat", "truffle"], "paths": ["contracts/", "web3/"],
               "keywords": ["web3", "solidity", "ethereum", "metamask", "erc20", "smart contract", "wallet connect"]},
    "microservices": {"match": ["microservice", "микросервис", "kafka", "rabbitmq"],
                      "packages": ["kafka-python", "aiokafka", "pika", "celery", "grpcio", "nameko"], "paths": ["services/"],
                      "keywords": ["kafka", "rabbitmq", "grpc", "consul", "istio", "service mesh"]},
    "native_mobile": {"match": ["ios", "android", "native mobile", "мобильн", "flutter", "react native"],
                      "packages": ["react-native", "expo", "flutter", "capacitor", "cordova"], "paths": ["ios/", "android/"],
                      "keywords": ["react native", "swiftui", "kotlin", "xcode", "android studio"]},
    "open_banking": {"match": ["open banking", "банковск", "core ledger", "psd2"],
                     "packages": ["plaid", "tink", "truelayer"], "paths": [], "keywords": ["open banking", "psd2", "plaid", "core ledger"]},
    "payments": {"match": ["payment", "платеж", "платёж", "billing", "эквайринг", "stripe"],
                 "packages": ["stripe", "braintree", "adyen", "paypal-checkout"], "paths": ["billing/"], "keywords": ["stripe", "paypal", "braintree", "adyen"]},
    "complex_auth": {"match": ["saml", "sso", "ldap", "enterprise auth", "kerberos"],
                     "packages": ["python3-saml", "ldap3", "keycloak"], "paths": [], "keywords": ["saml", "ldap", "kerberos", "keycloak"]},
    "websockets": {"match": ["websocket", "вебсокет", "realtime", "real-time"],
                   "packages": ["socket.io", "ws", "websockets", "socketio"], "paths": [], "keywords": ["websocket", "socket.io"]},
    "email": {"match": ["email sending", "рассылк", "newsletter", "smtp"],
              "packages": ["nodemailer", "sendgrid", "resend", "mailgun"], "paths": [], "keywords": ["smtp", "sendgrid", "mailgun"]},
    "multi_tenancy": {"match": ["multi-tenan", "multitenan", "мультитенант", "team accounts", "organizations", "командн"],
                      "packages": [], "paths": ["tenants/", "organizations/"], "keywords": ["tenant_id", "organization_id", "workspace_id", "rbac"]},
    "marketplace": {"match": ["marketplace", "маркетплейс", "plugin store", "adapter sdk"],
                    "packages": [], "paths": ["marketplace/", "plugins/"], "keywords": ["marketplace", "plugin registry", "adapter sdk"]},
    "llm_grading": {"match": ["llm grading", "llm-оцен", "llm оцен", "ai grading", "auto-grade", "оценка ответов"],
                    "packages": [], "paths": [], "keywords": ["grade_with_llm", "llm_score", "ai_grader"]},
}
FUNCTION_WORDS = {
    "the", "and", "for", "with", "without", "any", "all", "from", "into", "onto", "over", "under", "that", "this", "these",
    "those", "than", "then", "other", "others", "such", "only", "also", "more", "most", "less", "some", "each", "every",
    "their", "there", "them", "they", "will", "shall", "must", "should", "would", "could", "have", "has", "been", "being",
    "are", "was", "were", "not", "nor", "but", "via", "per", "own", "out", "off", "about", "within", "across", "between",
    "during", "before", "after", "until", "while", "when", "where", "which", "what", "who", "whom", "how", "yet", "still",
    "first", "second", "third", "party", "parties", "stage", "phase", "release", "version", "initial", "later", "future",
    "new", "use", "used", "using", "make", "made", "based", "kind", "type", "types", "level", "full", "part", "real",
    "или", "для", "при", "под", "над", "без", "это", "этот", "эта", "эти", "того", "тоже", "также", "только", "если",
    "как", "что", "чтобы", "когда", "где", "кто", "все", "всех", "всё", "любой", "любые", "любых", "любая", "каждый",
    "другой", "другие", "других", "свой", "свои", "своих", "будет", "быть", "есть", "через", "между", "после", "перед",
    "пока", "этапе", "этап", "версии", "версия", "релизе", "релиз", "первой", "первом", "сторонних", "сторонние",
    "третьих", "третьим", "лиц", "лицам", "поддержка", "поддержки", "функционал", "функции", "функций",
}
GENERIC_ARCHITECTURAL_STOPWORDS = {
    "api", "app", "apps", "service", "services", "system", "systems", "module", "modules",
    "data", "model", "models", "code", "file", "files", "function", "functions",
    "endpoint", "endpoints", "route", "routes", "server", "servers", "client", "clients",
    "ui", "ux", "web", "rest", "http", "https", "integration", "integrations", "support",
    "feature", "features", "development", "build", "project", "mvp", "v1", "v2",
    "custom", "direct", "native", "simple", "complex", "realtime", "external", "user",
    "reviews", "review", "item", "items", "list", "get", "post", "put", "delete",
}
COMMON_CODE_WORDS = {
    # verbs of everyday development: «No push notifications» must not make `git push` or `send_push()` a crossing
    "push", "pull", "commit", "merge", "build", "install", "update", "delete", "create", "send", "fetch", "sync",
    "deploy", "start", "stop", "check", "clean", "reset", "patch",
    "architecture", "production", "deployment", "development", "database", "databases", "runtime",
    "environment", "config", "configuration", "script", "scripts", "library", "libraries",
    "framework", "frameworks", "package", "packages", "public", "private", "internal", "generic",
    "complete", "advanced", "basic", "standard", "default", "source", "sources", "content", "contents",
    "anything", "everything", "entire", "whole", "general", "universal", "automatic", "manual",
    "hidden", "similar", "example", "examples", "actual", "overall", "multiple", "single", "primary",
    "editor", "console", "logging", "testing", "pattern", "patterns", "state", "context",
    "environments", "infrastructure", "infrastructures", "research", "zero", "multi", "cross",
    "structure", "structures", "layer", "layers", "engine", "engines", "worker", "workers",
    "call", "calls", "free", "like", "self", "long", "form", "present", "whose", "hard", "coded",
    "applied", "scale", "side", "truth", "record", "records", "goal", "goals", "directly", "stack",
    "identity", "style", "event", "events", "acting", "requiring", "exposing", "defining",
    "continuously", "simultaneously", "served", "interface", "product", "products", "loop", "loops",
    # added with the enumeration rule (2026-09-21): `todo` as a blocking item of «…Item, Record, Goal, First,
    # Todo or similar example entities» would refuse every `# TODO:` comment in the repository it guards
    "todo", "todos", "entity", "entities", "placeholder", "placeholders", "sample", "samples",
    "dummy", "temp",
    "архитектура", "продакшен", "разработка", "окружение", "конфигурация", "скрипт", "скрипты",
    "библиотека", "библиотеки", "пакет", "пакеты", "общий", "общая", "общее", "полный", "полная",
    "полное", "базовый", "стандартный", "внутренний", "внешний", "автоматический", "ручной",
    "пример", "примеры", "данных", "данные", "шаблон", "шаблоны", "запись", "записи", "цель", "цели",
}
TECHNOLOGY_WORDS = {
    "sqlite", "sqlcipher", "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongo", "redis",
    "elasticsearch", "cassandra", "dynamodb", "firestore", "indexeddb", "kafka", "rabbitmq", "celery",
    "grpc", "graphql", "websocket", "websockets", "docker", "kubernetes", "terraform", "nginx",
    "firebase", "supabase", "auth0", "keycloak", "saml", "ldap", "kerberos", "oauth",
    "stripe", "paypal", "braintree", "adyen", "plaid", "twilio", "sendgrid", "mailgun", "smtp",
    "blockchain", "solidity", "ethereum", "bitcoin", "metamask", "web3", "erc20",
    "electron", "tauri", "flutter", "expo", "swiftui", "xcode", "cordova", "capacitor",
    "django", "flask", "fastapi", "express", "nestjs", "nextjs", "rails", "laravel", "spring",
    "sqlalchemy", "sqlmodel", "prisma", "drizzle", "typeorm", "sequelize", "mongoose",
    "microservice", "microservices", "serverless", "istio", "consul", "airflow", "spark",
    "tensorflow", "pytorch", "langchain", "pinecone", "weaviate", "chromadb",
}
SHORT_BOUNDARY_WORDS = 4  # longer than this, in the founder's own words, and the boundary's lone words only warn
# How many comma/«or»-separated items make a boundary an enumeration: «social feeds, followers, public profiles,
# leaderboards or multiplayer» is five refusals on one line, and an item that is one rare word is that item in
# full, so it blocks like a short boundary (field report 2026-09-21: `class Leaderboard` walked past `leaderboards`).
LIST_ITEMS_MIN = 3
# …and only when the boundary opens with such an item. A sentence that merely contains a list («no storing personal
# data in analytics, logs, reports or exports») refuses the storing, not the log file.
LIST_HEAD_WORDS = 3
GLUE_MAX = 3              # how many adjacent words may be glued back into one technology name (`postgre sql`)
MARKERS_PER_BOUNDARY = 8
WARN_MARKERS_PER_BOUNDARY = 8
NEGATION_RE = re.compile(r"\b(no|not|never|without|нет|не|без|запрещено|исключено|отсутствует|нельзя|никаких)\b", re.IGNORECASE)
CLAUSE_RE = re.compile(r"[,;:.!?()\[\]{}«»\"“”]|\bor\b|\band\b|\bили\b|\bи\b", re.IGNORECASE)
# The half of a refusal that names what the founder *wants*: «no server SQLite: managed PostgreSQL only» refuses
# SQLite and prescribes PostgreSQL, and arming both refuses the project's own database URL.
PRESCRIBES_RE = re.compile(
    r"\bonly\b|\binstead\b|\brather\s+than\b|\bis\s+the\b|\bare\s+the\b|\bmust\b|\bshall\b|\buses?\b|\busing\b|"
    r"\bтолько\b|\bвместо\b|\bостаётс\w*|\bостаетс\w*|\bдолжн\w*|\bиспользу\w*", re.IGNORECASE)
# Where one statement ends: coarser than CLAUSE_RE, so the dot of «Expo SDK 57.x prebuild only» cannot hide the
# "only" from the half that carries it.
SEGMENT_RE = re.compile(r"[;:]|(?<!\d)\.(?!\d)|\bbut\b|\bно\b|—|–", re.IGNORECASE)
PUNCTUATION_RE = re.compile(r"[^\w\s]+", re.UNICODE)
CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
SEPARATOR_RE = re.compile(r"[\-_\./\\:;\(\)\[\]\"']+")


def normalize(text: str) -> str:
    """Split camelCase, lower-case, separators to spaces: `PushNotifications` → `push notifications`."""
    return SEPARATOR_RE.sub(" ", CAMEL_RE.sub(r"\1 \2", str(text)).lower()).strip()


def glue_technologies(words: list) -> list:
    """Put a technology's name back together after `normalize` split its humps: `postgre sql` → `postgresql`,
    `g rpc` → `grpc`, `dynamo db` → `dynamodb`. Without this the lexicon never sees the name the founder wrote."""
    out, i = [], 0
    while i < len(words):
        glued_any = False
        for n in range(min(GLUE_MAX, len(words) - i), 1, -1):
            glued = "".join(words[i:i + n])
            if glued in TECHNOLOGY_WORDS:
                out.append(glued)
                i += n
                glued_any = True
                break
        if not glued_any:
            out.append(words[i])
            i += 1
    return out


def prescribes(clause: str) -> bool:
    """The clause says what to use rather than what not to. A clause carrying its own refusal never does."""
    return bool(PRESCRIBES_RE.search(clause)) and not NEGATION_RE.search(clause)


def stack_vocabulary(stack: str) -> set:
    """What the product is built from is not a boundary marker. Outside the full LUMIS pack this is honestly
    weaker than the generator's vocabulary: the installer knows only what the founder typed into `--stack`, and
    a config rebuilt in place knows only what it carries (see `config_vocabulary`)."""
    words = {w for w in normalize(stack).split() if len(w) > 3}
    return words | {w[:-1] for w in words if w.endswith("s")} | {w + "s" for w in words}


def markers_for(boundary: str, vocabulary: set) -> tuple:
    """(blocking markers, warn-only markers) for one boundary — phrases first, then words, in that order."""
    segments = SEGMENT_RE.split(str(boundary or ""))
    kept = [p for p in segments if not prescribes(p)] or segments
    clauses = [" ".join(glue_technologies(c.split()))
               for c in (normalize(PUNCTUATION_RE.sub(" ", NEGATION_RE.sub("", part)))
                         for p in kept for part in CLAUSE_RE.split(p)) if c]
    words = [t for clause in clauses for t in clause.split() if t]
    tokens = [t for t in dict.fromkeys(words)
              if len(t) > 3 and t not in GENERIC_ARCHITECTURAL_STOPWORDS and t not in FUNCTION_WORDS and not t.isdigit()]
    phrases = []
    for clause in clauses:
        content = [t for t in clause.split() if len(t) > 2 and t not in FUNCTION_WORDS]
        phrases += ["%s %s" % (a, b) for a, b in zip(content, content[1:]) if a != b]
    # an item of an enumeration that is one rare word is that item in full: such items lead the list, because the
    # per-boundary cap cuts from the tail and a word the founder listed on its own must survive it
    enumerated = len(clauses) >= LIST_ITEMS_MIN and len(clauses[0].split()) <= LIST_HEAD_WORDS
    list_items = {c for c in clauses if len(c.split()) == 1 and len(c) > 3} if enumerated else set()
    raw = list(dict.fromkeys([t for t in tokens if t in list_items] + phrases + tokens))
    whole = not raw
    if whole:
        raw = [normalize(boundary)]
    short = len(words) <= SHORT_BOUNDARY_WORDS
    blocking, warning = [], []
    for text in raw:
        parts = text.split()
        if not text or len(text) < 3 or text in GENERIC_ARCHITECTURAL_STOPWORDS:
            continue
        if not whole and any(len(w) < 3 or w.isdigit() for w in parts):
            continue
        if all(w in vocabulary or w in COMMON_CODE_WORDS or w in GENERIC_ARCHITECTURAL_STOPWORDS for w in parts):
            continue
        if whole:
            continue  # nothing but function words: a marker nobody would ever write into a file
        if " " in text or short or text in list_items:
            blocking.append(text)
        else:
            warning.append(text)
    return blocking[:MARKERS_PER_BOUNDARY], warning[:WARN_MARKERS_PER_BOUNDARY]


PROSE_SUFFIXES = (".md", ".mdx", ".rst", ".adoc")
DOC_DIRS = {"docs", "doc", "adr", "rfc"}
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}


def is_prose_path(path: str) -> bool:
    """A file that names a boundary on purpose: an ADR that explains the Non-Goal, a README line restating it, a
    test that asserts the forbidden feature is absent. Writing the boundary down is inside the boundary; only the
    code that crosses it is not. These warn and are logged (`noted`), they are never refused."""
    p = _clean_path(path)
    if not p:
        return False
    if p.endswith(PROSE_SUFFIXES):
        return True
    segments = set(p.split("/")[:-1])
    base = p.rsplit("/", 1)[-1]
    if segments & DOC_DIRS or segments & TEST_DIRS:
        return True
    return base.startswith(("test_", "test-")) or any(m in base for m in ("_test.", ".test.", ".spec.", "_spec."))


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
# What a leaked credential looks like in a tool payload. A warning, never a block: the agent may be writing a
# fixture on purpose, but the founder's agent checked for this by hand before every push (field report 2026-09-22).
SECRET_LEAKS: list[tuple[str, "re.Pattern[str]"]] = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("a connection string with a password", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@]+@", re.I)),
    ("an API token", re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,})")),
]


def secret_leaks(text: str, path: str = "") -> list[str]:
    """The kinds of credential a payload carries. Documents, tests and *.example files are where placeholders live."""
    low = _clean_path(path)
    if low and (is_prose_path(low) or low.endswith((".example", ".sample", ".template"))):
        return []
    found = [kind for kind, rx in SECRET_LEAKS if rx.search(str(text or ""))]
    if any(w in str(text or "").lower() for w in ("example.com", "placeholder", "changeme", "xxxxxxxx", "your_")):
        return [] if len(found) < 2 else found
    return found


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
        "path": text_of_tool_input(tool_name, tool_input)[1][:200],
        # what the agent actually asked for: without it the log says "something was blocked" and no more
        # a refusal keeps more of the payload: the token that matched is usually past the first line of a heredoc
        "attempted": redact(attempted or (tool_input or {}).get("command", ""), limit=600 if event in ("blocked", "tamper") else 160),
        "hits": [h[:300] for h in hits if str(h).strip()][:8],
    }
    if event in ("warned", "possible") and not entry["hits"]:
        return  # a warning with no reason teaches the agent to skip the whole category (field report 2026-09-22)
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


def fingerprints() -> str:
    """Which hook and which config are speaking: without them «did the rules change?» can only be answered by trying
    the refused edit again (field report 2026-09-22)."""
    try:
        hook = file_digest(Path(__file__))[:8]
    except Exception:
        hook = "?"
    try:
        config = file_digest(project_root() / ".lumis" / "scope_guard.json")[:8]
    except Exception:
        config = "absent"
    return f"hook {hook} · config {config}"


def write_request(reason: str) -> int:
    """`scope_guard.py request --reason "…"`: the last refusal, written into .lumis/requests/<ts>-<slug>.md with the
    exact payload the guard recorded, the boundary it named, and the agent's reason — a file, so it survives the
    agent's context being compacted, and paste-ready for LUMIS Amend. The founder's agent wrote such a file by hand,
    twice, because the first copy had drifted from the file by the time a decision came (field report 2026-09-22)."""
    root = project_root()
    events = [e for e in read_log({"log": ".lumis/guard.log"}) if e.get("event") in ("blocked", "tamper")]
    if not events:
        print("no refusal on record: nothing to request")
        return 1
    last = events[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", (reason or "request").lower()).strip("-")[:40] or "request"
    stamp = re.sub(r"[^0-9T]", "", str(last.get("ts", ""))[:19]) or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = root / ".lumis" / "requests" / f"{stamp}-{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    hits = last.get("hits") or []
    kind = "the guard's own files" if last.get("event") == "tamper" else "a Non-Goal"
    amend_lines = [f"- Consider lifting or narrowing the boundary behind: {h}" for h in hits if "NG-" in str(h)] or [
        "- The refusal concerned the guard's own files: if the change was meant, run Amend or edit the boundary yourself; the agent must not."]
    body = "\n".join([
        f"# Request to the founder: {reason or '(no reason given)'}",
        "",
        f"- refused at: {last.get('ts', '')} · agent: {last.get('agent', 'unknown')} · tool: {last.get('tool', '')}"
        + (f" · path: {last.get('path')}" if last.get("path") else ""),
        f"- what the guard named ({kind}):",
        *[f"  - {h}" for h in hits],
        "",
        "## What was attempted (as the guard recorded it, secrets stripped)",
        "",
        "```",
        str(last.get("attempted", "")),
        "```",
        "",
        "## Why the agent asks",
        "",
        reason or "(no reason given)",
        "",
        "## For LUMIS Amend (paste into «Указания архитектору» / the amendment notes)",
        "",
        *amend_lines,
        "",
        f"_written by scripts/scope_guard.py request · {fingerprints()}_",
        "",
    ])
    target.write_text(body, encoding="utf-8")
    print(f"request written: {target.relative_to(root)}")
    print("  hand it to the founder; the guard does not lift anything on its own")
    return 0


def report(cfg: dict) -> int:
    entries = read_log(cfg)
    counts = {"blocked": 0, "warned": 0, "possible": 0, "drift": 0, "tamper": 0}
    for e in entries:
        counts[e.get("event", "")] = counts.get(e.get("event", ""), 0) + 1
    agents = sorted({str(e.get("agent") or "unknown") for e in entries})
    stopped = counts.get("blocked", 0) + counts.get("tamper", 0)
    print(f"LUMIS Scope Guard — {len(entries)} events in {cfg.get('log', '.lumis/guard.log')} · {fingerprints()}")
    # «blocked: 0» beside eighteen tamper refusals read as «the guard never stepped in» (field report 2026-09-22)
    print(f"  stopped: {stopped} (blocked: {counts.get('blocked', 0)} · tamper: {counts.get('tamper', 0)})"
          f" · asked: {counts.get('asked', 0)} · inspected: {counts.get('inspected', 0)} · warned: {counts.get('warned', 0)} · drift prompts: {counts.get('drift', 0)}"
          + (f" · possible: {counts.get('possible', 0)}" if counts.get("possible") else "")
          + (f" · noted: {counts.get('noted', 0)}" if counts.get("noted") else "")
          + (f" · agents: {', '.join(agents)}" if entries else ""))
    if counts.get("possible"):
        print("  ('possible' is a single word out of a long Non-Goal sentence that turned up in a change: a match for you")
        print("   to judge, not a violation. Nothing was blocked; the word alone does not prove the boundary was crossed.)")
    if counts.get("inspected"):
        print("  ('inspected' is a read-only command — grep, git log, ls, an MCP read tool — that merely mentions a boundary: allowed, never a violation.)")
    if counts.get("noted"):
        print("  ('noted' is a document or a test that writes a boundary down — docs/, *.md, tests/: allowed, never a violation.)")
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


INTERPRETER_IN_COMMAND = re.compile(r"(?:^|[\s\"'])((?:[^\s\"']*[/\\])?(?:python3|python|py))(?:\s|$)")

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
    print(f"LUMIS Scope Guard — checking {root} · {fingerprints()}")
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
                  f"{len(cfg.get('deny_packages', []))} forbidden packages, {len(cfg.get('keywords', []))} keywords"
                  + (f", {len(cfg.get('warn_keywords') or [])} warn-only markers" if cfg.get("warn_keywords") else ""))
            # warn-only markers never stop a call, so they cannot answer for an otherwise empty config
            if not (cfg.get("deny_packages") or cfg.get("deny_paths") or cfg.get("keywords")):
                problems.append("no blocking triggers in .lumis/scope_guard.json: nothing would ever be blocked"
                                + (" (the warn-only markers report, they do not refuse)" if cfg.get("warn_keywords") else ""))
            # advice, never a problem: an armed `python` or `public` is the old disease, and the founder — not
            # this script — decides what their own words meant. `rebuild-markers` is theirs to run.
            stale = stale_markers(cfg)
            if stale:
                print(f"  · {len(stale)} blocking keyword(s) are words every repository contains: "
                      + ", ".join(f"'{w}'" for w in stale[:8]) + ("…" if len(stale) > 8 else ""))
                print("    (they refuse ordinary work — `python scripts/scope_guard.py rebuild-markers --dry-run`")
                print("     shows what today's rules would derive from the same boundaries; nothing else changes.)")
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
                        interpreters.add(line)
        print(f"  ✓ {agent}: {rel}")
    # a hook line names the interpreters it may run (`python` first, `python3` when there is no bare `python`);
    # it starts as long as one of them is on PATH — stock macOS/Linux have no `python`, Windows has no `python3`
    for line in sorted(interpreters):
        names = list(dict.fromkeys(INTERPRETER_IN_COMMAND.findall(line))) or ["python"]
        found = [(n, shutil.which(n)) for n in names]
        usable = [(n, p) for n, p in found if p]
        if usable:
            print(f"  ✓ interpreter '{usable[0][0]}' → {usable[0][1]}")
        else:
            print("  ✗ none of " + ", ".join(f"'{n}'" for n in names) + " is on PATH — the hook would fail to start")
            problems.append("no Python on PATH (" + ", ".join(names) + "); the agent cannot run the hook")
    # a link in place of the guard, or a guard living somewhere else, is a rewrite waiting to happen
    for rel in MANIFEST_FILES:
        p = root / rel
        if not os.path.lexists(p):
            continue
        if p.is_symlink() or os.path.realpath(p) != os.path.realpath(root.resolve() / rel):
            print(f"  ✗ {rel} is a link or is not where it was installed → {os.path.realpath(p)}")
            problems.append(f"{rel} is not a plain file at its installed path")
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
    # the third side: a copy of the fingerprints outside the repository, which a rewrite of the repository cannot reach
    state, findings, recorded = verify_baseline(root)
    where = baseline_path(root) if state != "off" else Path("")
    if state == "off":
        print("  – baseline outside the repository — off (LUMIS_NO_BASELINE, or no home folder in this environment)")
    elif state == "absent":
        made = record_baseline_if_absent(root)
        if made:
            print(f"  ✓ baseline outside the repository — recorded now: {made}")
            print("    (expected right after install. If the guard has been here for a while, a missing baseline is itself a signal.)")
        elif has_manifest and not drifted:
            print(f"  – baseline outside the repository — cannot be written to {where.parent} (read-only home?); only the manifest in the repository is compared")
        else:
            print("  – baseline outside the repository — absent, and not recorded: the guard's files do not match the manifest they came with")
    elif state == "unreadable":
        print(f"  ✗ baseline outside the repository — {where} is not valid JSON")
        problems.append("the baseline outside the repository is unreadable: re-baseline with `scope_guard.py write-manifest` if the guard is the one you installed")
    elif state == "differs":
        print(f"  ✗ baseline outside the repository ({where}, recorded {recorded or 'unknown'}) — differs:")
        for item in findings:
            print(f"      {item}")
            problems.append(f"differs from the baseline outside the repository: {item}")
        print("    (after an Amend or a re-install this is expected: run `python scripts/scope_guard.py write-manifest` yourself."
              " If you changed nothing, the guard was rewritten. The hook refuses `write-manifest` to the agent.)")
    else:
        print(f"  ✓ baseline outside the repository — matches ({where}, recorded {recorded or 'unknown'})")
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


# --- rebuilding the markers of an installed config ---------------------------------------------------------------
# A founder who edited `.lumis/scope_guard.json` or `CONSTITUTION.md` by hand cannot get better markers by
# re-downloading the ZIP: the download would overwrite the architecture inventory they normalised (field report
# 2026-09-21). This command re-derives the markers in place, from the boundaries the config already carries, and
# leaves everything else alone. It is the founder's command: the hook refuses it to an agent exactly as it refuses
# `write-manifest` — `GUARD_SELF_RUN` whitelists `pre-tool|prompt|report|doctor` and nothing else, so a tool call
# naming this file with any other word is denied as `tamper`, `--dry-run` included. That is deliberate: a dry run
# prints what the real run would do, and an agent that can read the plan can argue for it.
def config_path(root: Path) -> Path | None:
    """Where `load_config` actually read from. `load_config` throws the path away and answers `EMPTY_CONFIG` for a
    missing *or* unparseable file, and writing that back would erase a hand-edited config over a JSON typo."""
    for candidate in (root / ".lumis" / "scope_guard.json", Path(__file__).resolve().parents[1] / ".lumis" / "scope_guard.json"):
        if candidate.exists():
            return candidate
    return None


def rebaseline(root: Path) -> tuple[dict, Path | None]:
    """The manifest in the repository and its copy outside it, taken again. Used by `write-manifest` and after
    `rebuild-markers` has rewritten a file the manifest fingerprints — otherwise `doctor` would report the guard
    as changed since install, which it is, by the founder, on purpose."""
    target = root / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(root)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest, write_baseline(root, manifest["files"])


def config_boundaries(cfg: dict) -> list[dict]:
    """The boundaries to derive from. A config written before `boundaries` existed carries only `non_goals`, and
    its ids are the positions in that list — the same numbering both generators use."""
    boundaries = [b for b in (cfg.get("boundaries") or []) if isinstance(b, dict) and str(b.get("text") or "").strip()]
    if boundaries:
        return [{"id": str(b.get("id") or f"NG-{i}"), "text": str(b["text"])} for i, b in enumerate(boundaries, 1)]
    return [{"id": f"NG-{i}", "text": str(ng)} for i, ng in enumerate(cfg.get("non_goals") or [], 1) if str(ng).strip()]


def config_vocabulary(cfg: dict) -> tuple[set, bool]:
    """(the product's own words, whether the config carried them).

    The pack's generator knows the founder's idea, their invariants and the approved stack; a config does not
    carry that prose, so LUMIS writes the vocabulary it used into `vocabulary`. Without that key — an older
    config — only the architecture's own names and the project name are known, and a word of the idea can be
    armed that the original generator correctly dropped. The diff says so instead of pretending otherwise."""
    stored = [str(w) for w in (cfg.get("vocabulary") or []) if str(w).strip()]
    if stored:
        return {w.lower() for w in stored}, True
    arch = cfg.get("architecture") or {}
    names: list[str] = [str(cfg.get("project") or "")]
    for key in ("entities", "endpoints", "top_level"):
        names += [str(n) for n in (arch.get(key) or [])]
    words: set = set()
    for name in names:
        words |= {w for w in normalize(name).split() if len(w) > 2}
    return words | {w[:-1] for w in words if w.endswith("s")} | {w + "s" for w in words}, False


def _ng_order(bid: str) -> tuple:
    """NG-10 after NG-9: the number sorts as a number, anything else keeps its spelling."""
    m = re.match(r"^NG-(\d+)$", str(bid or ""))
    return (0, int(m.group(1)), "") if m else (1, 0, str(bid or ""))


PRESERVED_ORIGINS = ("model", "founder")


def derive_config_markers(cfg: dict) -> dict:
    """The keywords, warn-only markers and trigger sources this config would have if it were generated today.

    Three sources go in, exactly as `code_scaffolder.generate_scope_guard_config` merges them: the curated
    capability lexicon, the markers a model proposed or the founder typed (which no offline derivation can
    reinvent — they are preserved by their recorded origin), and the derivation from the boundary's own words.
    Anything the config lists under `allowed_markers` never leaves here, and `pinned_keywords` always does."""
    boundaries = config_boundaries(cfg)
    vocabulary, vocabulary_stored = config_vocabulary(cfg)
    origins = {str(k).lower(): str(v) for k, v in (cfg.get("marker_origins") or {}).items()}
    allowed = {str(w).lower() for w in (cfg.get("allowed_markers") or [])}
    pinned = [str(w) for w in (cfg.get("pinned_keywords") or []) if str(w).strip()]
    old_sources = {str(k).lower(): str(v) for k, v in (cfg.get("trigger_sources") or {}).items()}
    old_keywords = [str(k) for k in (cfg.get("keywords") or [])]
    old_warn = [str(k) for k in (cfg.get("warn_keywords") or [])]

    keywords: list[str] = []
    warn_keywords: list[str] = []
    packages: list[str] = list(cfg.get("deny_packages") or [])   # preserved verbatim: the founder may have added some
    paths: list[str] = list(cfg.get("deny_paths") or [])
    trigger_sources: dict[str, str] = {}
    matched: dict[str, list[str]] = {}
    per_boundary: dict[str, dict] = {}
    for b in boundaries:
        bid, text = b["id"], b["text"]
        low = text.lower()
        added_block: list[str] = []
        added_warn: list[str] = []
        for cap, spec in CAPABILITY_TRIGGERS.items():
            if any(m in low for m in spec["match"]):
                matched.setdefault(cap, []).append(text)
                for t in spec["keywords"]:
                    added_block.append(t)
                for t in spec["packages"] + spec["paths"] + spec["keywords"]:
                    trigger_sources.setdefault(t.lower(), bid)
        # a marker the model proposed or the founder typed cannot be re-derived offline: it is kept by its origin
        for kw in old_keywords:
            if old_sources.get(kw.lower()) == bid and origins.get(kw.lower()) in PRESERVED_ORIGINS:
                added_block.append(kw)
        for kw in old_warn:
            if old_sources.get(kw.lower()) == bid and origins.get(kw.lower()) in PRESERVED_ORIGINS:
                added_warn.append(kw)
        blocking, warning = markers_for(text, vocabulary)
        added_block += blocking
        added_warn += warning
        for t in added_block:
            keywords.append(t)
            trigger_sources.setdefault(t.lower(), bid)
        for t in added_warn:
            warn_keywords.append(t)
            trigger_sources.setdefault(t.lower(), bid)
        per_boundary[bid] = {"text": text, "block": list(dict.fromkeys(added_block)), "warn": list(dict.fromkeys(added_warn))}

    def dedupe(xs: list) -> list:
        return list(dict.fromkeys(x for x in xs if x))

    # `pinned_keywords` goes first, before the cap: it is the documented way to keep a marker this rebuild cannot
    # re-derive, and appending it last meant a config that derives 320 keywords silently truncated away the very
    # markers the founder had just rescued (review 2026-09-21).
    keywords = [k for k in dedupe(pinned + keywords) if k.lower() not in allowed or k in pinned]
    blocking_keywords = keywords[:320]
    warn_only = [w for w in dedupe(warn_keywords) if w not in set(blocking_keywords) and w.lower() not in allowed][:240]
    return {
        "boundaries": boundaries, "per_boundary": per_boundary, "keywords": blocking_keywords,
        "warn_keywords": warn_only, "trigger_sources": trigger_sources, "capabilities": matched,
        "deny_packages": dedupe(packages), "deny_paths": dedupe(paths),
        "vocabulary_size": len(vocabulary), "vocabulary_stored": vocabulary_stored,
        "vocabulary_truncated": bool(cfg.get("vocabulary_truncated")),
        "cap_cut": len(keywords) - len(blocking_keywords),
        "pinned": pinned, "allowed": sorted(allowed),
    }


def rebuild_markers(root: Path, dry_run: bool = False) -> int:
    """`python scripts/scope_guard.py rebuild-markers [--dry-run]` — the founder's own command."""
    path = config_path(root)
    if path is None:
        print("No .lumis/scope_guard.json here — nothing to rebuild.", file=sys.stderr)
        return 1
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{path} is not valid JSON ({exc}) — nothing was written. Fix the file first.", file=sys.stderr)
        return 1
    if not isinstance(cfg, dict):
        print(f"{path} does not hold a JSON object — nothing was written.", file=sys.stderr)
        return 1
    fresh = derive_config_markers(cfg)
    if not fresh["boundaries"]:
        print("No boundaries in this config — nothing to rebuild.", file=sys.stderr)
        return 1
    old_keywords, old_warn = [str(k) for k in cfg.get("keywords") or []], [str(k) for k in cfg.get("warn_keywords") or []]
    old_sources = {str(k).lower(): str(v) for k, v in (cfg.get("trigger_sources") or {}).items()}
    origins = {str(k).lower(): str(v) for k, v in (cfg.get("marker_origins") or {}).items()}
    has_origins = bool(cfg.get("marker_origins"))
    new_block, new_warn = set(fresh["keywords"]), set(fresh["warn_keywords"])
    old_block, old_warn_set = set(old_keywords), set(old_warn)

    print(f"LUMIS scope guard — rebuilding markers from {path}")
    vocab_note = "" if fresh["vocabulary_stored"] else " (from ARCHITECTURE.md and the project name only: this config" \
                                                       " predates the stored vocabulary, so a word of your idea may be armed)"
    if fresh["vocabulary_stored"] and fresh["vocabulary_truncated"]:
        # the generator cut the list alphabetically; treating the remainder as complete would re-arm the tail
        vocab_note = " (the stored list was cut at its limit, so a word of yours late in the alphabet may be armed)"
    print(f"  {len(fresh['boundaries'])} boundaries · vocabulary: {fresh['vocabulary_size']} words{vocab_note}"
          f" · lexicon: {len(fresh['capabilities'])} capabilities matched")
    unknown: list[str] = []
    rows: dict[str, list[str]] = {}
    for b in fresh["boundaries"]:
        bid = b["id"]
        entry = fresh["per_boundary"].get(bid) or {"block": [], "warn": []}
        mine_block = [t for t in entry["block"] if t in new_block]
        mine_warn = [t for t in entry["warn"] if t in new_warn]
        gone = [t for t in old_keywords + old_warn
                if old_sources.get(t.lower()) == bid and t not in new_block and t not in new_warn]
        lines: list[str] = []
        for text in mine_block:
            if text not in old_block:
                lines.append(f"    + block  {text}" + ("   (pinned)" if text in fresh["pinned"] else
                                                       f"   ({origins.get(text.lower())})" if origins.get(text.lower()) in PRESERVED_ORIGINS else
                                                       "   (phrase)" if " " in text else "   (word)"))
        for text in mine_warn:
            if text in old_block:
                # not a removal: the word is still a marker, it just stopped refusing. This is the whole of the
                # 2026-09-21 fix — `python`, `curriculum`, `production` out of a long sentence are hints, not proof
                lines.append(f"    → warn   {text}   (was blocking; one word of a long sentence)")
            elif text not in old_warn_set:
                lines.append(f"    + warn   {text}")
        for text in gone:
            why = origins.get(text.lower()) if has_origins else ""
            if not why:
                unknown.append(text)
                why = "origin unknown — move it to \"pinned_keywords\" to keep it" if has_origins else \
                      "not reproduced by today's rules — move it to \"pinned_keywords\" to keep it"
            lines.append(f"    - {'block' if text in old_block else 'warn '}  {text}   ({why})")
        kept = [t for t in mine_block if t in old_block] + [t for t in mine_warn if t in old_warn_set]
        if lines:
            lines.append(f"      kept   {len(kept)} marker(s) unchanged" if kept else "      kept   nothing")
            rows[bid] = lines
    for bid in sorted(rows, key=_ng_order):
        text = next((b["text"] for b in fresh["boundaries"] if b["id"] == bid), "")
        print(f"  {bid}  \"{text[:110]}" + ("…\"" if len(text) > 110 else "\""))
        for line in rows[bid]:
            print(line)
    if not rows:
        print("  every boundary already carries exactly the markers today's rules derive — nothing to change.")
    downgraded = old_block & new_warn
    print(f"  ── totals: +{len(new_block - old_block)} blocking, -{len(old_block - new_block)} blocking "
          f"(of which {len(downgraded)} became warn-only), +{len(new_warn - old_warn_set - old_block)} warn, "
          f"-{len(old_warn_set - new_warn)} warn; {len(fresh['pinned'])} pinned kept; "
          f"{len(set(unknown))} removed with unknown origin")
    if fresh["cap_cut"]:
        print(f"     ({fresh['cap_cut']} marker(s) past the 320-keyword limit were cut; pinned ones were kept first)")
    if unknown:
        print("     (a marker with no recorded origin was either derived by an older LUMIS or typed here by hand.")
        print("      To keep any of them, paste this into .lumis/scope_guard.json and run this again:")
        print('      "pinned_keywords": ' + json.dumps(sorted(set(unknown)), ensure_ascii=False) + ")")
    if dry_run:
        print("--dry-run: nothing written.")
        return 0
    # The rebuild is destructive by design — that is the point of O3 — so the file as it was goes next to it
    # before a byte is changed. Without it the advice above is unusable after the fact: the words it names are no
    # longer in the config to copy from, and they exist only in the terminal scrollback (review 2026-09-21).
    backup = path.with_name(path.stem + ".prev.json")
    try:
        backup.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"could not write the backup {backup}: {exc} — nothing was changed.", file=sys.stderr)
        return 1
    # `{**cfg, **rewritten}`: every key this command does not own — architecture, deny_paths, deny_packages,
    # drift_phrases, design_non_goals, pinned_keywords, note, and anything a later LUMIS adds — survives verbatim
    rewritten = {
        "keywords": fresh["keywords"],
        "warn_keywords": fresh["warn_keywords"],
        "trigger_sources": fresh["trigger_sources"],
        "capabilities": fresh["capabilities"],
        "markers_rebuilt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if origins:  # a preserved marker keeps its recorded origin; one this rebuild dropped no longer has an entry
        rewritten["marker_origins"] = {k: v for k, v in (cfg.get("marker_origins") or {}).items()
                                       if str(k).lower() in {t.lower() for t in fresh["keywords"] + fresh["warn_keywords"]}}
    try:
        path.write_text(json.dumps({**cfg, **rewritten}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"could not write {path}: {exc}", file=sys.stderr)
        return 1
    print(f"written: {path} — {len(fresh['keywords'])} blocking, {len(fresh['warn_keywords'])} warn-only markers")
    print(f"the config as it was: {backup} (delete it when you are happy with the rebuild)")
    # the config is fingerprinted by the manifest, so a rebuild without this would show up as a guard changed
    # since install; the config is written first, or the manifest would fingerprint the old file
    manifest, outside = rebaseline(root)
    print(f"{MANIFEST}: {len(manifest['files'])} guard file(s) fingerprinted")
    print(f"baseline outside the repository: {outside}" if outside else
          "baseline outside the repository: not written (switched off, or the home folder is read-only)")
    return 0


# The disease this command exists to cure, as `doctor` can see it from outside: an armed `python`, `public` or
# `architecture` means the config was generated before 2026-09-21 (or hand-written), and the agent it guards
# cannot run the project's own tests. Advice, never a failure — the founder decides what their words mean.
def stale_markers(cfg: dict) -> list[str]:
    return sorted({k for k in (cfg.get("keywords") or [])
                   if " " not in str(k) and (str(k).lower() in COMMON_CODE_WORDS or str(k).lower() in FUNCTION_WORDS)})


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
    if mode == "request":
        argv = sys.argv[1:]
        reason = ""
        for i, arg in enumerate(argv):
            if arg == "--reason" and i + 1 < len(argv):
                reason = argv[i + 1]
            elif arg.startswith("--reason="):
                reason = arg.split("=", 1)[1]
        return write_request(reason.strip())
    if mode == "doctor":
        return doctor()
    if mode == "write-manifest":  # after an Amend, or when the founder edited the guard on purpose
        manifest, outside = rebaseline(project_root())
        print(f"{MANIFEST}: {len(manifest['files'])} guard file(s) fingerprinted")
        print(f"baseline outside the repository: {outside}" if outside else "baseline outside the repository: not written (switched off, or the home folder is read-only)")
        return 0
    if mode == "rebuild-markers":  # the founder re-derives the markers of a config they edited by hand
        # read straight from argv: `parse_args` answers (mode, agent) to five callers and swallows the rest
        return rebuild_markers(project_root(), dry_run="--dry-run" in sys.argv[1:])
    # first contact: the installed state is recorded outside the repository before any tool call is judged
    record_baseline_if_absent(project_root())
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
    command = str((tool_input or {}).get("command", ""))
    attempted_text, tool_path = text_of_tool_input(tool_name, tool_input)
    # the two exemptions a block already has: looking is not doing, and writing a boundary down is inside it.
    # A possible match must not nag about them either, or the founder learns to ignore the guard's stderr.
    looking = (is_command(tool_name, tool_input) and is_read_only_command(command)) or is_read_only_tool(tool_name, tool_input)
    documenting = not is_command(tool_name, tool_input) and is_prose_path(tool_path)
    warnings: list[str] = []
    marker_hits = [] if (looking or documenting) else check_warn_markers(cfg, tool_name, tool_input)
    if marker_hits:
        warnings.append(
            "🔎 LUMIS Scope Guard — for you to judge (this is not a violation): "
            + "; ".join(marker_hits)
            + ". A single word out of a long Non-Goal sentence is a hint, not proof: if this really is the feature "
              "the founder ruled out, stop and ask; if it is ordinary work, carry on — nothing is blocked.")
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
    tampered, touched_rules = check_tamper(tool_name, tool_input)
    if tampered:  # refusing the write is a mechanism; telling the agent not to touch the guard is only a promise
        emit_denial(agent,
                    "⛔ LUMIS Scope Guard blocked a change to the guard itself: " + ", ".join(tampered)
                    + ". The boundaries are lifted by the founder through LUMIS Amend, which regenerates these files together — "
                    "not by editing the hook, its config or the constitution. Ask the founder instead of working around it.")
        log_event(cfg, "tamper", tool_name, tool_input, [f"write to {f}" for f in tampered], agent, attempted=attempted_text or command)
        return 2
    leaks = secret_leaks(attempted_text or command, tool_path)
    if leaks:
        warnings.append("🔑 LUMIS Scope Guard: this change carries what looks like " + " and ".join(leaks)
                        + ". Check it before it lands in the repository; a fixture belongs in a *.example file or a test.")
        log_event(cfg, "warned", tool_name, tool_input, [f"possible secret: {k}" for k in leaks], agent, attempted="")
    if touched_rules:
        warnings.append("📄 LUMIS: this change rewrites the rules the agent reads (" + ", ".join(touched_rules)
                        + "). Keep your own notes, but the LUMIS section is regenerated by Amend — edits to it are lost and the boundaries stay.")
    for w in warnings:
        sys.stderr.write(w + "\n")
    hits = check_pre_tool(cfg, tool_name, tool_input)
    if hits and looking:
        # the agent is looking, not building: allow it and record that a boundary area was inspected
        log_event(cfg, "inspected", tool_name, tool_input, hits, agent, attempted=command or attempted_text)
        return 1 if warnings else 0
    if hits and documenting:
        # documenting a boundary is not crossing it: the ADR that explains the Non-Goal, the README line restating
        # it and the test that asserts the feature is absent were all refused as violations of the boundary they
        # were writing down — and each refusal then argued in the Amend dialog for lifting it (audit 2026-09-15).
        sys.stderr.write("📝 LUMIS Scope Guard: this file writes a Non-Goal down (" + "; ".join(hits)
                         + "). Documenting or testing a boundary is inside it — only the code that crosses it is not. "
                           "Allowed and logged as `noted`.\n")
        log_event(cfg, "noted", tool_name, tool_input, hits, agent, attempted=attempted_text)
        return 1
    if hits:
        emit_denial(agent,
                    "⛔ LUMIS Scope Guard blocked this change (CONSTITUTION.md, Article I — Non-Goals): "
                    + "; ".join(hits)
                    + ". The boundary can be lifted only by the founder (LUMIS Amend / a new consilium run), never by bypassing the hook.")
        log_event(cfg, "blocked", tool_name, tool_input, hits, agent, attempted=attempted_text)
        return 2
    if design_hits or arch_hits:
        log_event(cfg, "warned", tool_name, tool_input, design_hits + arch_hits, agent, attempted=attempted_text)
    if marker_hits:
        # its own event: `warned` is the visual contract and the architecture, `possible` is a boundary word that
        # may or may not mean anything. The Amend question "lift or keep?" must not be argued by a maybe.
        log_event(cfg, "possible", tool_name, tool_input, marker_hits, agent, attempted=attempted_text)
    return 1 if warnings else 0  # 1 = non-blocking: the warning is shown, the change proceeds


if __name__ == "__main__":
    raise SystemExit(main())
