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
        forbidden packages, paths or keywords listed in .lumis/scope_guard.json (a package as the whole name an import,
        an install or a manifest line brings in, never a word that starts with it) — the message names the
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
        `possible`): the word names the boundary it came from and leaves the judgement to you;
        three boundary classes the founder decides on — a new dependency, a push or deploy that leaves the machine,
        a write outside the project — are held for approval (`"classes"` in the config: allow | ask | block,
        logged as `held`); with `"mode": "observe"` nothing is refused except a change to the guard itself;
        where the LUMIS pre-commit check is installed, the plain spellings of a commit past it (`--no-verify`, `-n`,
        `-c` / `--config-env core.hooksPath=…`, a `GIT_CONFIG_*` variable set in the command, a `git config` write of
        core.hooksPath, a write to this repository's `.git/config`, `git commit-tree`) are held the same way, and a
        direct delete or overwrite of its file by path is refused as `tamper` (the limits: docs/BOUNDARY_CHECK_CI.md).
  * `python scripts/scope_guard.py prompt [--agent <name>]`
        adds a note to the context when the prompt names a boundary (a package, a path or a phrase — never a lone
        word) or contains a drift phrase ("quick fix for now", "while I'm in here", ...): advice, it never stops.
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
        inventory, the deny lists, `pinned_keywords` and everything else are kept (a config written before 2026-09-30
        also gets the lexicon's package families, `deny_package_prefixes`). `--dry-run` prints the diff and
        writes nothing; the real run saves the file as it was to `.lumis/scope_guard.prev.json` and re-baselines
        the manifest afterwards. Yours to run: the hook refuses it to the agent, `--dry-run` included.
  * `python scripts/scope_guard.py observe on|off` -> switch the guard to recording only (`on`) or back to refusing
        (`off`): rewrites the `mode` key of .lumis/scope_guard.json and re-baselines. Yours to run, like write-manifest.
  * `python scripts/scope_guard.py check-diff --base <ref> [--head <ref>] [--markdown f] [--sarif f] [--json f]`
        -> the same boundaries on a diff (a pull request in CI, `.github/workflows/lumis-boundary-check.yml`): added
        lines only, PASS / WARN / BLOCK, one markdown report, SARIF for code scanning, JSON; exit 2 on BLOCK, 1 when
        it could not run (never a PASS). `--diff <file>` or stdin read a diff without git. Read-only: the agent may
        run it too, without the output flags. `--staged [--format text]` reads the staged change against HEAD: the
        pre-commit check.
  * `python scripts/scope_guard.py install-pre-commit [--uninstall]` -> write (or remove) the git pre-commit hook that
        runs `check-diff --staged --format text` before each commit. Local only: `git commit --no-verify` skips it, and
        the pull request check reads the diff again. Yours to run: the hook refuses it to the agent.

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
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page; the reports carry emoji
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# The release this script belongs to — bump it on every change of this file. The pack writes the same string into
# .lumis/scope_guard.json as `hook_version`, so `doctor` can tell a config that expects a newer hook (keys the old
# script would ignore in silence) from a hook that is merely newer than its config (harmless: new keys take defaults).
HOOK_VERSION = "2026-10-01"

# --- the budget: a guard that cannot finish reading refuses (third review of 30.09) -------------------------------
# Claude Code gives a hook 60 s by default and treats one that runs longer as a non-blocking error: the change lands.
# Two review rounds found readings that ran past that on a crafted payload (160 KB of dashes: 119 s; 5 000 edits of a
# 5.5 MB file: 75 s). The regexes are linear again, every disk read and every edit's context is capped, and whatever is
# left is bounded by the clock: the hook records when it started, the content readers look at the clock line by line
# and edit by edit, and past SCAN_BUDGET_SECONDS the hook stops reading and REFUSES the call (exit 2, event `timeout`)
# — refused, not passed. The generators write `timeout: 60` into the Claude Code hook settings, so the budget is below
# the client's limit. `check-diff` has its own budget: past CI_SCAN_BUDGET_SECONDS the verdict is INCOMPLETE (exit 1).
SCAN_BUDGET_SECONDS = 20
CI_SCAN_BUDGET_SECONDS = 60
# How much of one text is read for packages: the content of a call, a file an Edit lands in, a manifest on disk. Past
# it a package is not read: the rest is reported as a possible match (WARN, exit 1) with the reason, never passed in
# silence. Keywords, phrases and paths are still matched in the whole text.
PACKAGE_READ_MAX = 1_000_000
EDIT_CONTEXT_MAX = 200         # edits of one call read with the file around them; the rest as their own text only
REPLACE_ALL_CONTEXT_MAX = 50   # occurrences of one `replace_all` edit read with the file around them
_SCAN = {"deadline": 0.0, "read": 0, "total": 0}


class ScanBudgetExceeded(Exception):
    """The hook's reading of a call ran past SCAN_BUDGET_SECONDS (`scan_checkpoint`): the call is refused."""


def start_scan_budget(seconds: float, started: float | None = None) -> None:
    """Arm the clock: `scan_checkpoint` raises once `seconds` have passed since `started` (default: now). Only the
    hook's `main` arms it; `check-diff`, the studio and the tests read without a deadline unless they arm it."""
    _SCAN.update(deadline=(time.monotonic() if started is None else started) + float(seconds), read=0, total=0)


def stop_scan_budget() -> None:
    _SCAN["deadline"] = 0.0


def scan_progress(read: int, total: int | None = None) -> None:
    """How far the reading of the call's lines got, for the refusal message."""
    _SCAN["read"] = read
    if total is not None:
        _SCAN["total"] = total


def scan_checkpoint() -> None:
    """Called by the content readers at line and edit granularity: raise ScanBudgetExceeded past the deadline."""
    if _SCAN["deadline"] and time.monotonic() > _SCAN["deadline"]:
        raise ScanBudgetExceeded()


# The tamper check's probes — git's own answer for a rewind (`git status`/`git diff`), `git clean -n`, `git ls-files`,
# the real path of what a removal takes — go to the disk or spawn git, 10-40 ms each: `git reset --hard HEAD; ` × 1 600
# took 64 s, past the client's 60 s, and the call went through (fourth review of 30.09). The loops look at the clock
# (`scan_checkpoint`), and one call gets TAMPER_PROBE_MAX probes: a command with more rewind or removal segments than
# that is refused as a change to the guard, the rest unprobed — refused, not passed.
TAMPER_PROBE_MAX = 64
_PROBES = {"left": TAMPER_PROBE_MAX}
TAMPER_PROBES_EXHAUSTED = (f"the command has more rewind or removal segments than the guard probes ({TAMPER_PROBE_MAX}): "
                           "the rest was not checked against the guard's files — refused, not passed; split the command")


class TamperProbesExhausted(Exception):
    """One call asked for more than TAMPER_PROBE_MAX tamper probes (`_take_probe`): refused as a change to the guard."""


def _take_probe() -> None:
    """Called before each probe of the tamper check: the clock first, then one of the call's TAMPER_PROBE_MAX probes."""
    scan_checkpoint()
    if _PROBES["left"] <= 0:
        raise TamperProbesExhausted()
    _PROBES["left"] -= 1

# The three decisions that are the founder's whatever the Non-Goals say: a new dependency changes the stack, a push
# or a deploy leaves the machine, a write outside the project is not this project's change. Missing key -> "ask".
DEFAULT_CLASSES = {"dependency": "ask", "outbound": "ask", "outside_root": "ask"}
CLASS_VERDICTS = ("allow", "ask", "block")

EMPTY_CONFIG = {"non_goals": [], "keywords": [], "warn_keywords": [], "deny_packages": [], "deny_paths": [], "drift_phrases": [], "design_non_goals": [],
                "mode": "enforce", "classes": dict(DEFAULT_CLASSES)}
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


def emit_ask(agent: str, message: str) -> int:
    """Hand the decision to the human, where the client can: Claude Code and Cursor show a permission prompt for an
    "ask" answer on exit 0. Codex, Windsurf and Copilot have no such answer, so they get the warning on stderr and
    exit 1 — the call proceeds and the founder reads why in the transcript and in the log. Returns the exit code."""
    if agent == "claude":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                 "permissionDecisionReason": message}}, ensure_ascii=False))
        return 0
    if agent == "cursor":
        print(json.dumps({"permission": "ask", "userMessage": message, "agentMessage": message}, ensure_ascii=False))
        return 0
    sys.stderr.write(message + "\n")
    return 1


def guard_mode(cfg: dict) -> str:
    """"observe" or "enforce" (the default, and whatever else the key says: a typo must not switch the guard off)."""
    return "observe" if str((cfg or {}).get("mode") or "").strip().lower() == "observe" else "enforce"


def class_verdict(cfg: dict, name: str) -> str:
    """allow | ask | block for one boundary class; a missing or unreadable value is "ask"."""
    classes = (cfg or {}).get("classes")
    value = str((classes if isinstance(classes, dict) else {}).get(name, DEFAULT_CLASSES.get(name, "ask"))).strip().lower()
    return value if value in CLASS_VERDICTS else "ask"


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
                         # the text filters a pipeline ends with. `grep … | grep -v scope_guard | cut -c1-330 | head` was
                         # refused as tampering because `cut` was an unknown program, which sent the line to the
                         # tamper check, where the quoted `scope_guard` read as loading the hook (bench series 24.09)
                         "cut", "tr", "jq", "nl", "tac", "column", "basename", "dirname", "realpath", "readlink",
                         "date", "whoami", "hostname", "printenv", "true", "false", "test", "xxd", "od", "strings",
                         "less", "more", "paste", "fold", "expand", "unexpand", "comm", "join", "rev", "seq", "yes",
                         # the same looks spelled in PowerShell: the agent on Windows must be able to read too
                         "get-content", "gc", "type", "get-childitem", "gci", "select-string", "sls", "get-item",
                         "gi", "test-path", "resolve-path", "measure-object", "get-location", "compare-object"}
GIT_READ_ONLY = {"log", "grep", "status", "show", "diff", "blame", "ls-files", "rev-parse", "rev-list", "shortlog",
                 "describe", "cat-file", "config"}
SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|\n]")
# `2>&1`, `>&2`, `&>` duplicate a descriptor and write no file: `cat CONSTITUTION.md 2>&1 | head` was refused as a
# write to the constitution (bench series 24.09)
WRITES_TO_FILE = re.compile(r">>?\s*(?!&|/dev/null\b|NUL\b)\S")


def reader_output_file(exe: str, args: list[str]) -> str:
    """The file an otherwise read-only command was told to write, or "". `sort -o f`, `uniq in out`, `tree -o f` and
    `git diff --output=f` look like looking: the 2026-09-23 audit replaced the guard's config with `sort -o
    .lumis/scope_guard.json cfg.json` while the hook counted it as a look, so neither the tamper nor the class check ran."""
    if exe in ("sort", "tree"):
        for i, a in enumerate(args):
            if a in ("-o", "--output"):
                return args[i + 1] if i + 1 < len(args) else ""
            if a.startswith("--output="):
                return a.split("=", 1)[1]
            # `sort -uo out`, `sort -oout`: the first `o` of a short cluster takes the rest, or the next word
            m = re.match(r"^-([A-Za-z]*?)o(.*)$", a) if exe == "sort" and not a.startswith("--") else None
            if m and not set(m.group(1)) & set("ktST"):
                return m.group(2) or (args[i + 1] if i + 1 < len(args) else "")
    if exe == "uniq":
        positional = [a for a in args if not a.startswith("-") or a == "-"]
        return positional[1] if len(positional) >= 2 else ""
    if exe == "git":
        for i, a in enumerate(args):
            if a.startswith("--output="):
                return a.split("=", 1)[1]
            if a == "--output" and i + 1 < len(args):
                return args[i + 1]
    return ""


# `git config` reads a value or writes one. Only the reading forms are a look: `git config alias.p push`,
# `git config remote.origin.url …` rewrite what a later `git p` or `git push` does (audit 2026-09-23).
GIT_CONFIG_WRITE_FLAGS = {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section",
                          "-e", "--edit"}
GIT_CONFIG_VALUE_FLAGS = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}


def git_config_writes(args_after_config: list[str]) -> bool:
    """True for a `git config …` that changes the configuration."""
    if any(a.lower() in GIT_CONFIG_WRITE_FLAGS for a in args_after_config):
        return True
    positional: list[str] = []
    skip = False
    for a in args_after_config:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a.lower() in GIT_CONFIG_VALUE_FLAGS
            continue
        positional.append(a)
    if positional[:1] and positional[0].lower() in ("set", "unset", "rename-section", "remove-section", "edit"):
        return True
    return len(positional) >= 2 and positional[0].lower() not in ("get", "list")


VERSION_OR_HELP = {"--version", "-V", "-v", "--help", "-h", "help", "version"}


def stream_editor_writes(exe: str, args: list[str]) -> bool:
    """True when sed/perl/awk would write a file by themselves: `-i` in any short cluster, `--in-place`, gawk's
    `-i inplace`, or a sed script that carries a `w file` command (`s/x/y/w out`, `/re/w out`)."""
    for a in args:
        if a == "--in-place" or a.startswith("--in-place=") or re.match(r"^-[A-Za-z]*i", a):
            return True
        # the file name may be the next word when the shell split the script at a space: `'s/a/b/w out.txt'`
        if exe == "sed" and re.search(r"(?:^|[;\s/}])w(?:\s*\S|$)", a) and not a.startswith("-"):
            return True
    return False


def is_read_only_command(command: str) -> bool:
    """True only when every segment is a known inspection command and nothing is redirected into a file.
    Anything we cannot read confidently (substitutions, unknown executables) is treated as not read-only."""
    text = str(command or "").strip()
    if not text or "$(" in text or "`" in text or WRITES_TO_FILE.search(text):
        return False
    # split outside quotes: `grep -E "webhook|retry" ARCHITECTURE.md` is one look, not a look and two unknown
    # programs named `retry"` — which sent the whole line to the tamper check (bench pilot 24.09)
    for segment, _sep in _split_shell(text):
        parts = segment.strip().split()
        if not parts:
            return False
        exe = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        exe = exe[:-4] if exe.endswith(".exe") else exe
        if reader_output_file(exe, [p.strip("'\"") for p in parts[1:]]):
            return False  # a look that writes a file is a write
        if exe == "git":
            sub = next((p for p in parts[1:] if not p.startswith("-")), "")
            if sub not in GIT_READ_ONLY or "--edit" in parts:
                return False
            if sub == "config" and git_config_writes(parts[parts.index(sub) + 1:]):
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
        elif parts[1:] and all(p.strip("'\"") in VERSION_OR_HELP for p in parts[1:]):
            continue  # `python --version`, `node -v`, `git --version`: the program prints and exits (series 24.09)
        elif exe in ("sed", "perl", "awk", "gawk"):
            # a stream editor prints unless told to edit in place: `sed -n 330,360p .lumis/scope_guard.json` is a
            # look, and the bench pilot of 24.09 logged it as tampering. `-i`/`--in-place` (and sed's `w file`
            # command) make it a write; a redirect is caught above.
            if stream_editor_writes(exe, [p.strip("'\"") for p in parts[1:]]):
                return False
        elif exe not in READ_ONLY_EXECUTABLES:
            return False
    return True


# --- the guard protects itself ---------------------------------------------------------------------------------
# "anything my user can write, the agent can write, including its own hook script and the config that registers
# it" — u/Foreign-Schedule3996, r/ChatGPTCoding, 2026-09-09. Telling the agent not to touch the guard is a
# promise; refusing the write is a mechanism. This is not a security boundary — a determined process with shell
# access can still reach the files — but no rewrite happens quietly through a tool call.
# The workflow that runs the same boundaries on every pull request (`check-diff`, below). An agent that rewrote it
# would switch the second checkpoint off as quietly as an edit of the hook's config switches off the first; the
# manifest fingerprints it only where it exists (`build_manifest` skips a file that is not there).
CI_WORKFLOW_PATH = ".github/workflows/lumis-boundary-check.yml"
GUARD_FILES = (
    ".lumis/scope_guard.json", ".lumis/guard.log", ".lumis/guard.manifest.json",
    "scripts/scope_guard.py",
    ".claude/settings.json", ".cursor/hooks.json", ".codex/hooks.json", ".windsurf/hooks.json",
    ".github/hooks/lumis-scope-guard.json",
    "CONSTITUTION.md",
    # Claude Code reads the project-local override too, and `{"disableAllHooks": true}` there switches this hook off
    # as surely as an edit of settings.json does (audit 2026-09-23). It is not fingerprinted (see MANIFEST_FILES):
    # the client itself writes it whenever the founder clicks "always allow".
    ".claude/settings.local.json",
    CI_WORKFLOW_PATH,
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
# log. Exactly four words are open to the agent — report, doctor, request, and `check-diff` with its input flags
# only (`--base`, `--head`, `--diff`, `--root`, `--staged`, `--format markdown|text`, `--help`: it reads git and
# prints — `--staged --format text` is what the pre-commit check runs, review 2026-10-01; with `--markdown`, `--sarif` or
# `--json` it writes a file, and that spelling is judged like any other command naming the hook — refused as
# `tamper`) — and every other word naming this file —
# `write-manifest`, `rebuild-markers`, `observe`, with or without `--dry-run` — stays a `tamper` refusal:
# re-baselining, re-deriving the markers and switching the mode are the founder's, run by them in their own shell.
# `pre-tool` and `prompt` were open too until 2026-09-23: they append to .lumis/guard.log, so an agent could pipe any
# payload in and forge journal lines — a fake refusal, or noise that pushes real events out of the studio's view.
# The separator is either slash: on Windows, where these agents mostly run, PowerShell tab-completion produces
# `.\scripts\scope_guard.py`, and the two documented read-only commands were refused to the agent for the spelling
# alone (review 2026-09-21). Everything else in this file already normalises backslashes; this pattern did not.
GUARD_SELF_RUN = re.compile(
    r"^\s*(?:python3?|py)(?:\s+-X\s+utf8)?\s+(?:\.[\\/])?scripts[\\/]scope_guard\.py\s+"
    r"(?:(?:report|doctor|request|--help|-h|help)\b[^>|;&\n]*"
    r"|check-diff(?:\s+(?:--(?:base|head|diff|root)(?:=|\s+)[^\s>|;&<`$]+|--format(?:=|\s+)(?:markdown|text)"
    r"|--staged|--help|-h))*)"
    r"(?:\s+2>&1)?\s*$", re.I)


MANIFEST = ".lumis/guard.manifest.json"
# the log is meant to grow and the manifest cannot fingerprint itself; the local settings are the client's to rewrite
MANIFEST_FILES = tuple(f for f in GUARD_FILES if f not in (".lumis/guard.log", MANIFEST, ".claude/settings.local.json"))


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
    _take_probe()
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
    _take_probe()
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
        _take_probe()
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
    _take_probe()
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


# the options of `sudo` / `doas` that take a value (`sudo -u deploy pip install …`): read only for packages
# (`_command_words(sudo_values=True)`); the tamper check and the classes read `sudo` as they always did
SUDO_VALUE_FLAGS = {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from", "-D",
                    "--chdir", "-r", "--role", "-t", "--type", "-U", "--other-user", "-T", "--command-timeout"}


def _wrapped_command(segment: str, sudo_values: bool = False) -> str:
    """The command a wrapper runs: `powershell -c "Remove-Item -Recurse .lumis"` -> `Remove-Item -Recurse .lumis`.
    Empty when the segment is not a wrapper. `sudo_values`: the value of a `sudo`/`doas` option that takes one
    (`-u deploy`) is skipped too."""
    parts = str(segment or "").strip().split()
    if not parts:
        return ""
    exe = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    exe = exe[:-4] if exe.endswith(".exe") else exe
    if exe not in SHELL_WRAPPERS:
        return ""
    rest = parts[1:]
    while rest and (rest[0].startswith("-") or rest[0].isdigit() or (rest[0].startswith("/") and len(rest[0]) <= 3)):
        flag = rest.pop(0)  # -c, -Command, -NoProfile, /c, the seconds of `timeout 5 …`
        if sudo_values and exe in ("sudo", "doas") and flag in SUDO_VALUE_FLAGS and rest:
            rest.pop(0)
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
            scan_checkpoint()  # a segment's arguments and the segments themselves are read under the clock
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


# a heredoc opener — never the `<<<` of a here-string, whose word is the data itself (`tee x <<< 'resend'`)
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
_HERE_STRING = re.compile(r"<<<\s*(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|(\S+))")
_MESSAGE_ARG = re.compile(r"(\s(?:-m|-am|--message)(?:\s+|=))(\"(?:[^\"\\]|\\.)*\"|'[^']*')")


def _write_target_of_line(line: str) -> str:
    """Where a shell line sends its data: the redirect target, or what `tee` writes."""
    m = re.search(r">>?\s*([^\s|;&]+)", line) or re.search(r"\btee\b\s+(?:-a\s+)?([^\s|;&]+)", line)
    return m.group(1).strip("'\"") if m else ""


# A heredoc that becomes a commit message: `git commit -m "$(cat <<'EOF' … EOF)"` (Claude Code's own commit form) or
# `git commit -F - <<EOF`. Its body is the message whatever quotes it holds; `_MESSAGE_ARG` stops at the first inner
# quote, and the rest of the body was read as commands — `Checked; git push after review` was held as a push.
_MESSAGE_HEREDOC = re.compile(r"(?:\s(?:-m|-am|--message)(?:\s+|=)[\"']?\$\(\s*cat\b|\s(?:-F|--file)(?:\s+|=)-(?:\s|$))")
# what copies a heredoc into a file unchanged; anything else fed a heredoc (python, bash, psql) runs it
_HEREDOC_WRITERS = {"cat", "tee"}


def _heredoc_feeds_a_writer(line: str) -> bool:
    """`cat > Dockerfile <<'EOF'`, `cat <<EOF > notes.txt`, `tee x.yml <<EOF`: the body is file content."""
    for segment in SEGMENT_SPLIT.split(line):
        if "<<" in segment:
            words = segment.strip().split()
            return bool(words) and words[0].rsplit("/", 1)[-1].lower() in _HEREDOC_WRITERS
    return False


def _command_without_data(text: str, files_too: bool = False) -> str:
    """The command minus the data it carries into a document: a heredoc body written to a prose file, a commit
    message. A note in DECISION_LOG.md that names CONSTITUTION.md is a note about the guard, not a change to it —
    the founder's agent was refused three times in a row for exactly that (field report 2026-09-22). A heredoc fed
    to an interpreter, or written anywhere but a prose file, keeps its body: that is a script, and a script is read
    as a command.

    `files_too` also drops the body `cat`/`tee` writes into any file (a Dockerfile, a CI workflow, notes.txt): the
    boundary classes judge what a command *runs*, and file content written through a shell is judged like the same
    content written with the Write tool. The tamper and Non-Goal checks keep the default: for them a script body
    written to disk is still a script."""
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
        as_data = bool(m) and (_MESSAGE_HEREDOC.search(line) is not None
                               or (files_too and bool(target) and _heredoc_feeds_a_writer(line)))
        if m and (as_data or (target and is_prose_path(target))) and not _mentions_guard_file(_clean_path(target), GUARD_FILES):
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
        _PROBES["left"] = TAMPER_PROBE_MAX
        try:
            files = list(_guard_targets_of_command(command))
        except TamperProbesExhausted:
            files = [TAMPER_PROBES_EXHAUSTED]
        for name in _mentions_guard_file(command, GUARD_FILES):
            # named in the text but not a target the parser can see: the refusal says so, so the agent knows whether
            # to reword a note or to stop (the field report: «three rounds to find out which»)
            if not any(name in hit for hit in files):
                files.append(f"{name} (named in the command text)")
        if _touches_baseline(command):
            files.append("the guard's baseline outside the repository (~/.lumis)")
        if HOOK_AS_MODULE.search(command) and not any("scope_guard" in hit for hit in files):
            files.append("scripts/scope_guard.py (loaded as a module: its founder-only commands run without their names)")
        files += [hit for hit in pre_commit_tamper(command=command) if hit not in files]
        return files, _mentions_guard_file(command, GUARD_TEXT_FILES)
    targets = [p for p in [path] + destination_paths(tool_name, tool_input) if p]
    if not targets:
        return [], []
    files: list[str] = []
    rules: list[str] = []
    for target in targets:
        for name in _mentions_guard_file(_clean_path(target), GUARD_FILES):
            if name not in files:
                files.append(name)
        if (_touches_baseline(target) or _touches_baseline(os.path.realpath(os.path.expanduser(str(target))))) \
                and "the guard's baseline outside the repository (~/.lumis)" not in files:
            files.append("the guard's baseline outside the repository (~/.lumis)")
        linked = _resolves_to_guard(target)
        if linked and linked not in files and f"{linked} (through a link)" not in files:
            files.append(f"{linked} (through a link)")
        rules += [n for n in _mentions_guard_file(_clean_path(target), GUARD_TEXT_FILES) if n not in rules]
    files += [hit for hit in pre_commit_tamper(paths=targets) if hit not in files]
    return files, rules


# `python -c "import sys; sys.argv=['g','observe','on']; sys.path.insert(0,'scripts'); import scope_guard;
# scope_guard.main()"` ran the founder's `observe on` — mode switched, manifest and baseline re-taken, nothing on
# record — because the command never spells `scope_guard.py` (audit 2026-09-23). The module name counts as the file.
# A name assembled at run time ('scr' + 'ipts/scope_' + 'guard.py') is still invisible: the same class as base64.
HOOK_AS_MODULE = re.compile(r"(?<![\w.\-])scope_guard(?![\w\-])", re.I)
# where a move or copy tool names the path it writes to; `path` alone missed mcp__filesystem__move_file's target
DEST_KEYS = ("destination", "dest", "target", "target_path", "destination_path", "new_path", "newPath", "to")


def destination_paths(tool_name: str, tool_input: dict) -> list[str]:
    """The second path a file tool writes: the destination of a move or a copy (and, for a move, the source it
    removes). Only for a tool whose name says it writes; a read tool's `target` is not a write."""
    tool_input = tool_input or {}
    words = tool_words(tool_name)
    if is_command(tool_name, tool_input) or not any(w in WRITE_TOOL_WORDS for w in words):
        return []
    out = [str(tool_input[k]) for k in DEST_KEYS if isinstance(tool_input.get(k), str) and tool_input.get(k)]
    if any(w in ("move", "rename", "delete", "remove") for w in words):
        out += [str(tool_input[k]) for k in ("source", "src", "old_path", "oldPath", "from")
                if isinstance(tool_input.get(k), str) and tool_input.get(k)]
    return out


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
        if low.startswith("@"):
            # a name written as code (`@Transactional`, derived from «never use @Transactional»): that name exactly,
            # in any case — `@TransactionalEventListener` and `@transactionals` are other names (2026-09-29). Also
            # fully qualified, as Java, Kotlin and TypeScript write an annotation or a decorator:
            # `@org.springframework.transaction.annotation.Transactional`, `@jakarta.transaction.Transactional`.
            qualifier = r"(?:[a-z_$][\w$]*\.)*" if re.fullmatch(r"@[\w$]+", low) else ""
            pattern = re.compile(r"(?<![\w@$.])@" + qualifier + re.escape(low[1:]) + r"(?![\w$])")
        elif len(words) > 1:
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


def _keyword_found(keyword: str, low: str, spelled: str) -> bool:
    """A keyword in the lower-cased text or in its camel-case-opened spelling. A name written as code (`@…`) is
    looked for as written only: opened up, `@TransactionalEventListener` would read as `@transactional event …`."""
    need = _keyword_need(keyword)
    if need and need not in low and need not in spelled:
        return False  # every match holds this substring: a plain search first (a 2.8 MB file, third review of 30.09)
    pattern = keyword_pattern(keyword)
    return bool(pattern.search(low) or (not str(keyword).lstrip().startswith("@") and pattern.search(spelled)))


@lru_cache(maxsize=4096)
def _keyword_need(keyword: str) -> str:
    """A substring every match of `keyword_pattern(keyword)` contains: the name of an `@name`, the first word of a
    phrase, the stem of a single word."""
    low = str(keyword or "").lower().strip()
    if low.startswith("@"):
        return low[1:].split(".")[-1]
    words = low.split()
    if len(words) > 1:
        return words[0]
    return low[:-1] if (len(low) > 4 and low.endswith("s") and not low.endswith("ss")) else low


# --- a forbidden package: a whole module name where code brings it in (2026-09-30) ------------------------------------
# Until hook 2026-09-29 a package was found as a substring — `import {pkg}`, `from {pkg}`, `require('{pkg}` — or as a
# token between spaces, quotes and slashes. Under «No payment collection or billing; No native mobile apps» (`expo`
# from the lexicon) that refused `import exportCsv from './exportCsv'`, `require('export-to-csv')`, `import exporter
# from 'exporter'`, `import expoConfig from './expo.config'` and Python's `import export_utils`; `ws` refused openpyxl's
# `ws = wb.active` and `import ws_client`, `resend` refused `import resend_queue`, `pika` refused `import pikachu` —
# while `import * as Notifications from 'expo-notifications'` passed. A package is now the whole name a statement
# brings in, read per language:
#   - JS/TS: the specifier of `import … from '<spec>'`, `import '<spec>'`, `export … from '<spec>'`, `require('<spec>')`,
#     `require.resolve('<spec>')`, `import('<spec>')` is the package, a subpath of it (`expo/config`) or a package of the
#     scope named after it (`@expo/vector-icons` for `expo`, `@stripe/stripe-js` for `stripe`), also fetched from a
#     package CDN (`https://esm.sh/resend@2`). A local specifier (`./`, `../`, `/`, `~/`, `@/`, `#`) is never a
#     package, the name an import binds (`import exportCsv from …`) is never read, and `from '<x>'` counts only in an
#     import or export statement (`Imported from 'ws' module` in a string is not one);
#   - Python: the top-level module of `import <mod>[.sub] [as x]` / `from <mod>[.sub] import …`, `-` and `_` alike
#     (`paypal-checkout` is `import paypal_checkout`) — the whole module, never its start (`export_utils`, `wsgiref`);
#   - Java, Kotlin, C#, Rust, PHP, Go, Ruby: the vendor's part of the imported path, never a module of the project's
#     own or a standard namespace — the name after a reversed domain (`com.stripe.Stripe`; `javax.xml.ws`,
#     `org.springframework.ws` and `com.acme.api.ws` are not the package `ws`), the first segment of a C#, Rust, PHP or
#     Ruby path (`using Stripe;`, `use stripe::Client`, `use Stripe\StripeClient`, `require 'stripe'`; not
#     `using Acme.Integration.Ws;`, `use crate::ws`, `use App\Mail\Resend`), a Go module's owner or repository
#     (`github.com/stripe/stripe-go/v76`; not `github.com/acme/app/internal/ws`);
#   - a manifest line (`package.json` / `composer.json` keys, `requirements*.txt`, `pyproject.toml`, `Pipfile`,
#     `Cargo.toml`, `go.mod`, `Gemfile`) and a requirement line of `constraints*.txt`, `tox.ini`, `setup.cfg` or a conda
#     `environment.yml`: the dependency's name, with the dependency class's own readers;
#   - a shell command, and an install command written into a file (a Dockerfile `RUN`, its exec form `RUN ["pip",
#     "install", "x"]`, a CI `run:`, a package.json script): the package installed or run by name — `pip install stripe`,
#     `npm i expo`, `yarn add ws`, `npx expo start`, `npm create expo-app` (that is `create-expo-app`), also for the whole
#     machine (`npm i -g`, `pipx`, `uv tool`, `cargo install`, `go install`, `brew install`); in a command the agent runs,
#     also the package's own program (`expo start`, `flutter run`, `python -m celery`). What a command writes into a file
#     (`echo 'resend==2' >> requirements.txt`, a heredoc) is read as that file's content, and the code a heredoc feeds
#     an interpreter as that language's. `npm install export-to-csv` is another package: the dependency class holds it
#     like any new one.
# A statement written over several lines — a trailing backslash (`RUN pip install \`, `import os, \`, a hashed
# requirement), a `require(` or `import(` left open at the end of a line, an exec-form array left open — is read as one
# line too (`statement_spans`). A bare word of code — `ws = wb.active`, `const expo = 1` — is none of these and is not a
# package hit: a word the founder wants refused wherever it is written is a keyword of the lexicon, not a package. A
# request (the prompt hook) and the data a command carries (a commit message) are prose and keep the word reading: a
# package named in a sentence is how a person names it.
#
# A family of packages is named explicitly: `deny_package_prefixes` (the lexicon's `packages_prefix`) — `expo-`,
# `@expo/`, `react-native-`, `@react-native/` for native mobile apps — refuses every JS/npm name that starts with one
# (`expo-notifications`, `expo-router`, `react-native-maps`) — an npm name only: `pip install expo-helpers` is another
# ecosystem's package, held by the dependency class like any new one. A hyphen is not a family separator in general:
# `ws-…` and `resend-…` are unrelated packages. A config written before 2026-09-30 has no families until
# `rebuild-markers`.
#
# Reading a line costs one pass over it: an install command inside a line is read from its start to its end (a shell
# separator, the closing quote, or `INLINE_WINDOW` characters), once, and only when the words after the manager install
# or run something (`go back to the dashboard` is English, not `go`). The hook 2026-09-30 as first built re-read the rest
# of the line at every match, and a one-line JSON of 60 000 characters took 30 s (review 30.09).
LOCAL_SPECIFIER_PREFIXES = (".", "/", "~/", "@/", "#")
# The import statements a file's language has, by extension. Any other file (or no file at all) is read with every form
# except the JVM's dotted `import a.b.C`, which it reads as Python's; an SQL file with none (`FROM "stripe"` is a table).
IMPORT_LANGUAGES = {
    **{ext: "js" for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte", ".astro",
                             ".html", ".htm")},
    **{ext: "py" for ext in (".py", ".pyi", ".pyx")},
    **{ext: "jvm" for ext in (".java", ".kt", ".kts", ".scala", ".groovy")},
    ".cs": "cs", ".rs": "rs", ".php": "php", ".go": "go", ".rb": "rb", ".rake": "rb", ".sql": "none",
}
# `from '<spec>'` of an import or export statement: after `import`/`export` at the start of a statement (a line, or after
# `;`, `{`, `}`, the `>` of a `<script>` tag, a closing `*/`), or on the line that closes a multi-line one
# (`} from 'ws'`); minified `from"ws"` too. A `from '…'` inside a string or a template literal is not an import.
# Read from each `from '…'` backwards over its clause (`_js_from_specs`), at most JS_CLAUSE_MAX characters: the one
# regex this replaced scanned forward from every `{import`/`}import` of a line to its end, and a line of 100 000
# characters of them took 12 s (review 30.09).
JS_FROM_SPEC_RE = re.compile(r"\bfrom\s*(['\"])([^'\"\n]+)\1")
JS_CLAUSE_START_RE = re.compile(r"(?:[{}>]|\*/)\s*(?:import|export)\b")
JS_CLAUSE_MAX = 4000
_CLAUSE_STOP_RE = re.compile(r"[;'\"`\n]")
# `require('x')`, `require.resolve('x')`, `import('x')`, also with a bundler's comment first
# (`import(/* webpackChunkName: "mail" */ 'nodemailer')`, read with the comments taken out first:
# `_without_block_comments`) and with options after (`import('x', { with: … })`). No nested quantifier: the form with
# `(?:/\*.*?\*/\s*)*` inside took exponential time on `import(` and forty `/* a */` (review 30.09).
JS_CALL_RE = re.compile(r"\b(?:require(?:\.resolve)?|import)\s*\(\s*(['\"`])([^'\"`\n]+)\1\s*[,)]")
JS_SIDE_EFFECT_RE = re.compile(r"(?:^|(?<=[;{}>]))\s*import\s*(['\"])([^'\"\n]+)\1", re.M)
_PY_MODULE = r"[A-Za-z_][\w.]*"
# at the start of a statement — a line, or after `;`, `:`, a quote, `(` (`python -c "import stripe"`) or a comment
# marker (then it is a comment line, `noted`) — and the module list ends the statement: `import exportCsv from './x'`
# is not Python.
PY_IMPORT_RE = re.compile(r"(?:^|(?<=[;:\"'`(#/]))\s*import\s+(" + _PY_MODULE + r"(?:\s+as\s+\w+)?(?:\s*,\s*" + _PY_MODULE
                          + r"(?:\s+as\s+\w+)?)*)\s*(?=$|[;#)\"'`]|\\n)", re.M)
PY_FROM_RE = re.compile(r"(?:^|(?<=[;:\"'`(#/]))\s*from\s+(\.*" + _PY_MODULE + r"|\.+)\s+import\b", re.M)
PY_DYNAMIC_RE = re.compile(r"\b(?:import_module|__import__)\s*\(\s*(?:name\s*=\s*)?['\"]([A-Za-z_][\w.]*)['\"]")
JVM_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.M)
CS_USING_RE = re.compile(r"^\s*(?:global\s+)?using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", re.M)
RUST_USE_RE = re.compile(r"^\s*(?:pub(?:\s*\([^)]*\))?\s+)?(?:use\s+(?:::)?(\w+(?:::\w+)*)|extern\s+crate\s+(\w+))", re.M)
PHP_USE_RE = re.compile(r"^\s*use\s+(?:function\s+|const\s+)?\\?(\w+(?:\\\w+)*)", re.M)
GO_IMPORT_RE = re.compile(r"^\s*import\s+(?:[\w.]+\s+)?\"([^\"]+)\"", re.M)
GO_BLOCK_LINE_RE = re.compile(r"^\s*(?:[\w.]+\s+)?\"([^\"]+)\"\s*(?://.*)?$")
RUBY_REQUIRE_RE = re.compile(r"^\s*require\s*\(?\s*['\"]([^'\"]+)['\"]", re.M)
# the top-level domains a Java/Kotlin/Scala package starts with when it is a reversed domain: the vendor is the next name
# (`com.stripe`, `io.socket`); any two-letter first name counts too (`de.`, `uk.`)
REVERSED_DOMAIN_ROOTS = frozenset({"com", "org", "net", "io", "dev", "co", "me", "app", "ai", "edu", "gov", "mil", "info",
                                   "biz", "xyz", "tech", "cloud", "sh", "gg", "tv", "pro", "name"})
# a Rust path that starts in the project's own crate
RUST_LOCAL_ROOTS = frozenset({"crate", "self", "super"})
# the readings whose name is an import path with a vendor's part (`_import_roots`)
IMPORT_PATH_READINGS = {"jvm": ".", "cs": ".", "rust": "::", "php": "\\", "ruby": "/", "go": "/"}
# where a module is fetched by URL and the URL names the npm package: `https://esm.sh/resend@2.0.0` (Deno, Supabase edge
# functions), `https://cdn.jsdelivr.net/npm/stripe@14/+esm`, `https://unpkg.com/expo@51/…`, `https://deno.land/x/…`
PACKAGE_CDN_HOSTS = frozenset({"esm.sh", "cdn.esm.sh", "cdn.skypack.dev", "unpkg.com", "cdn.jsdelivr.net", "esm.run",
                               "jspm.dev", "dev.jspm.io", "ga.jspm.io", "deno.land"})
_CDN_PATH_PREFIX = re.compile(r"^(?:(?:v\d+|stable|pin|npm|x)/)+")
# what a manager is read as: a PyPI name (`-`, `_`, `.` alike), an npm name (scopes, subpaths, families), a Go module
# (its owner or repository), a Composer vendor/package (either name), or one name compared the PyPI way
MANAGER_READINGS = {**{m: "pip" for m in ("pip", "uv", "uvx", "poetry", "pipenv", "pipx", "conda", "mamba", "micromamba",
                                          "pdm", "rye")},
                    **{m: "npm" for m in ("npm", "pnpm", "yarn", "bun", "expo")}, "go": "go", "composer": "slash"}
# installs for the whole machine rather than the project: not a dependency of this project, still an install
SYSTEM_INSTALLERS = {"brew", "choco", "scoop", "winget", "apt", "apt-get", "snap", "dnf", "yum"}
JS_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
JS_RUN_SUBCOMMANDS = {"exec", "dlx", "x"}         # `npm exec x`, `pnpm dlx x`, `yarn dlx x`, `bun x x` run package x
JS_CREATE_SUBCOMMANDS = {"create", "init"}       # `npm create expo-app` runs `create-expo-app`
NPX_RUNNERS = ("npx", "pnpx", "bunx")
# where an install command starts inside a line of a file: a Dockerfile `RUN`, a CI `run:`, a package.json script
_INLINE_MANAGERS = (r"pip\d*(?:\.\d+)?|pipx|python\d*(?:\.\d+)?|py|uvx?|poetry|pipenv|pdm|rye|npm|pnpm|yarn|bun|npx|pnpx|bunx|"
                    r"expo|cargo|go|gem|bundle|composer|conda|mamba|micromamba|dotnet|brew|choco|scoop|winget|apt|"
                    r"apt-get|snap")
# The manager may be written with its path (`RUN /opt/venv/bin/pip install`, `.venv/bin/pip install`,
# `.venv\Scripts\pip install`), after a Makefile recipe's prefix (`\t@pip install`, `\t-pip install`) or kept in a
# variable named after it (`$PIP install`, `${NPM} i`, make's `$(PIP) install`): until the second review of 30.09 only
# a manager right after a space or a quote was read. A path segment holds none of the characters a command can start
# after, and a variable's name is bounded: every start scans only its own word, so a line is still read in one pass.
_MANAGER_VARIABLE = r"\$[{(]?[A-Za-z_]{0,40}(?:PIP|NPM|PNPM|YARN)[A-Za-z0-9_]{0,40}[})]?"
# The prefix is at most three characters and the word after it starts with a letter, `$`, `.` or a slash (the third
# review of 30.09: `[@+\-]*` followed by a path class that also takes `-` backtracked quadratically — a line of 160 KB
# of dashes took 119 s; possessive quantifiers need Python 3.11 and the hook runs on 3.9). A line that names none of the
# managers is not read at all (`MANAGER_WORD_RE`). A path may also start with `~`, `%`, `_` or a digit
# (`~/.local/bin/pip`, `%APPDATA%\Python\Scripts\pip`, `_venv/bin/pip`: fourth review of 30.09) — never with a `-`.
INLINE_COMMAND_RE = re.compile(r"(?:^|(?<=[\s\"'`(\[,:=;&|]))[@+\-]{0,3}(?:sudo\s+)?(?=[A-Za-z0-9$./\\~%_])"
                               r"(?:[^\s\"'`\\/(\[,:=;&|]*[\\/])*(?:" + _INLINE_MANAGERS + r"|" + _MANAGER_VARIABLE
                               + r")\s+\S", re.I)
MANAGER_WORD_RE = re.compile(r"pip|py|uv|poetry|pdm|rye|npm|yarn|bun|npx|pnpx|expo|cargo|go|gem|bundle|composer|conda|"
                             r"mamba|dotnet|brew|choco|scoop|winget|apt|snap", re.I)
# the exec form of a Dockerfile `RUN` / `CMD` or a YAML `command:` — `["pip", "install", "resend"]` — whose first word is
# a manager: the same command, written as a JSON array
EXEC_FORM_RE = re.compile(r"\[\s*(['\"])(?:sudo|" + _INLINE_MANAGERS + r")\1\s*,[^\]\n]*\]", re.I)
# the words that make a manager's command an install or a run of a package, among the three after it: `pip install`,
# `npm i`, `yarn add`, `go get`, `composer require`, `pnpm dlx`, `npm create`, `uv tool install`, `python -m`. `go back to
# the dashboard` has none, and is not read (review 30.09: every ` go ` of a one-line JSON was read to the end of the line).
INLINE_VERBS = frozenset({"install", "i", "in", "add", "a", "get", "require", "reinstall", "inject", "exec", "dlx", "x",
                          "create", "init", "run", "tool", "global", "pip", "-m"})
# an install command inside a line is read up to its end — a shell separator, the closing quote — or this many characters
INLINE_WINDOW = 20000
# A statement written over several lines (`statement_spans`): a call to `require(` / `import(` / `import_module(` left
# open at the end of a line, and an exec-form array left open (`RUN [` … `]`, `command: [` … `]`). A trailing
# backslash is the third. At most STATEMENT_MAX_LINES lines and STATEMENT_MAX_CHARS characters are joined.
OPEN_CALL_RE = re.compile(r"\b(?:require(?:\.resolve)?|import|import_module|__import__)\s*\(\s*$")
OPEN_EXEC_FORM_RE = re.compile(r"(?:^\s*(?:RUN|CMD|ENTRYPOINT)\s+|\b(?:command|entrypoint|args)\s*:\s*)\[[^\]]*$", re.I)
# A JS/TS import or export whose `from '…'` comes on a later line (`import { Resend,` / `  CreateEmailOptions } from
# 'resend';`, `import Constants` / `  from 'expo';`): a line that starts one and holds no quote and no `;` yet. Only in
# a JS/TS file, or text of no known language (`_js_import_end`). One that opens a brace is joined only while the lines
# are inside it, up to the line holding the `}`; then — and for one with no open brace, at once — the `from '…'` must
# follow on that line or the next non-empty lines (`from` and the module may take two). A comment line never closes
# it (the third review of 30.09: `export {` … `}` then `// … from 'resend' webhooks` was read as an import).
OPEN_JS_IMPORT_RE = re.compile(r"^\s*(?:import\b(?!\s*[(.=:])|export\s+(?:type\s+)?(?:\{|\*))[^'\"`;]*$")
JS_FROM_TAIL_RE = re.compile(r"^\s*from\s*(['\"])[^'\"\n]+\1")
JS_FROM_PREFIX_RE = re.compile(r"^\s*(?:from\s*)?$")
JS_COMMENT_LINE_RE = re.compile(r"^\s*(?://|/\*|\*|<!--)")
JS_IMPORT_TAIL_LINES = 2
# `import` / `import type` alone on its line, then one line of what it imports (`Resend`, `{ Resend }`, `* as R`), then
# the `from '…'` (fourth review of 30.09)
JS_BARE_IMPORT_RE = re.compile(r"^\s*import(?:\s+type)?\s*$")
JS_IMPORT_NAME_LINE_RE = re.compile(r"^\s*(?:(?!from\s*$)[A-Za-z_$][\w$]*|\*\s*as\s+[A-Za-z_$][\w$]*|\{[^{}'\"`;/]*\})\s*$")
STATEMENT_MAX_LINES = 60
STATEMENT_MAX_CHARS = 8000


def _without_block_comments(text: str) -> str:
    """The text with every closed `/* … */` replaced by a space — one pass, left to right: after an unclosed `/*` no
    later comment can close either. Only for reading a module specifier (`import(/* webpackChunkName */ 'x')`)."""
    s = str(text or "")
    if "/*" not in s:
        return s
    out: list[str] = []
    i = 0
    while True:
        start = s.find("/*", i)
        end = s.find("*/", start + 2) if start >= 0 else -1
        if start < 0 or end < 0:
            break
        out += [s[i:start], " "]
        i = end + 2
    out.append(s[i:])
    return "".join(out)


def _js_from_specs(text: str) -> list[str]:
    """The module of every `… from '<spec>'` of an import or export statement in the text (`JS_FROM_SPEC_RE`), read
    backwards from the `from` over its clause — up to the nearest `;`, quote, backtick or newline, at most JS_CLAUSE_MAX
    characters: the clause starts the statement with `import`/`export` (at the start of a line or after `;`, or after
    `{`, `}`, `>`, `*/` inside it), or it is the line that closes a multi-line one (`} from 'ws'`). Linear in the text:
    each character is in at most one clause."""
    s = str(text or "")
    if "from" not in s:
        return []
    import bisect

    out: list[str] = []
    # the clause boundaries of the whole text, found once (not five `rfind`s over a 4 000-character copy per `from`:
    # a 1 MB line of `from"x"` took 4.5 s, third review of 30.09)
    stops = [d.start() for d in _CLAUSE_STOP_RE.finditer(s)]
    for m in JS_FROM_SPEC_RE.finditer(s):
        lo = max(0, m.start() - JS_CLAUSE_MAX)
        k = bisect.bisect_left(stops, m.start()) - 1
        cut = stops[k] if k >= 0 and stops[k] >= lo else -1
        if cut < 0 and lo > 0:
            continue  # a clause longer than JS_CLAUSE_MAX is not an import clause
        bound = s[cut] if cut >= 0 else ""
        clause = s[cut + 1:m.start()]
        at_start = bound in ("", ";", "\n")
        line_start = bound in ("", "\n")
        if ((at_start and re.match(r"\s*(?:import|export)\b", clause)) or JS_CLAUSE_START_RE.search(clause)
                or (line_start and re.match(r"\s*\}", clause))):
            out.append(m.group(2))
    return out


def _cdn_spec(url: str) -> str:
    """The npm specifier a package CDN's URL names (`https://esm.sh/v135/resend@2.0.0/es2022/resend.mjs` →
    `resend@2.0.0/es2022/resend.mjs`), or "" for any other URL."""
    m = re.match(r"^https?://([^/?#]+)/([^?#]*)", str(url or ""))
    if not m or m.group(1) not in PACKAGE_CDN_HOSTS:
        return ""
    path = _CDN_PATH_PREFIX.sub("", m.group(2))
    return path[len("npm:"):] if path.startswith("npm:") else path


def _js_spec_name(spec: str) -> str:
    """The package a JS/TS module specifier (or an npm name) names, lower-cased and without a version (`npm:stripe@14`
    → `stripe`, `https://esm.sh/resend@2` → `resend`); "" for a file of the project (`./x`, `../x`, `/x`, `~/x`, `@/x`,
    `#x`), a URL of anything but a package CDN, or a Node built-in."""
    s = str(spec or "").strip().lower()
    if "://" in s:
        s = _cdn_spec(s)
    for scheme in ("npm:", "jsr:"):
        if s.startswith(scheme):
            s = s[len(scheme):]
    if not s or s.startswith(LOCAL_SPECIFIER_PREFIXES) or "://" in s or s.startswith("node:"):
        return ""
    return re.sub(r"^((?:@[^/@]+/)?[^/@]+)@[^/]*", r"\1", s)


def _import_roots(reading: str, name: str) -> list[str]:
    """The names of an import path that can be a package — the vendor's part, never a module of the project's own or a
    standard namespace. `jvm`: the name after a reversed domain (`com.stripe.Stripe` → `stripe`, and `io.socket` read
    back as `socket.io`), else the first (`expo.modules.core` → `expo`) — `javax.xml.ws`, `jakarta.xml.ws`,
    `org.springframework.ws`, `com.acme.api.ws` name no package `ws`; `cs`, `rust`, `php`, `ruby`: the first segment
    (`using Stripe.Checkout;`, `use stripe::Client`, `use Stripe\\StripeClient`, `require 'stripe/api'`), and none for
    Rust's `crate::`, `self::`, `super::`; `go`: the owner and the repository of a path with a host
    (`github.com/stripe/stripe-go/v76` → `stripe`, `stripe-go`; `gopkg.in/gomail.v2` → `gomail`), else the first
    segment (`net/http`)."""
    separator = IMPORT_PATH_READINGS.get(reading, "")
    parts = [p for p in str(name or "").strip().lower().split(separator)] if separator else []
    parts = [p for p in parts if p]
    if not parts:
        return []
    if reading == "jvm":
        if len(parts) > 1 and (parts[0] in REVERSED_DOMAIN_ROOTS or len(parts[0]) == 2):
            return [parts[1], f"{parts[1]}.{parts[0]}"]
        return [parts[0]]
    if reading == "rust" and parts[0] in RUST_LOCAL_ROOTS:
        return []
    if reading == "go":
        # a host has a dot (`github.com`); the dependency class hands over names spelled the PyPI way (`github-com`)
        host = "." in parts[0] or bool(re.search(r"-(?:com|org|net|io|in|dev|land|sh)$", parts[0]))
        if host and len(parts) > 1:
            return [re.sub(r"\.v\d+$", "", p) for p in parts[1:3]]
        return [parts[0]]
    return [parts[0]]


def reads_as_package(pkg: str, reading: str, name: str) -> bool:
    """`name`, read the way `reading` says, is the forbidden package `pkg` — as a whole name, never as its start.

    `npm`: the name, a subpath of it (`expo/config`) or a package of the scope named after it (`@expo/…` for `expo`);
    `py`: the top-level module (`stripe.error` → `stripe`), `-` and `_` alike; `pip` and `exact`: the name, `-`, `_`
    and `.` alike (PyPI's own rule); `jvm` / `cs` / `rust` / `php` / `ruby` / `go`: the vendor's part of an import path
    (`_import_roots`); `slash`: either name of a Composer `vendor/package`."""
    p, n = str(pkg or "").strip().lower(), str(name or "").strip().lower()
    if not p or not n:
        return False
    if reading == "npm":
        n = _js_spec_name(n)
        return bool(n) and (n == p or n.startswith(p + "/") or (not p.startswith("@") and n.startswith("@" + p + "/")))
    if reading == "py":
        top = n.split(".")[0]
        return bool(top) and _pep503(top) == _pep503(p)
    if reading in IMPORT_PATH_READINGS:
        return any(_pep503(root) == _pep503(p) for root in _import_roots(reading, n))
    if reading == "slash":
        return any(_pep503(part) == _pep503(p) for part in n.split("/") if part)
    return _pep503(n) == _pep503(p)


def _file_language(file: str) -> str:
    """`js`, `py`, `jvm`, `cs`, `rs`, `php`, `go`, `rb`, `none` (SQL) — or "" for any other file and for no file."""
    name = _base_name(file)
    ext = "." + name.rsplit(".", 1)[1] if "." in name.lstrip(".") else ""
    return IMPORT_LANGUAGES.get(ext, "")


def import_uses(line: str, file: str = "") -> list[tuple[str, str]]:
    """(reading, name) for each module or package an import statement on this line brings in, by the file's language
    (`_file_language`). The name an import binds is never read: `import exportCsv from './exportCsv'` brings in the
    file `./exportCsv`, which is the project's own."""
    text = str(line or "")
    if not text.strip():
        return []
    lang = _file_language(file)
    out: list[tuple[str, str]] = []
    if lang in ("js", ""):
        out += [("npm", spec) for spec in _js_from_specs(text)]
        if "(" in text:
            out += [("npm", m.group(2)) for m in JS_CALL_RE.finditer(_without_block_comments(text))]
        out += [("npm", m.group(2)) for m in JS_SIDE_EFFECT_RE.finditer(text)]
    if lang in ("py", ""):
        for m in PY_IMPORT_RE.finditer(text):
            out += [("py", part.split()[0]) for part in m.group(1).split(",") if part.strip()]
        out += [("py", m.group(1)) for m in PY_FROM_RE.finditer(text) if not m.group(1).startswith(".")]
        out += [("py", m.group(1)) for m in PY_DYNAMIC_RE.finditer(text)]
    if lang == "jvm":
        out += [("jvm", m.group(1)) for m in JVM_IMPORT_RE.finditer(text)]
    if lang in ("cs", ""):
        out += [("cs", m.group(1)) for m in CS_USING_RE.finditer(text)]
    if lang in ("rs", ""):
        out += [("rust", m.group(1) or m.group(2)) for m in RUST_USE_RE.finditer(text)
                if lang == "rs" or "::" in (m.group(1) or "")]
    if lang in ("php", ""):
        out += [("php", m.group(1)) for m in PHP_USE_RE.finditer(text) if lang == "php" or "\\" in m.group(1)]
    if lang == "go":
        out += [("go", m.group(1)) for m in GO_IMPORT_RE.finditer(text)]
        block = GO_BLOCK_LINE_RE.match(text)
        if block:
            out.append(("go", block.group(1)))
    if lang in ("rb", ""):
        out += [("ruby", m.group(1)) for m in RUBY_REQUIRE_RE.finditer(text) if not m.group(1).startswith((".", "/"))]
    return out


# keys of a TOML array that are not dependencies (`keywords = ["stripe"]` names a topic, not a package)
TOML_METADATA_KEYS = {"keywords", "classifiers", "authors", "maintainers", "include", "exclude", "files", "urls", "readme",
                      "license", "license-files", "members", "exclude-members", "categories", "features", "default"}


def manifest_line_uses(line: str, filename: str) -> list[tuple[str, str]]:
    """(reading, name) for the dependency one line of a manifest declares — the per-line form of `declared_names`, for
    a diff line or one line of a Write. A key with a string value in `package.json` / `composer.json` (a whole object on
    one line is read with `declared_names`), a requirement line, a TOML key (`stripe = "^5"`, `[dependencies.stripe]`)
    or the strings of a dependency array, a `go.mod` require, a `Gemfile` gem."""
    base = _base_name(filename)
    s = str(line or "").strip()
    if not s or not _is_manifest(filename):
        return []
    if base in ("package.json", "composer.json"):
        reading = _manifest_reading(base)
        if s.startswith("{") and s.rstrip(",").endswith("}"):
            try:
                json.loads(s.rstrip(","))
                return [(reading, n) for n in sorted(declared_names(s.rstrip(","), base))]
            except Exception:
                pass
        # a package name holds no quote and no backslash: the key is read up to the next quote (the escaped form scanned
        # to the end of the line from every `"`, and a line of `\"` never finished — third review of 30.09)
        return [(reading, m.group(1)) for m in re.finditer(r"\"([^\"\\\n]{1,214})\"\s*:\s*\"", s)]
    if base in ("pyproject.toml", "pipfile", "cargo.toml"):
        reading = _manifest_reading(base)
        if s.startswith("#"):
            return []
        table = re.match(r"^\[+\s*(?:[\w.\-]+\.)?(?:dependencies|dev-dependencies|build-dependencies|packages|dev-packages)"
                         r"\.[\"']?([\w.\-]+)[\"']?\s*\]+$", s)
        if table:
            return [(reading, table.group(1))]
        if s.startswith("["):
            return []
        pair = re.match(r"^([A-Za-z0-9_.\-\"']+)\s*=\s*(.*)$", s)
        if pair:
            key, value = pair.group(1).strip("\"'"), pair.group(2).strip()
            if value.startswith("[") and key.lower() not in TOML_METADATA_KEYS:
                return [(reading, _package_name(v)) for v in re.findall(r"[\"']([^\"']+)[\"']", value.split(" #", 1)[0])]
            return [] if value.startswith("[") or key.lower() == "python" else [(reading, key)]
        return [(reading, _package_name(v)) for v in re.findall(r"[\"']([^\"']+)[\"']", s.split(" #", 1)[0])]
    if base == "go.mod":  # the module path as written: `github.com/gobwas/ws v1.4.0` (one dot per step of the host:
        # `[\w.\-]+\.[\w.\-]+` could split a run of dots every way, 12 s on a line of them — third review of 30.09)
        return [("go", n) for n in re.findall(r"^\s*(?:require\s+)?([\w\-]*(?:\.[\w\-]*)+/\S+)\s+v\d", s)]
    return [(_manifest_reading(base), n) for n in declared_names(s, base)]


def _manifest_reading(filename: str) -> str:
    """How the names a manifest declares are read (`reads_as_package`): `package.json` as npm names, `composer.json` as
    Composer's vendor/package, `go.mod` as Go modules, `Cargo.toml` and `Gemfile` as one name, the rest the PyPI way."""
    return {"package.json": "npm", "composer.json": "slash", "go.mod": "go", "cargo.toml": "exact",
            "gemfile": "exact"}.get(_base_name(filename), "pip")


# The files that carry Python requirement lines without being a manifest the dependency class reads: a pip constraints
# file, tox's `deps`, setup.cfg's `install_requires`, a conda environment's list (its `pip:` entries included). A line
# there names a package the environment installs; hook 2026-09-29 refused `resend==2.0` in any of them as a word.
REQUIREMENT_LIKE_FILE = re.compile(r"^(?:[\w.\-]*constraints[\w.\-]*\.(?:txt|in)|tox\.ini|setup\.cfg|environment\.ya?ml|"
                                   r"conda[\w.\-]*\.ya?ml)$", re.I)
# No two `\s*` next to each other: `^\s*(?:… |\s+)` and a spec ending `\s*(?:[…]\s*)?…\s*` split a run of spaces
# every way before failing — a 100 KB line of spaces in a setup.cfg never finished (third review of 30.09). Each
# optional part now starts with its own `\s*` and a character it must see.
_REQUIREMENT_SPEC = (r"([A-Za-z0-9][\w.\-]*)(?:\s*\[[^\]]*\])?(?:\s*(?:===|==|>=|<=|~=|!=|<|>)\s*[\w.*+!\-]+"
                     r"(?:\s*,\s*(?:===|==|>=|<=|~=|!=|<|>)\s*[\w.*+!\-]+)*)?(?:\s*;.*)?\s*")
_INI_REQUIREMENT_RE = re.compile(r"^(?:\s*(?:deps|install_requires|tests_require|setup_requires|requires)\s*=\s*|\s+)"
                                 + _REQUIREMENT_SPEC + r"$")
_CONDA_REQUIREMENT_RE = re.compile(r"^\s*-\s+(?:[\w.\-]+::)?([A-Za-z0-9][\w.\-]*)(?:\s*\[[^\]]*\])?\s*(?:[=<>!~].*)?$")


def requirement_like_line_uses(line: str, filename: str) -> list[tuple[str, str]]:
    """(reading, name) for the requirement one line of a `REQUIREMENT_LIKE_FILE` names: a constraints line read like
    requirements.txt, an ini line that is only a requirement (`deps = resend`, `    resend==2.0` — never `ws =
    app.cli:main`), a conda list item (`- resend==2.0`, `- conda-forge::stripe`)."""
    base = _base_name(filename)
    s = str(line or "").rstrip()
    if not s.strip() or s.lstrip().startswith(("#", ";")) or not REQUIREMENT_LIKE_FILE.match(base):
        return []
    if base.endswith((".txt", ".in")):  # a constraints file: `dev-constraints.txt` too
        return [("pip", n) for n in declared_names(s, "requirements.txt")]
    if base.endswith(".ini") or base.endswith(".cfg"):
        m = _INI_REQUIREMENT_RE.match(s.split(" #", 1)[0].rstrip())
        return [("pip", m.group(1))] if m else []
    m = _CONDA_REQUIREMENT_RE.match(s.split(" #", 1)[0])
    return [("pip", m.group(1))] if m and m.group(1).lower() != "pip" else []


# The config files of a forbidden stack that name its packages without being a manifest the dependency class reads
# (the second review of 30.09): Expo's `app.json` / `app.config.json` (a top-level `"expo"` key is the Expo app's config),
# Flutter's `pubspec.yaml` (its `dependencies:` entries, `flutter:`, `sdk: flutter`), a .NET project's
# `<PackageReference Include="Stripe.net" …>` (and a central `Directory.Packages.props`), a Deno config or an import
# map whose values name npm packages (`"mail": "npm:resend@2"`, an esm.sh URL). Read for a forbidden package only.
# Left as designed — mentioned by a keyword if at all, never read as a package: lockfiles, Django's INSTALLED_APPS,
# `/// <reference types>`, SCSS imports, next.config's `transpilePackages`.
STACK_CONFIG_FILE = re.compile(r"^(?:app(?:\.config)?\.json|pubspec\.yaml|[\w.\-]+\.(?:cs|fs|vb)proj|directory\.packages\.props|"
                               r"deno\.jsonc?|import_map\.json|importmap\.json)$", re.I)
# Expo's app config is read as a whole document (the third review of 30.09): only a TOP-LEVEL `"expo"` key is the
# Expo app's config (`{"scripts": {"expo": …}}`, `{"targets": {"expo": {…}}}` are not), so the text is parsed as JSON,
# and a text that does not parse — one line of the file, a fragment an Edit writes — gets no stack-config reading.
STACK_DOCUMENT_NAMES = frozenset({"app.json", "app.config.json"})
# pubspec.yaml: a package is a two-space key under `dependencies:`, `dev_dependencies:` or `dependency_overrides:`, and
# `sdk: flutter` (never a key of `executables:`, `environment:` or `flutter:`). A line read before any top-level key of
# the text (one line of a diff, an Edit's fragment) counts when its value is a version, or when it is empty and the
# next line is its source (`git:`, `path:`, `hosted:`, `version:`, `sdk:`) — what a dependency's value is, and an
# executable's (`expo: main`, `expo:`) is not. The hook and check-diff read the file as a document too
# (`stack_document_change`, `diff_row_statements`), so a section header in sight decides.
PUBSPEC_DEPENDENCY_SECTIONS = frozenset({"dependencies", "dev_dependencies", "dependency_overrides"})
_PUBSPEC_TOP_RE = re.compile(r"^([A-Za-z_][\w\-]*)\s*:")
_PUBSPEC_KEY_RE = re.compile(r"^  ([a-z_][a-z0-9_]*)\s*:\s*(.*)$")
_PUBSPEC_VERSION_RE = re.compile(r"^(?:[\"']?\s*(?:[\^<>=~]|\d|any\b))")
_PUBSPEC_SDK_FLUTTER_RE = re.compile(r"^\s+sdk\s*:\s*[\"']?flutter[\"']?\s*$")
_PUBSPEC_SOURCE_RE = re.compile(r"^    \s*(?:git|path|hosted|version|sdk)\s*:")
DOCUMENT_NAMES = STACK_DOCUMENT_NAMES | {"pubspec.yaml"}
# bounded: an unbounded `[^>]*?` scanned to the end of the line from each of 60 000 `<PackageReference` (third review)
# Each scan stops at the next tag or at the value's own quote, so every character is read by one start (the third review
# of 30.09: `[^>]*?` from each of 60 000 `<PackageReference`, and a key read back over 200 000 `\"`, did not finish).
_PACKAGE_REFERENCE_RE = re.compile(r"<Package(?:Reference|Version)\b[^<>]{0,1000}?\bInclude\s*=\s*\"([^\"<>]{1,500})\"", re.I)
_IMPORT_MAP_VALUE_RE = re.compile(r"\"\s*:\s*\"((?:npm:|jsr:|https?://)[^\"\n]{1,2000})\"")


def _pubspec_uses(text: str) -> list[tuple[str, str]]:
    """The packages a pubspec.yaml text names (see PUBSPEC_DEPENDENCY_SECTIONS), read line by line with the section
    each line is in; "" is the section before any top-level key of the text."""
    out: list[tuple[str, str]] = []
    section = ""
    lines = str(text or "").split("\n")
    for i, raw in enumerate(lines):
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = _PUBSPEC_TOP_RE.match(line)
        if top:
            section = top.group(1).lower()
            continue
        if section and section not in PUBSPEC_DEPENDENCY_SECTIONS:
            continue
        if _PUBSPEC_SDK_FLUTTER_RE.match(line):
            out.append(("exact", "flutter"))
            continue
        key = _PUBSPEC_KEY_RE.match(line)
        if not key:
            continue
        value = key.group(2).strip()
        if section or _PUBSPEC_VERSION_RE.match(value):
            out.append(("exact", key.group(1)))
        elif not value:  # its source on the next non-empty line (looked for a few lines ahead, never the rest)
            after = next((x for x in lines[i + 1:i + 4] if x.strip()), "")
            if _PUBSPEC_SOURCE_RE.match(after):
                out.append(("exact", key.group(1)))
    return out


def stack_config_uses(line: str, filename: str) -> list[tuple[str, str]]:
    """(reading, name) for the package a text of a `STACK_CONFIG_FILE` names: an Expo `app.json` whole (a text that
    parses as JSON with a top-level `"expo"`), a pubspec.yaml by its sections (`_pubspec_uses`), the rest line by line.
    Pure."""
    base = _base_name(filename)
    s = str(line or "")
    if not s.strip() or not STACK_CONFIG_FILE.match(base):
        return []
    if base in STACK_DOCUMENT_NAMES:
        try:
            data = json.loads(s)
        except Exception:
            return []
        return [("npm", "expo")] if isinstance(data, dict) and "expo" in data else []
    if base == "pubspec.yaml":
        return _pubspec_uses(s)
    if base.endswith("proj") or base == "directory.packages.props":
        return [("cs", n) for n in _PACKAGE_REFERENCE_RE.findall(s)]
    return [("npm", v) for v in _IMPORT_MAP_VALUE_RE.findall(s)]


def stack_document_change(tool_name: str, tool_input: dict) -> tuple[str, str] | None:
    """(the document as the call leaves it, as it was) for a Write or an Edit of an Expo `app.json` /
    `app.config.json` or a `pubspec.yaml` (`DOCUMENT_NAMES`), None for any other call. A Write's content is the new document and ""
    the old (a Write names what it writes, as any other Write does); an Edit is applied to the file on disk (read up to
    PACKAGE_READ_MAX) — when the file cannot be read or an edit does not apply, the new text is only the fragments,
    which do not parse and so name nothing."""
    tool_input = tool_input or {}
    if is_command(tool_name, tool_input):
        return None
    text, path = text_of_tool_input(tool_name, tool_input)
    if _base_name(path) not in DOCUMENT_NAMES:
        return None
    content = next((tool_input[k] for k in ("content", "contents") if isinstance(tool_input.get(k), str)), None)
    if content is not None:
        return content, ""
    old, _why = _read_for_packages(Path(path) if os.path.isabs(path) else project_root() / path)
    if old is None:
        return text, ""
    new = old
    for o, n, every, _offset in _edits_of(tool_input):
        if not o or o not in new:
            return text, ""
        new = new.replace(o, n) if every else new.replace(o, n, 1)
    return new, old


def _create_package(word: str) -> str:
    """What `npm create <x>` / `npm init <x>` runs: `expo-app` → `create-expo-app`, `@scope/x` → `@scope/create-x`."""
    name = _package_name(word).lower()
    if name.startswith("@"):
        scope, _sep, rest = name.partition("/")
        return f"{scope}/create-{rest}" if rest else f"{scope}/create"
    return name if name.startswith("create-") else "create-" + name


def command_package_uses(command: str, programs: bool = True) -> list[tuple[str, str]]:
    """(reading, name) for every package a shell command installs or runs by name: the installs `dependency_additions`
    reads plus those for the whole machine (`_installs(machine=True)`), `npx|pnpx|bunx <pkg>`, `npm exec|pnpm dlx|
    yarn dlx|bun x <pkg>`, `npm|yarn|pnpm|bun create|init <x>` (`create-<x>`), `uvx <pkg>`, `python -m <module>`.
    `programs`: the text is a command the agent runs, so a command whose program is the package's own CLI (`expo start`,
    `stripe listen`, `flutter run`) counts too."""
    uses = [(MANAGER_READINGS.get(manager, "exact"), name) for manager, name in _installs(command, machine=True)]
    for tokens in _install_commands(command):
        exe = _manager_exe(tokens[0])
        words = [t for t in _after_global_options(exe, tokens[1:]) if not t.startswith("-")]
        if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe) and "-m" in tokens[1:]:
            i = tokens.index("-m")
            if i + 1 < len(tokens):
                uses.append(("py", tokens[i + 1]))
            continue
        if exe in JS_RUNNERS and len(words) > 1 and words[0].lower() in JS_RUN_SUBCOMMANDS | JS_CREATE_SUBCOMMANDS:
            uses.append(("npm", _package_name(words[1]) if words[0].lower() in JS_RUN_SUBCOMMANDS
                         else _create_package(words[1])))
            continue
        if exe == "uvx" and words:
            uses.append(("pip", _package_name(words[0])))
            continue
        if programs:
            first = tokens[0].strip()
            uses.append(("npm", _package_name(first) if first.startswith("@") else _package_name(exe)))
    return uses


def _starts_an_install(words: list[str]) -> bool:
    """The first words of a command inside a line — a manager and what follows it — install or run a package: one of
    the three words after the manager is an `INLINE_VERBS` word (`pip install`, `pnpm --filter web add`), the manager
    runs packages itself (`npx`, `uvx`), or Python is told `-m`. `go back to the dashboard` is not a command."""
    while words and (words[0].lower() == "sudo" or re.fullmatch(r"[@+\-]+", words[0])):
        words = words[1:]
    if words:  # a Makefile recipe's prefix glued to the word: `@pip`, `-pip`
        words = [words[0].lstrip("@+-")] + words[1:]
    if len(words) < 2:
        return False
    exe = _manager_exe(words[0])
    if exe in NPX_RUNNERS or exe == "uvx":
        return True
    after = [w.lower() for w in words[1:4]]
    if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe):
        return "-m" in after
    return any(w in INLINE_VERBS for w in after)


def _command_end(text: str, start: int, limit: int) -> int:
    """Where the shell command that starts at `start` ends, before `limit`: a separator outside quotes (`;`, `&&`,
    `||`, `|`, `&`, a newline). `2>&1` and `&>` are redirects, not separators. One pass over the command."""
    quote = ""
    i = start
    while i < limit:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in ";\n|":
            return i
        elif ch == "&" and text[i - 1:i] not in ("<", ">") and text[i + 1:i + 2] != ">":
            return i
        i += 1
    return i


def exec_form_uses(line: str) -> list[tuple[str, str]]:
    """The packages the exec form of a command installs or runs — a Dockerfile `RUN ["pip", "install", "resend"]`, a
    YAML `command: ["npx", "expo", "start"]` — read as the same command written out."""
    out: list[tuple[str, str]] = []
    for m in EXEC_FORM_RE.finditer(str(line or "")):
        items = [a or b for a, b in re.findall(r"\"((?:[^\"\\]|\\.)*)\"|'([^']*)'", m.group(0)) if a or b]
        command = " ".join(f"'{item}'" if re.search(r"\s", item) else item for item in items)
        words = command.split()[:6]
        if _starts_an_install(words):
            command = re.sub(r"^sudo\s+", "", command, flags=re.I)
            out += command_package_uses(command, programs=_exe_name(command.split()[0]) in NPX_RUNNERS)
    return out


def inline_command_uses(line: str) -> list[tuple[str, str]]:
    """The packages an install command written into a line of a file installs or runs (`RUN pip install stripe`,
    `run: npm i expo`, `"postinstall": "npx expo prebuild"`, the exec form `RUN ["pip", "install", "resend"]`). A
    command ends at a shell separator, at its closing quote when the line quotes it, or after `INLINE_WINDOW`
    characters; a manager whose next words install or run nothing is not a command (`_starts_an_install`), and a match
    inside a command already read is one of its words. So each character of the line is read at most once (review
    30.09: the rest of the line was re-read at every match, 30 s for a one-line JSON of 60 000 characters). A program
    is read as a package only behind `npx`/`pnpx`/`bunx`: `expo = 1` in code is not `expo` run."""
    text = str(line or "")
    out: list[tuple[str, str]] = []
    if not MANAGER_WORD_RE.search(text):
        return out
    read_to = 0
    for m in INLINE_COMMAND_RE.finditer(text):
        start = m.start()
        if start < read_to:
            continue
        words = text[start:start + 160].split()[:6]
        if not _starts_an_install(words):
            continue
        limit = min(len(text), start + INLINE_WINDOW)
        quote = text[start - 1] if start and text[start - 1] in "\"'`" else ""
        if quote:
            closing = text.find(quote, start, limit)
            limit = closing if closing >= 0 else limit
        read_to = _command_end(text, start, limit)
        command = re.sub(r"^[@+\-]*(?:sudo\s+)?", "", text[start:read_to].strip(), flags=re.I)
        first = _exe_name(command.split(None, 1)[0]) if command.split() else ""
        out += command_package_uses(command, programs=first in NPX_RUNNERS)
    if "[" in text:
        out += exec_form_uses(text)
    return out


def _statement_open(line: str, js: bool = False) -> str:
    """What keeps a statement open at the end of this line: `\\` (a trailing backslash), `)` (a `require(`, `import(`,
    `import_module(` left open), `]` (an exec-form array left open) or, when `js` (the text may be JS/TS), `from` (an
    import whose module comes on a later line); "" when the line ends its statement."""
    s = str(line or "").rstrip()
    if s.endswith("\\"):
        return "\\"
    if "(" in s and OPEN_CALL_RE.search(_without_block_comments(s)):
        return ")"
    if "[" in s and OPEN_EXEC_FORM_RE.search(s):
        return "]"
    if js and OPEN_JS_IMPORT_RE.match(s):
        return "from"
    return ""


def _js_import_end(lines: list[str], i: int) -> int:
    """The last line of the import or export that `lines[i]` opens without naming its module (`OPEN_JS_IMPORT_RE`), or
    -1 when the lines after it do not finish one. With an open brace the lines are joined up to the one holding the
    `}` (a comment line never is it), at most STATEMENT_MAX_LINES; the `from '…'` must then be on that line after the
    `}`, or on the next non-empty lines — at most JS_IMPORT_TAIL_LINES of them, holding nothing but `from` and the
    module. A comment line there ends the reading: `export {` … `}` / `// … from 'resend' webhooks` is no import."""
    n = len(lines)
    first = str(lines[i])
    j = i
    tail = ""
    if JS_BARE_IMPORT_RE.match(first):
        k = i + 1
        while k < n and not str(lines[k]).strip():
            k += 1
        if k < n and JS_IMPORT_NAME_LINE_RE.match(str(lines[k])):
            j = k  # the one line of names: the `from '…'` comes after it
    if first.count("{") > first.count("}"):
        while True:
            j += 1
            if j >= n or j - i > STATEMENT_MAX_LINES:
                return -1
            line = str(lines[j])
            if "}" in line and not JS_COMMENT_LINE_RE.match(line):
                tail = line[line.rfind("}") + 1:]
                break
    elif "}" in first:
        tail = first[first.rfind("}") + 1:]
    if JS_FROM_TAIL_RE.match(tail):
        return j
    if not JS_FROM_PREFIX_RE.match(tail):
        return -1
    for _ in range(JS_IMPORT_TAIL_LINES):
        j += 1
        while j < n and not str(lines[j]).strip():
            j += 1
        if j >= n or JS_COMMENT_LINE_RE.match(str(lines[j])):
            return -1
        tail = f"{tail} {str(lines[j]).strip()}"
        if JS_FROM_TAIL_RE.match(tail):
            return j
        if not JS_FROM_PREFIX_RE.match(tail):
            return -1
    return -1


def statement_spans(lines: list[str], file: str = "") -> list[tuple[int, int, str]]:
    """(first, last, text) for every statement these consecutive lines write over more than one line, joined into one
    line: a trailing backslash continues it (`RUN pip install \\`, Python's `import os, \\`, a hashed requirement), a
    `require(` or `import(` left open runs to its `)` (`const { Server } = require(` / `'ws'` / `)`), an exec-form array
    left open to its `]`, and — in a JS/TS file (`file`) or text of no known language — an import whose `from '…'` comes
    on a later line (`import { Resend }` / `  from 'resend';`, `_js_import_end`). At most STATEMENT_MAX_LINES lines and
    STATEMENT_MAX_CHARS characters. Only packages are read in the joined text (`package_uses`); every line keeps its own
    reading and its own verdict. Pure, one pass."""
    out: list[tuple[int, int, str]] = []
    js = _file_language(file) in ("js", "")
    i, n = 0, len(lines)
    while i < n:
        scan_checkpoint()
        closer = _statement_open(lines[i], js)
        if not closer:
            i += 1
            continue
        if closer == "from":
            j = _js_import_end(lines, i)
            if j < 0:
                i += 1
                continue
            out.append((i, j, " ".join(str(lines[x]).strip() for x in range(i, j + 1))[:STATEMENT_MAX_CHARS * 2]))
            i = j + 1
            continue
        text, j = str(lines[i]).rstrip(), i
        while closer and j + 1 < n and j - i < STATEMENT_MAX_LINES and len(text) < STATEMENT_MAX_CHARS:
            j += 1
            following = str(lines[j]).strip()
            if closer == "\\":
                text = text[:-1].rstrip()
            text = f"{text} {following}"
            if closer == "\\" or closer in following:
                closer = _statement_open(following, js)
        if j > i:
            out.append((i, j, text))
        i = j + 1
    return out


# the interpreters a heredoc can feed code to, and a file name of the language that code is read in
HEREDOC_INTERPRETERS = {"node": "<stdin>.js", "deno": "<stdin>.ts", "bun": "<stdin>.js", "tsx": "<stdin>.ts",
                        "ts-node": "<stdin>.ts", "ruby": "<stdin>.rb", "php": "<stdin>.php"}


def _heredoc_file(line: str) -> str:
    """What the body of the heredoc this line opens is read as: the file `cat`/`tee` writes it into, a file of the
    language an interpreter reads it in (`python - <<EOF` → `<stdin>.py`), or "" — a heredoc fed to anything else (a
    shell, `psql`) stays part of the command."""
    for segment in SEGMENT_SPLIT.split(str(line or "")):
        if "<<" not in segment:
            continue
        words = segment.strip().split()
        exe = _exe_name(words[0]) if words else ""
        if exe in _HEREDOC_WRITERS:
            return _write_target_of_line(line)
        if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe):
            return "<stdin>.py"
        return HEREDOC_INTERPRETERS.get(exe, "")
    return ""


def shell_embedded_files(command: str) -> tuple[str, list[tuple[str, str]]]:
    """(the command without the text it carries into a file or an interpreter, [(file, text)]), so that a package is
    read in what the text is: a heredoc `cat`/`tee` writes into a file is that file's content (`cat >> requirements.txt
    <<EOF` holds requirement lines), what `echo`/`printf` send into a file (`>`, `>>`, `| tee [-a]`) too (`echo
    'resend==2.0' >> requirements.txt`, review 30.09: it passed while the next `pip install -r` installed it), and a
    heredoc fed to an interpreter is code of its language (`python - <<EOF` … `ws = wb.active` is Python, not the
    program `ws`). A heredoc fed to a shell stays commands. Pure."""
    raw = str(command or "")
    files: list[tuple[str, str]] = []
    if "<<" in raw:
        lines, kept, i = raw.split("\n"), [], 0
        while i < len(lines):
            line = lines[i]
            kept.append(line)
            m = _HEREDOC.search(line)
            file = _heredoc_file(line) if m else ""
            if not file:
                i += 1
                continue
            j = i + 1
            while j < len(lines) and lines[j].strip() != m.group(2):
                j += 1
            files.append((file, "\n".join(lines[i + 1:j])))
            i = j + 1
        raw = "\n".join(kept)
    if "<<<" in raw:  # a here-string: `tee -a requirements.txt <<< 'resend'`, `python3 <<< 'import resend'`
        for segment, _sep in _split_shell(raw):
            m = _HERE_STRING.search(segment)
            if not m:
                continue
            data = next((g for g in m.groups() if g is not None), "").replace("\\n", "\n")
            tokens = _shell_tokens(segment[:m.start()] + " " + segment[m.end():])
            exe = _exe_name(tokens[0]) if tokens else ""
            targets = ([t for t in tokens[1:] if not t.startswith("-") and not REDIRECT_TOKEN.match(t)] if exe == "tee"
                       else _redirect_targets(tokens) if exe == "cat"
                       else ["<stdin>.py"] if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe)
                       else [HEREDOC_INTERPRETERS[exe]] if exe in HEREDOC_INTERPRETERS else [])
            files += [(t, data) for t in targets]
    if ">" in raw or "tee" in raw:
        piped: str | None = None
        for segment, sep in _split_shell(raw):
            tokens = _shell_tokens(segment)
            exe = _exe_name(tokens[0]) if tokens else ""
            if exe == "tee" and sep == "|" and piped is not None:
                files += [(t, piped) for t in tokens[1:] if not t.startswith("-")]
            piped = None
            if exe not in ("echo", "printf"):
                continue
            args: list[str] = []
            for token in tokens[1:]:
                if REDIRECT_TOKEN.match(token):
                    break
                args.append(token)
            while exe == "echo" and args and re.match(r"^-[neE]+$", args[0]):
                args = args[1:]
            data = " ".join(args).replace("\\n", "\n")
            targets = _redirect_targets(tokens)
            files += [(t, data) for t in targets]
            piped = None if targets else data
    return raw, files


def package_uses(text: str, file: str = "", shell: bool = False, statement: str = "",
                 statement_base: str = "") -> list[tuple[str, str]]:
    """(reading, name) for every package the text brings in, line by line: an import statement (`import_uses`), a
    manifest entry when `file` is a manifest (`manifest_line_uses`), a requirement line of a requirement-like file
    (`requirement_like_line_uses`), a package a forbidden stack's own config names (`stack_config_uses`), an install
    command written into the line (`inline_command_uses`) — and the same readings of every statement written over
    several lines (`statement_spans`), or of `statement`, the joined statement a line belongs to (`line_hits` gets it
    from its caller). `statement_base` is that statement's text as it was before the change, when the statement reaches
    lines the change did not write (a context line of a diff, the rest of a file an Edit lands in): a package it already
    names is not this line's (`statement_changes`). `shell`: the text is a command the agent runs
    (`command_package_uses`, programs included, a backslash-newline continuing the command), code it carries (`python
    -c "import stripe"`) is read with every import form, and the text it carries into a file or an interpreter as that
    file's (`shell_embedded_files`; a comment line there is written down, not read). At most PACKAGE_READ_MAX
    characters of the text are read (the caller reports the rest: `unread_parts`)."""
    raw = str(text or "")[:PACKAGE_READ_MAX]
    if not raw.strip() and not statement:
        return []
    if shell:
        command, embedded = shell_embedded_files(raw)
        command = re.sub(r"\\\r?\n", " ", command)
        uses = command_package_uses(command) + [use for line in command.split("\n") for use in import_uses(line)]
        for target, content in embedded:
            code = "\n".join(line for line in content.split("\n") if not is_comment_line(target, line))
            uses += package_uses(code, target)
        return uses
    manifest = bool(file) and _is_manifest(file)
    requirements = bool(file) and bool(REQUIREMENT_LIKE_FILE.match(_base_name(file)))
    stack_config = bool(file) and bool(STACK_CONFIG_FILE.match(_base_name(file)))
    lines = raw.split("\n")
    uses: list[tuple[str, str]] = []
    if stack_config and _base_name(file) in STACK_DOCUMENT_NAMES | {"pubspec.yaml"}:
        uses += stack_config_uses(raw, file)  # read as a document: a key's place in it decides (`stack_config_uses`)
        stack_config = False
    for line in lines:
        scan_checkpoint()
        if not line.strip():
            continue
        uses += import_uses(line, file)
        if manifest:
            uses += manifest_line_uses(line, file)
        if requirements:
            uses += requirement_like_line_uses(line, file)
        if stack_config:
            uses += stack_config_uses(line, file)
        uses += inline_command_uses(line)
    joined = [span for _first, _last, span in statement_spans(lines, file)] if len(lines) > 1 else []
    for whole in joined:
        uses += import_uses(whole, file) + inline_command_uses(whole)
    if statement:
        uses += statement_changes(statement, statement_base, file)
    return uses


def statement_changes(statement: str, base: str = "", file: str = "") -> list[tuple[str, str]]:
    """(reading, name) for the packages a joined statement brings in (an import, an install command) that `base` — the
    text around it as it was before the change — does not already bring in. With no base, all of them. So a line
    added to `RUN pip install \\` … `stripe \\` … brings in its own package, never `stripe` the statement already had."""
    uses = package_uses(statement, file)
    if not base or not uses:
        return uses
    before = {(reading, _pep503(name)) for reading, name in package_uses(base, file)}
    return [(reading, name) for reading, name in uses if (reading, _pep503(name)) not in before]


def _prose_names(trigger: str, low: str, prefix: bool = False) -> bool:
    """A package named in a sentence: the word between spaces, quotes, slashes, `@` or `=` — the reading every text got
    until hook 2026-09-29, kept for a request and for the data a command carries. A prefix is followed by a name."""
    word = str(trigger or "").strip().lower()
    if not word or word not in low:  # the substring test first: a regex scan per package of a 1 MB text is not free
        return False
    t = re.escape(word)
    tail = r"[a-z0-9]" if prefix else r"(?:[\s'\"@=:]|$)"
    return bool(t) and bool(re.search(r"(?:^|[\s'\"/@=(`])" + t + tail, low))


def package_hits(cfg: dict, text: str, file: str = "", shell: bool = False, prose: bool = False,
                 statement: str = "", statement_base: str = "") -> list[str]:
    """The forbidden packages (`deny_packages`) and package families (`deny_package_prefixes`) the text brings in, as
    the config lists them — the package part of `trigger_hits`. `file` gives the language and says whether a line is a
    manifest's; `shell` reads a command the agent runs; `prose` (a request, a commit message) also takes a package
    named in a sentence; `statement` is the joined statement a line belongs to (`statement_spans`), `statement_base`
    the same text before the change (`statement_changes`). A family is read in npm names only. Pure."""
    packages = [str(p).strip() for p in cfg.get("deny_packages") or [] if str(p or "").strip()]
    prefixes = [str(p).strip() for p in cfg.get("deny_package_prefixes") or [] if str(p or "").strip()]
    if not (packages or prefixes) or not (str(text or "").strip() or statement):
        return []
    uses = list(dict.fromkeys(package_uses(text, file, shell=shell, statement=statement,
                                           statement_base=statement_base)))  # a name read once
    low = str(text).lower() if prose else ""
    hits = [pkg for pkg in packages
            if any(reads_as_package(pkg, reading, name) for reading, name in uses) or (prose and _prose_names(pkg, low))]
    npm_names = [n for n in (_js_spec_name(name) for reading, name in uses if reading == "npm") if n]
    hits += [prefix for prefix in prefixes
             if any(n.startswith(prefix.lower()) for n in npm_names) or (prose and _prose_names(prefix, low, prefix=True))]
    return hits


def forbidden_package(cfg: dict, name: str, reading: str = "npm") -> str:
    """The `deny_packages` or `deny_package_prefixes` entry an installed or declared package name is, or "" — the
    reading `package_hits` gives the same name, so the dependency class skips exactly what was refused: the name read
    as `reading` says (`MANAGER_READINGS`, `_manifest_reading`) or the PyPI way, and a family only for an npm name
    (`pip install expo-helpers` is not in the Expo family: held as a new dependency, review 30.09)."""
    for pkg in cfg.get("deny_packages") or []:
        if str(pkg or "").strip() and (reads_as_package(str(pkg), "exact", name) or reads_as_package(str(pkg), reading, name)):
            return str(pkg)
    if reading != "npm":
        return ""
    spec = _js_spec_name(name)
    for prefix in cfg.get("deny_package_prefixes") or []:
        if str(prefix or "").strip() and spec.startswith(str(prefix).strip().lower()):
            return str(prefix)
    return ""


# The deny rules a pack writes into .claude/settings.json for the forbidden packages: Claude Code refuses these installs
# before the hook runs (defence in depth; the hook is the matcher). Until 2026-09-30 a rule read `Bash(npm install
# expo*)`, which also matched `npm install export-to-csv` and `pip install stripe-mock`. A rule is now the name alone,
# the name and more words (`expo *`: the space before `*` keeps the word whole), or the name with a version
# (`expo@*`, `stripe==*`, `stripe>*`, `stripe[*`); a family is its prefix (`expo-*`), for the JS managers only.
JS_INSTALL_RULES = ("npm install", "npm i", "pnpm add", "yarn add")
PY_INSTALL_RULES = ("pip install", "uv add")


def claude_deny_rules(cfg: dict) -> list[str]:
    """`Bash(…)` deny rules for the installs of `deny_packages` and `deny_package_prefixes`, in that order."""
    rules: list[str] = []
    for pkg in [str(p).strip() for p in (cfg or {}).get("deny_packages") or [] if str(p or "").strip()]:
        for manager in JS_INSTALL_RULES:
            rules += [f"Bash({manager} {pkg})", f"Bash({manager} {pkg} *)", f"Bash({manager} {pkg}@*)"]
        for manager in PY_INSTALL_RULES:
            rules += [f"Bash({manager} {pkg})", f"Bash({manager} {pkg} *)"] + [f"Bash({manager} {pkg}{c}*)" for c in "=<>~["]
    for prefix in [str(p).strip() for p in (cfg or {}).get("deny_package_prefixes") or [] if str(p or "").strip()]:
        rules += [f"Bash({manager} {prefix}*)" for manager in JS_INSTALL_RULES]
    return list(dict.fromkeys(rules))


def legacy_deny_rules(cfg: dict) -> set[str]:
    """The rules written before 2026-09-30 for the same packages (`Bash(npm install expo*)`): an installer that merges
    into an existing .claude/settings.json drops them, or the prefix match would keep refusing `export-to-csv`."""
    return {f"Bash({manager} {str(p).strip()}*)" for p in (cfg or {}).get("deny_packages") or [] if str(p or "").strip()
            for manager in JS_INSTALL_RULES + PY_INSTALL_RULES}


def trigger_hits(cfg: dict, text: str, path: str = "", *, file: str = "", shell: bool = False,
                 prose: bool = False, statement: str = "", statement_base: str = "") -> list[tuple[str, str]]:
    """(kind, trigger) for every **blocking** Non-Goal trigger the text contains — the single place where a
    forbidden package, path, keyword or phrase is recognised. Pure: no I/O, no state, the config is read-only.

    `path` is the file the text belongs to and is matched against the forbidden paths; `file` (default: `path`) only
    gives the language a package is read in — `line_hits` passes it for one line without matching the path again.
    `shell` says the text is a command the agent runs, `prose` that it is a sentence (a request, a commit message),
    `statement` the joined statement a line belongs to (`statement_spans`) and `statement_base` that statement before
    the change: all of them only change how a package is read (`package_hits`, 2026-09-30).

    `warn_keywords` are deliberately not here: they are a possible match for a human to judge, and a caller that
    reads this function is asking what stops a tool call. `warn_triggers` answers the other question.

    The hook renders these as refusal lines (`match_triggers`); LUMIS Studio reads the same hits line by line
    (`lumis/core/boundary_check.py`) so the pasted fragment is judged by exactly the matcher that will run in the
    repository — a studio answer the hook would not repeat is a lie about the guard."""
    low = (text or "").lower()
    hits: list[tuple[str, str]] = [("package", pkg) for pkg in
                                   package_hits(cfg, text, file or path, shell=shell, prose=prose, statement=statement,
                                                statement_base=statement_base)]
    slashed_path, slashed_text = str(path or "").replace("\\", "/").lower(), low.replace("\\", "/")
    for deny_path in cfg.get("deny_paths", []):
        if deny_path and (deny_path_pattern(deny_path).search(slashed_path) or deny_path_pattern(deny_path).search(slashed_text)):
            hits.append(("path", deny_path))
    words = _without_home_folders(text)
    low_words, spelled = words.lower(), _spelled_out(words)
    for kw in cfg.get("keywords", []):
        if kw and _keyword_found(kw, low_words, spelled):
            hits.append(("phrase" if " " in kw.strip() else "keyword", kw))
    return hits


_DENY_PATH_PATTERNS: dict[str, "re.Pattern[str]"] = {}


def deny_path_pattern(deny_path: str) -> "re.Pattern[str]":
    """A forbidden path as a whole path segment: `ios/` is src/ios/App.swift and `ios/` itself, never
    `scenarios/`, `studios/` or `portfolios/`. A plain substring test refused `pytest tests/scenarios/` and a commit
    message about "the scenarios/ page" as crossings of «No native iOS/Android apps» (audit 2026-09-23)."""
    low = str(deny_path or "").replace("\\", "/").lower()
    pattern = _DENY_PATH_PATTERNS.get(low)
    if pattern is None:
        head = r"(?<![A-Za-z0-9_.\-])" if low[:1].isalnum() or low[:1] == "_" else ""
        pattern = re.compile(head + re.escape(low))
        _DENY_PATH_PATTERNS[low] = pattern
    return pattern


# `C:\Users\<name>\…`, `/Users/<name>/…`, `/home/<name>/…`: the folder every absolute path on the machine starts with.
# A marker `users` (out of «…between several users at once») warned on each of them (audit 2026-09-23).
# Only at the start of an absolute path: `src/users/models.py` is the project's own `users` and still counts.
_HOME_FOLDER = re.compile(r"(?i)(?<![^\s'\"=(])(?:[a-z]:)?[\\/]+(?:users|home)[\\/]+[^\\/\s'\"]+")


def _without_home_folders(text: str) -> str:
    """The text with the home-folder prefix of every absolute path blanked, for the keyword match only."""
    return _HOME_FOLDER.sub(" ", str(text or ""))


def warn_triggers(cfg: dict, text: str) -> list[tuple[str, str]]:
    """(kind, trigger) for the warn-only markers — a single word out of a long Non-Goal sentence.

    They exist because the config generator used to make every such word blocking: on the founder's run of
    2026-09-21 the hook would have refused `python -m pytest`, a file whose docstring said "canonical
    curriculum", and the project's own `services/` package. A word out of a sentence is a hint for a human;
    it is reported, it never stops a tool call, and a config written before this key existed simply has none."""
    words = _without_home_folders(text)
    low, spelled = words.lower(), _spelled_out(words)
    return [("phrase" if " " in str(kw).strip() else "keyword", kw)
            for kw in cfg.get("warn_keywords", []) or [] if kw and _keyword_found(kw, low, spelled)]


def match_triggers(cfg: dict, text: str, path: str = "", kinds: tuple[str, ...] | None = None,
                   prose: bool = False) -> list[str]:
    """Non-Goal triggers in any text — a tool call's payload or the user's own prompt. One line per boundary.
    `kinds` keeps only those kinds of hit (the prompt hook drops single-word keywords); `prose` reads the text as a
    sentence (the prompt hook: a package named in a request counts, `package_hits`)."""
    raw = [(f"{TRIGGER_LABELS[kind]} '{trigger}'", trigger) for kind, trigger in trigger_hits(cfg, text, path, prose=prose)
           if kinds is None or kind in kinds]
    # one line per boundary: "forbidden dependency 'stripe', forbidden path 'billing/' → NG-1 "..." (set by the founder; ...)"
    grouped: dict[str, list[str]] = {}
    for what, trigger in raw:
        grouped.setdefault(explain(cfg, trigger), []).append(what)
    return sorted(", ".join(dict.fromkeys(whats)) + why for why, whats in grouped.items())


# --- where a hit stands: how much one line proves (2026-09-29) --------------------------------------------------------
# A trigger is text, and the same text proves more on one line than on another. Two independent findings of
# 2026-09-29 were false refusals on ordinary code: `from collections import defaultdict` under «No payment collection
# or billing», and a retro over 40 merged pull requests of a public repository where four of five BLOCK verdicts were
# a comment line (of the kind `// saveDraft is transactional, so a failed batch leaves nothing behind`), a
# `.gitignore` line (`yarn-debug.log*`) and a pnpm option (`--frozen-lockfile`). The rule since then:
#   - a hit blocks on a line of code; the same hit in a comment line of a code file or in an ignore file is written
#     down, not crossed (`noted`);
#   - a single-word keyword whose every match on the line is inside another tool's or library's name is a possible
#     match (`possible`). Two such names only: a command-line option, and only in a shell command, a CI file, a
#     lockfile or a manifest — never in the project's own source, never for a technology the boundaries name
#     (`--stripe-key` blocks); and the module of an import that is a standard or well-known library spelling another
#     form of the word (`from collections import …` for `collection`) — never the project's own module (`app.billings`);
#   - a name written as code (`@Transactional`), a phrase, a package and a path are never weakened this way.
# Each weaker verdict is printed with its reason (stderr, exit 1) and logged. The hook's content scan of a Write or an
# Edit, `check-diff` and the studio read each line with `line_hits`; the hook then keeps, per trigger, its strongest
# line — block, then warn, then noted — so a comment that names a trigger never hides a line of code carrying it, and
# a whole Write is "written down" only when no line of it is a possible match or a crossing.
_C_STYLE = ("//", "/*", "*")
_HASH = ("#",)
_COMMENT_GROUPS = (
    (_C_STYLE, (".java", ".kt", ".kts", ".scala", ".groovy", ".gradle", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
                ".mts", ".cts", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cs", ".go", ".rs", ".swift", ".dart",
                ".m", ".mm", ".proto", ".scss", ".less", ".jsonc", ".json5", ".zig", ".sol", ".fs", ".fsx")),
    (("/*", "*"), (".css",)),
    (_HASH, (".py", ".pyi", ".pyx", ".sh", ".bash", ".zsh", ".fish", ".rb", ".rake", ".pl", ".pm", ".r", ".yml", ".yaml",
             ".toml", ".cfg", ".conf", ".properties", ".env", ".ps1", ".psm1", ".nix", ".cmake", ".mk", ".ex", ".exs",
             ".jl", ".cr", ".tcl", ".awk", ".dockerfile", ".txt")),
    (_HASH + (";",), (".ini",)),
    (_HASH + _C_STYLE, (".php", ".tf", ".hcl")),
    (("--", "/*", "*"), (".sql",)),
    (("--",), (".lua", ".hs", ".elm")),
    ((";",), (".clj", ".cljs", ".cljc", ".edn", ".lisp", ".el", ".scm")),
    (("<!--",), (".html", ".htm", ".xhtml", ".xml", ".svg", ".md", ".mdx", ".xaml", ".csproj", ".plist")),
    (("<!--",) + _C_STYLE, (".vue", ".svelte", ".astro", ".jsp", ".cshtml", ".razor")),
    (("rem ", "::", "@rem "), (".bat", ".cmd")),
)
# How a comment line starts, per extension (after leading whitespace). `#` is not a comment in C, C++, C#, Rust or
# Swift (`#include`, `#region`, `#[derive]`), so those files know the C-style prefixes only. A file whose language is
# not known has no comment lines: every hit there is read as code, as before.
COMMENT_PREFIXES = {ext: prefixes for prefixes, exts in _COMMENT_GROUPS for ext in exts}
HASH_COMMENT_NAMES = frozenset({"dockerfile", "makefile", "gemfile", "rakefile", "procfile", "podfile", "brewfile",
                                "vagrantfile", "codeowners", ".gitattributes", ".editorconfig", ".env", ".npmrc",
                                ".bashrc", ".zshrc", ".profile"})
BLOCK_COMMENT_CLOSERS = {"/*": "*/", "<!--": "-->"}
# A comment that is an instruction to a tool is code, not prose: `// eslint-disable-next-line react-hooks/exhaustive-deps`
# is how a rule is switched off, and «never disable exhaustive-deps» is crossed on exactly that line.
DIRECTIVE_COMMENT_RE = re.compile(
    r"(?i)(?<![\w-])(?:eslint-(?:disable|enable)|@ts-(?:ignore|expect-error|nocheck)|noqa|type:\s*ignore|"
    r"pylint:\s*disable|pyright:\s*ignore|mypy:|nolint|prettier-ignore|(?:istanbul|c8)\s+ignore|biome-ignore|"
    r"rubocop:(?:disable|todo)|phpcs:(?:ignore|disable)|nosonar|go:(?:generate|build|embed|linkname)|\+build|"
    r"fmt:\s*(?:off|skip)|#pragma|swiftlint:disable|detekt:|@suppress)")
# The name of a module an import statement brings in, per language: Python, Java/Kotlin/C#/Rust/PHP, JS/TS, Go.
IMPORT_MODULE_RES = (
    re.compile(r"^\s*from\s+([\w.]+)\s+import\b"),
    re.compile(r"^\s*(?:import|using|use)\s+(?:static\s+)?([\w.:*\\]+(?:\s*,\s*[\w.:*\\]+)*)"),
    re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]"),
    re.compile(r"\b(?:require|import)\s*\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]"),
)
OPTION_TOKEN_RE = re.compile(r"^-{1,2}[a-z0-9]")
# Where a `--word` token is another tool's option rather than the project's own name (founder decision 2026-09-29):
# a CI file and a lockfile or manifest, besides a shell command. In the project's own source `ARGS = ['--billing']`
# is the project's own flag, and it is read as code.
CI_FILE_RE = re.compile(
    r"(?:^|/)(?:\.github/workflows/[^/]+|\.github/actions/.+/action|action|\.gitlab-ci|\.gitlab/ci/.+|"
    r"\.circleci/config|azure-pipelines|bitbucket-pipelines|\.travis|\.drone|\.woodpecker|\.woodpecker/.+|"
    r"\.buildkite/.+|appveyor|cloudbuild|codemagic)\.ya?ml$|(?:^|/)jenkinsfile$", re.I)
LOCKFILE_NAMES = frozenset({"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock",
                            "bun.lockb", "deno.lock", "poetry.lock", "pipfile.lock", "pdm.lock", "uv.lock", "cargo.lock",
                            "go.sum", "gemfile.lock", "composer.lock", "mix.lock", "pubspec.lock", "podfile.lock",
                            "packages.lock.json", "gradle.lockfile", "flake.lock"})
# Standard and well-known library modules whose name is another form of an ordinary word, as dotted paths: an import
# of one of these, or of a module under it, is someone else's module (`from collections import …`,
# `import java.util.Collections;`, `using System.Collections.Generic;`, `use std::collections::HashMap;`). Anything
# else an import names may be the project's own module, and the project's own module in either number is how code
# names the refused feature (`from app.billings import charge`, `import './billings'`, `from app.collections import …`).
LIBRARY_MODULES = frozenset({
    "collections", "numbers", "types", "requests", "secrets", "warnings",       # Python (standard library; requests)
    "java.util.collections", "java.util.arrays", "java.util.objects",           # Java
    "kotlin.collections", "system.collections", "system.threading.tasks",       # Kotlin, C#
    "std.collections",                                                          # Rust (`std::collections`)
    "events", "strings", "errors", "slices", "maps",                            # Node (`events`), Go
})


def _base_name(path: str) -> str:
    """The file's name, lower-cased — its last 255 characters: no file system has a longer one, and the name
    patterns (`MANIFEST_FILE`, …) took seconds on a 100 KB name (third review of 30.09)."""
    return str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()[-255:]


def is_option_context(path: str) -> bool:
    """A CI file, a lockfile or a manifest: text where a `--word` token is another tool's command-line option."""
    slashed = str(path or "").replace("\\", "/").lower()
    name = _base_name(path)
    return bool(slashed) and (bool(CI_FILE_RE.search(slashed)) or name in LOCKFILE_NAMES or _is_manifest(slashed))


def technology_triggers(cfg: dict) -> frozenset:
    """The triggers that name a technology — a lexicon name (`stripe`, `paddle`), a package the config forbids, a
    package of the capability lexicon. The option rule never weakens them (founder decision 2026-09-29): a Non-Goal
    that names Stripe is crossed by `--stripe-key` on a line of code, in a shell command and a CI file too."""
    names = set(TECHNOLOGY_WORDS) | {str(p).lower().strip() for p in cfg.get("deny_packages") or [] if p}
    for spec in CAPABILITY_TRIGGERS.values():
        names |= {str(p).lower() for p in spec.get("packages") or []}
    return frozenset(names)


def is_ignore_file(path: str) -> bool:
    """`.gitignore` and its kin (`.dockerignore`, `.npmignore`, `.eslintignore`, `.prettierignore`, …): a line there
    names what a tool skips; it builds nothing."""
    name = _base_name(path)
    return name.startswith(".") and name.endswith("ignore") and len(name) >= len(".ignore")


def comment_prefixes(path: str) -> tuple:
    """How a comment line starts in this file, by its name or extension; () for a language this does not know."""
    name = _base_name(path)
    if name in HASH_COMMENT_NAMES or name.startswith("dockerfile."):
        return _HASH
    ext = "." + name.rsplit(".", 1)[1] if "." in name.lstrip(".") else ""
    return COMMENT_PREFIXES.get(ext, ())


def is_comment_line(path: str, line: str) -> bool:
    """True when the whole line is a comment in this file's language. A trailing comment after code
    (`x = 1  # stripe`) is not one, and neither is a block comment closed on the line with code after it
    (`/* eslint-disable */ import stripe from 'stripe'`) or a comment that instructs a tool (`// eslint-disable-…`,
    `# noqa`, `// @ts-ignore`, `//go:generate`): those lines are code."""
    s = str(line or "").strip()
    if not s or DIRECTIVE_COMMENT_RE.search(s):
        return False
    for prefix in comment_prefixes(path):
        if prefix == "*":  # a line inside a /* … */ block; `*ptr = x` is code
            if s == "*" or s.startswith(("* ", "*/")):
                return True
            continue
        if not s.lower().startswith(prefix):
            continue
        closer = BLOCK_COMMENT_CLOSERS.get(prefix)
        if closer and closer in s[len(prefix):] and s[s.rfind(closer) + len(closer):].strip():
            return False
        return True
    return False


def _foreign_name(low: str, keyword: str, options: bool = False) -> str:
    """Why every match of a single-word keyword in this (lower-cased) line is inside a name that belongs to another
    tool or library, or "" when one of them may be the project's own code.

    Two such names. A command-line option (`--frozen-lockfile`, `--lockfile-only` for the marker `lockfiles`), only
    when `options` says the line is a shell command, a CI file, a lockfile or a manifest (`is_option_context`): in the
    project's own source `ARGS = ['--billing']` is the project's own flag. And the module of an import statement
    when the module is a standard or well-known library (`LIBRARY_MODULES`) and spells another form of the word
    (`from collections import …` for the marker `collection`). The project's own identifiers in either number —
    `class Leaderboard`, `streak_count`, `/api/leaderboards`, `from app.billings import charge`, `import './billings'`
    — are not foreign: that is how code names the refused feature."""
    matches = list(keyword_pattern(keyword).finditer(low))
    if not matches:
        return ""  # found only with camel case opened up: an identifier of the project's own
    modules = [m.span(1) for rx in IMPORT_MODULE_RES for m in rx.finditer(low)]
    word = str(keyword).lower().strip()
    reasons: list[str] = []
    for m in matches:
        if options:
            start = max(low.rfind(" ", 0, m.start()), low.rfind("\t", 0, m.start())) + 1
            ends = [i for i in (low.find(" ", m.end()), low.find("\t", m.end())) if i >= 0]
            token = low[start:min(ends) if ends else len(low)].lstrip("\"'`([{").rstrip("\"'`.,:;)]}")
            if OPTION_TOKEN_RE.match(token):
                reasons.append(f"the option '{token}'")
                continue
        span = next(((a, b) for a, b in modules if a <= m.start() < b), None)
        if span is not None and m.group(0) != word and _library_module(low[span[0]:span[1]], m.start() - span[0]):
            reasons.append(f"the imported module '{low[span[0]:span[1]].strip()}'")
            continue
        return ""
    return reasons[0]


def _library_module(modules: str, at: int) -> bool:
    """The imported module that holds position `at` of an import's module list is a library's (`LIBRARY_MODULES`,
    or a module under one), not the project's: `collections.abc` yes, `app.collections` and `./collections` no."""
    for part in re.finditer(r"[^,\s]+", modules):
        if part.start() <= at < part.end():
            path = re.sub(r"::|[\\/]", ".", part.group(0).strip("'\"`;"))
            path = path[len("node:"):] if path.startswith("node:") else path
            return any(path == lib or path.startswith(lib + ".") for lib in LIBRARY_MODULES)
    return False


def line_hits(cfg: dict, line: str, file: str = "", shell: bool = False,
              technologies: frozenset | None = None, statement: str = "",
              statement_base: str = "") -> list[tuple[str, str, str, str]]:
    """(kind, trigger, severity, why) for the Non-Goal triggers of one line of `file` (the file gives the language;
    it is not itself matched — a forbidden path of the file is the caller's). `shell` says the line is a shell
    command. `technologies` is `technology_triggers(cfg)`, passed in by a caller that reads many lines. `statement` is
    the statement this line starts when it runs over the next lines (`statement_spans`, joined): its packages count as
    this line's (`RUN pip install \\` … `resend`), less those of `statement_base`, the statement before the change
    (`statement_changes`). `severity`:

    - `block`: a blocking trigger on a line of code (or of a file whose language is not known, and in a command);
    - `noted`: a blocking trigger in a comment line of a code file, or anywhere in an ignore file — written down,
      not crossed; `why` says which;
    - `warn`: a warn-only marker; or a single-word keyword whose every match is inside another tool's command-line
      option (in a shell command, a CI file, a lockfile or a manifest, and not a technology) or an import of a
      library that spells another form of the word (`why` names it).

    Pure. Package names in an install command, a manifest or an import, forbidden paths, names written as code and
    phrases are never weakened by `_foreign_name`; only a comment or an ignore file makes them `noted`. A package is
    read in the language of `file` (a manifest's line as a declaration), a shell line as a command (`package_hits`,
    2026-09-30)."""
    out: list[tuple[str, str, str, str]] = []
    comment = bool(file) and is_comment_line(file, line)
    ignore = bool(file) and is_ignore_file(file)
    low = ""
    context: bool | None = None
    for kind, trigger in trigger_hits(cfg, line, file=file, shell=shell, statement=statement,
                                      statement_base=statement_base):
        if ignore:
            out.append((kind, trigger, "noted", "an ignore file"))
            continue
        if comment:
            out.append((kind, trigger, "noted", "a comment"))
            continue
        if kind == "keyword" and not str(trigger).lstrip().startswith("@"):
            low = low or _without_home_folders(line).lower()
            if context is None:
                context = shell or is_option_context(file)
            options = context and str(trigger).lower().strip() not in (
                technologies if technologies is not None else technology_triggers(cfg))
            foreign = _foreign_name(low, trigger, options=options)
            if foreign:
                out.append((kind, trigger, "warn", foreign))
                continue
        out.append((kind, trigger, "block", ""))
    out += [(kind, trigger, "warn", "") for kind, trigger in warn_triggers(cfg, line)]
    return out


# The order a trigger's verdict is decided in, over all the lines of one tool call: a line of code outranks a comment
# line, so `noted` is the verdict only of a trigger no line of code carries (2026-09-29).
SEVERITY_ORDER = ("block", "warn", "noted")


EDIT_OLD_KEYS = ("old_string", "old_str", "oldText", "old_text")
# A line an Edit adds inside a statement it cannot see the start of, when the file around it cannot be read: only
# the package name on it, and the backslash that continues the statement (`    resend \`), or the line right after
# one. Read as that one name, the PyPI way (an npm scope the npm way) — never as a family.
# (`(?:\s*(\\))?\s*$`, not `\s*(\\?)\s*$`: two `\s*` side by side split a run of spaces every way, and a line of
# 100 KB of spaces never finished — third review of 30.09; group 2 is then "\\" or None)
BARE_CONTINUATION_RE = re.compile(r"^\s+([A-Za-z0-9@][\w.\-/@]*(?:\[[^\]]*\])?(?:\s*[=<>!~]=?\s*[\w.*+!\-]+)?)(?:\s*(\\))?\s*$")


def _candidate_statement(token: str) -> str:
    """The install a bare package token stands for when the statement it continues is out of sight (`statement_changes`
    reads it): its name, compared whole."""
    name = _package_name(token)
    return f"npm install {name}" if name.startswith("@") else f"pip install {name}"


def _edits_of(tool_input: dict) -> list[tuple[str, str, bool, int]]:
    """(old, new, replace_all, line) for the edits a tool call makes, in the order they apply — the call's own
    `old_string`/`new_string` first, then its `edits` list — with the line of `text_of_tool_input`'s text where the
    new text starts (-1 when it adds no text: a deletion)."""
    out: list[tuple[str, str, bool, int]] = []
    line = 0
    for key in BODY_KEYS:  # the top-level parts, in the order `text_of_tool_input` joins them
        part = str(tool_input.get(key, "") or "")
        if not part:
            continue
        old = next((tool_input[k] for k in EDIT_OLD_KEYS if isinstance(tool_input.get(k), str)), None)
        if key in EDIT_BODY_KEYS and old is not None and not out:
            out.append((old, part, bool(tool_input.get("replace_all")), line))
        line += part.count("\n") + 1
    if not out:
        old = next((tool_input[k] for k in EDIT_OLD_KEYS if isinstance(tool_input.get(k), str)), None)
        if old is not None and any(isinstance(tool_input.get(k), str) for k in EDIT_BODY_KEYS):
            out.append((old, "", bool(tool_input.get("replace_all")), -1))
    for e in [x for x in (tool_input.get("edits") or []) if isinstance(x, dict)]:
        old = next((e[k] for k in EDIT_OLD_KEYS if isinstance(e.get(k), str)), None)
        parts = [str(e.get(k, "") or "") for k in EDIT_BODY_KEYS if str(e.get(k, "") or "")]
        if old is not None and any(isinstance(e.get(k), str) for k in EDIT_BODY_KEYS):
            out.append((old, parts[0] if parts else "", bool(e.get("replace_all")), line if parts else -1))
        line += sum(p.count("\n") + 1 for p in parts)
    return out


def _window(text: str, at: int, end: int, middle: str) -> tuple[list[str], int, int]:
    """(lines, first, last): `text` with `text[at:end]` replaced by `middle`, as the lines around it — up to
    STATEMENT_MAX_LINES whole lines before and after, and never more than STATEMENT_MAX_CHARS * 2 characters on either
    side, the partial lines joined to it — and where `middle`'s lines are among them. Bounded: the file is never split
    whole (the third review of 30.09: 5 000 edits of a 5.5 MB file split it twice each, 75 s)."""
    reach = STATEMENT_MAX_CHARS * 2
    lo, hi = max(0, at - reach), min(len(text), end + reach)
    ahead = text[lo:at].rsplit("\n", STATEMENT_MAX_LINES + 1)
    behind = text[end:hi].split("\n", STATEMENT_MAX_LINES + 1)
    if len(ahead) > STATEMENT_MAX_LINES + 1 or (lo > 0 and len(ahead) > 1):
        ahead = ahead[1:]  # the first piece is not a whole line
    if len(behind) > STATEMENT_MAX_LINES + 1 or (hi < len(text) and len(behind) > 1):
        behind = behind[:-1]
    body = middle.split("\n")
    body[0] = ahead[-1] + body[0]
    body[-1] = body[-1] + behind[0]
    context_before = ahead[:-1]
    lines = context_before + body + behind[1:]
    return lines, len(context_before), len(context_before) + len(body) - 1


def _read_for_packages(path: Path) -> tuple[str | None, str]:
    """(the file's text, "") — or (None, why it was not read): not a file, unreadable, or larger than
    PACKAGE_READ_MAX bytes (then it is not read at all: the edit is read as its own text)."""
    try:
        if not path.is_file():
            return None, ""
        if path.stat().st_size > PACKAGE_READ_MAX:
            return None, f"context not read: {path.name} is larger than {PACKAGE_READ_MAX // 1_000_000} MB"
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except Exception:
        return None, ""


def edit_statements(tool_name: str, tool_input: dict, unread: list[str] | None = None) -> dict[int, tuple[str, str]]:
    """{line of the call's text: (statement, the statement before the change)} for every statement an Edit's new text
    joins with lines of the file it does not itself write (review 30.09: a package added as a continuation line —
    `    resend \\` under an existing `RUN pip install \\`, `            ws \\` in a multi-line `pnpm add` of a CI file,
    `'ws'` into an open `require(` — was read on its own and passed). The file is read as it is on disk, each edit
    applied in turn (as `manifest_additions` applies them); the statement goes to the first line of the new text it
    covers, and its packages count less those the same stretch of the file named before the edit. A `replace_all` edit
    is read at each place it lands, the first REPLACE_ALL_CONTEXT_MAX of them.

    When the context is not available the edit is read as its own text: a bare package token on a line that continues a
    statement the new text does not start (`BARE_CONTINUATION_RE`) is read as that one package
    (`_candidate_statement`) — a forbidden one is refused; the dependency class holds anything else only in a manifest
    (`manifest_additions`). That is so when the file cannot be read, when an edit's old text is not in it — and, bounded
    since the third review of 30.09, when the file is larger than PACKAGE_READ_MAX bytes (not read at all), for the
    edits past the first EDIT_CONTEXT_MAX, and for a `replace_all` that lands in more than REPLACE_ALL_CONTEXT_MAX
    places. Each of those reasons is appended to `unread`: the caller reports it (a possible match, WARN). An Expo
    `app.json` is read whole by `stack_document_change`, not here."""
    tool_input = tool_input or {}
    edits = _edits_of(tool_input)
    if not edits or is_command(tool_name, tool_input):
        return {}
    notes = unread if unread is not None else []
    _text, path = text_of_tool_input(tool_name, tool_input)
    current: str | None = None
    if path:
        current, why = _read_for_packages(Path(path) if os.path.isabs(path) else project_root() / path)
        if why:
            notes.append(why)
    out: dict[int, tuple[str, str]] = {}

    def put(unit: int, statement: str, base: str) -> None:
        had = out.get(unit)
        out[unit] = (had[0] + "\n" + statement, had[1] + "\n" + base) if had else (statement, base)

    def text_only(new_lines: list[str], offset: int) -> None:
        seen_open = {x for a, b, _j in statement_spans(new_lines, path) for x in range(a, b + 1)
                     if not BARE_CONTINUATION_RE.match(new_lines[a])}
        for i, line in enumerate(new_lines):
            m = BARE_CONTINUATION_RE.match(line)
            continues = bool(m) and (m.group(2) == "\\" or (i > 0 and new_lines[i - 1].rstrip().endswith("\\")))
            if continues and i not in seen_open:
                put(offset + i, _candidate_statement(m.group(1)), "")

    for number, (old, new, every, offset) in enumerate(edits):
        scan_checkpoint()
        new_lines = new.split("\n")
        if number == EDIT_CONTEXT_MAX and current is not None:
            notes.append(f"context not read for the edits past the first {EDIT_CONTEXT_MAX} of this call")
            current = None
        if current is not None and old and old in current:
            if offset >= 0:
                start, places = 0, 0
                while places < (REPLACE_ALL_CONTEXT_MAX if every else 1):
                    at = current.find(old, start)
                    if at < 0:
                        break
                    places, start = places + 1, at + len(old)
                    lines, first, last = _window(current, at, at + len(old), new)
                    old_lines, _f, old_last = _window(current, at, at + len(old), old)
                    delta = last - old_last
                    if lines[first] != new_lines[0] or lines[last] != new_lines[-1]:
                        # the edit starts or ends inside a line: the whole line is what the file will say
                        put(offset, "\n".join(lines[first:last + 1]), "\n".join(old_lines[first:old_last + 1]))
                    for a, b, joined in statement_spans(lines, path):
                        if b < first or a > last or (a >= first and b <= last):
                            continue  # outside the new text, or wholly inside it (read with the text itself)
                        b_old = b - delta if b > last else old_last
                        put(max(a, first) - first + offset, joined, "\n".join(old_lines[min(a, first):b_old + 1]))
                if every and places == REPLACE_ALL_CONTEXT_MAX and current.find(old, start) >= 0:
                    notes.append(f"context not read past the first {REPLACE_ALL_CONTEXT_MAX} places a replace_all "
                                 "edit lands in")
                    text_only(new_lines, offset)
            current = current.replace(old, new) if every else current.replace(old, new, 1)
            if len(current) > PACKAGE_READ_MAX:
                notes.append(f"context not read: the file grows past {PACKAGE_READ_MAX // 1_000_000} MB")
                current = None
            continue
        if not old:  # an edit that creates the file: its text is the whole file, read with the text itself
            current = new if not current else None
            continue
        current = None  # this edit's context is gone, and so is every later one's
        if offset >= 0:
            text_only(new_lines, offset)
    return out


def judge_tool_input(cfg: dict, tool_name: str, tool_input: dict) -> dict[str, list[tuple[str, str, str]]]:
    """Every Non-Goal hit of a tool call, judged: `{"block" | "warn" | "noted": [(kind, trigger, why)]}`.

    A shell command is one unit, as it always was (a package in `pip install stripe` blocks exactly as before); the
    data it carries into a document — a commit message, a heredoc body — is left out (`check_data_mentions`). The
    content of a Write or an Edit is read line by line with `line_hits`, the reading `check-diff` gives an added
    line; the file's own path is matched once and a forbidden path blocks.

    Per trigger, as `check-diff` reports the same lines: `block` when any line blocks on it; otherwise `warn` when any
    line is a possible match; `noted` lists every trigger a comment line or an ignore file writes down and no line
    blocks on — it may also be in `warn`, and both are shown. A Write is only "written down" when `block` and `warn`
    are both empty (`main`): a comment never hides a line of code that carries the same trigger (review 2026-09-29).

    `unread` lists what was not read for packages, each with its reason (the content past PACKAGE_READ_MAX, the file
    around an Edit when it is larger than that, the edits past EDIT_CONTEXT_MAX…): the caller reports it as a possible
    match (WARN, exit 1), never as a pass in silence. The reading looks at the clock (`scan_checkpoint`) line by line."""
    text, path = text_of_tool_input(tool_name, tool_input)
    judged: dict[str, list] = {s: [] for s in SEVERITY_ORDER}
    unread: list[str] = []
    shell = is_command(tool_name, tool_input)
    if shell:
        units, file = [_command_without_data(text)], ""
    else:
        units, file = str(text or "").split("\n"), path
        judged["block"] += [(kind, trigger, "") for kind, trigger in trigger_hits(cfg, "", path)]
    scan_progress(0, len(units))
    if len(str(text or "")) > PACKAGE_READ_MAX:
        unread.append(f"the content past {PACKAGE_READ_MAX // 1_000_000} MB ({len(str(text)):,} characters) was not "
                      "read for packages: not read past 1 MB")
    whole = "\n".join(units)
    # a statement over several lines (`RUN pip install \`, `require(` … `)`) is read at its first line; one an Edit's
    # new text joins with lines of the file around it (`edit_statements`) at the first new line it covers, with the
    # statement as it was before the edit to subtract
    from_edits: dict[int, tuple[str, str]] = {}
    if not shell:
        from_edits = {k: v for k, v in edit_statements(tool_name, tool_input, unread).items() if 0 <= k < len(units)}
        document = stack_document_change(tool_name, tool_input)
        if document is not None:  # app.json / pubspec.yaml are read whole, less what they named before
            judged["block"] += [("package", t, "") for t in package_hits(cfg, "", file, statement=document[0],
                                                                        statement_base=document[1])]
    # only the triggers the whole text holds are read line by line: a long file costs one pass per trigger found
    found = {t for _k, t in trigger_hits(cfg, whole, file=file, shell=shell)} | {t for _k, t in warn_triggers(cfg, whole)}
    for k, (joined, base) in from_edits.items():
        found |= set(package_hits(cfg, units[k], file, statement=joined, statement_base=base))
    if found:
        statements: dict[int, tuple[str, str]] = {}
        if not shell:
            statements = {first: (joined, "") for first, _last, joined in statement_spans(units, file)}
            for k, (joined, base) in from_edits.items():
                had = statements.get(k)
                statements[k] = (joined + ("\n" + had[0] if had else ""), base)
        narrow = dict(cfg)
        for key in ("deny_packages", "deny_package_prefixes", "deny_paths", "keywords", "warn_keywords"):
            narrow[key] = [t for t in cfg.get(key) or [] if t in found]
        technologies = technology_triggers(cfg)  # from the whole config: the narrowed one lost unmatched packages
        for k, unit in enumerate(units):
            scan_progress(k, len(units))
            scan_checkpoint()
            joined, base = statements.get(k, ("", ""))
            for kind, trigger, severity, why in line_hits(narrow, unit, file, shell=shell, technologies=technologies,
                                                          statement=joined, statement_base=base):
                judged[severity].append((kind, trigger, why))
    scan_progress(len(units), len(units))
    blocked = {str(trigger).lower() for _k, trigger, _w in judged["block"]}
    for severity in SEVERITY_ORDER:
        kept, seen = [], set()
        for kind, trigger, why in judged[severity]:
            low = str(trigger).lower()
            if low in seen or (severity != "block" and low in blocked):
                continue
            seen.add(low)
            kept.append((kind, trigger, why))
        judged[severity] = kept
    judged["unread"] = list(dict.fromkeys(unread))
    return judged


def unread_lines(judged: dict) -> list[str]:
    """The warning lines for what a call's reading left unread for packages (`judge_tool_input`'s `unread`)."""
    return [f"possible match: part of this change was not read ({why})" for why in judged.get("unread") or []]


def _hit_order(cfg: dict):
    """The order `trigger_hits` reports in: packages, paths, then keywords, each as the config lists them."""
    rank = {"package": 0, "path": 1, "keyword": 2, "phrase": 2}
    keys = {"package": "deny_packages", "path": "deny_paths", "keyword": "keywords", "phrase": "keywords"}

    def key(hit: tuple) -> tuple:
        listed = [str(t) for t in cfg.get(keys.get(hit[0], "keywords")) or []]
        return (rank.get(hit[0], 3), listed.index(hit[1]) if hit[1] in listed else len(listed))
    return key


def render_hits(cfg: dict, hits: list[tuple[str, str, str]]) -> list[str]:
    """One line per boundary, as `match_triggers` writes them: "forbidden dependency 'stripe', Non-Goal keyword
    'stripe' → NG-1 "…" (set by the founder; …)"."""
    grouped: dict[str, list[str]] = {}
    for kind, trigger, _why in sorted(hits, key=_hit_order(cfg)):
        grouped.setdefault(explain(cfg, trigger), []).append(f"{TRIGGER_LABELS[kind]} '{trigger}'")
    return sorted(", ".join(dict.fromkeys(whats)) + why for why, whats in grouped.items())


def check_pre_tool(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """Non-Goal hits of a tool call that refuse it: a blocking trigger in a shell command, on a line of code of the
    content, or the file's own forbidden path. For a shell command the data it carries into a document — a commit
    message, a heredoc body appended to a Markdown file — is left out: `git commit -m "docs: explain why billing is
    out of scope"` was refused as a crossing of the billing boundary (audit 2026-09-23). `check_data_mentions`
    reports what the data names, as `noted`; `check_written_down` what only a comment or an ignore file names."""
    return render_hits(cfg, judge_tool_input(cfg, tool_name, tool_input)["block"])


def check_written_down(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """Blocking triggers that the content names only in comment lines or in an ignore file (2026-09-29): the
    boundary written down, not crossed — the same reading as a Write of a prose file, logged as `noted`. A trigger
    that a line of code also carries is not one of them (it blocks, or it is a possible match)."""
    judged = judge_tool_input(cfg, tool_name, tool_input)
    on_code = {str(t).lower() for _k, t, _w in judged["warn"]}
    return render_hits(cfg, [hit for hit in judged["noted"] if str(hit[1]).lower() not in on_code])


def check_data_mentions(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """Non-Goal hits that only the data of a shell command carries (see `check_pre_tool`): documentation of a
    boundary, the same reasoning as a Write of a prose file. A trigger the command itself carries is not one of them,
    even when it does not refuse the call (`--frozen-lockfile` is a possible match, not a commit message)."""
    if not is_command(tool_name, tool_input):
        return []
    command = str((tool_input or {}).get("command", ""))
    # the data is prose: a commit message names a package in a sentence (`package_hits`, 2026-09-30); what the command
    # itself names in the same words is not data
    outside = {trigger for _kind, trigger in trigger_hits(cfg, _command_without_data(command), prose=True)}
    return render_hits(cfg, [(kind, trigger, "") for kind, trigger in trigger_hits(cfg, command, prose=True)
                             if trigger not in outside])


def possible_line(cfg: dict, trigger: str, why: str = "") -> str:
    """The warning line of a possible match, naming its boundary and, when there is one, why it is not more."""
    return f"possible match with '{trigger}'" + (f" (only inside {why})" if why else "") + explain(cfg, trigger)


def check_warn_markers(cfg: dict, tool_name: str, tool_input: dict) -> list[str]:
    """One line per warn-only marker, each naming its boundary — the same `→ NG-n "…" (origin; source)` tail a
    refusal carries, so `report`, `doctor` and LUMIS Amend attribute a warning to a boundary exactly as they
    attribute a block. Runs for commands too: a lone word out of a long sentence shows up in `python -m …`
    more often than anywhere else. A commit message is data, like for a refusal. Since 2026-09-29 it also carries a
    blocking keyword found only inside another tool's command-line option (a shell command, a CI file, a lockfile or a
    manifest; never a technology) or a library's import spelling another form of the word."""
    return sorted({possible_line(cfg, trigger, why)
                   for _kind, trigger, why in judge_tool_input(cfg, tool_name, tool_input)["warn"]})


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
#
# The table carries the free guard pack's corrections since 2026-09-30 (they were `GUARD_PACK_LEXICON_FIXES`, applied
# to that pack's config only, while this hook was frozen): no `services/`, `plugins/`, `contracts/` (ordinary folders of
# web apps), no `kotlin` (a highlighter's language list, a Kotlin backend); `com.android.application`, `kotlin android`
# for an Android build; `create-expo-app`; the SDKs that were not refused (`smtplib`, `fastapi-mail`, `onelogin`,
# `saml2`, `paypalrestsdk`, `python-socketio`, …); `web socket`, `send mail`, `resend.emails`, `django.core.mail`.
# `expo`, `ws`, `resend` and `pika` stay packages: the free pack dropped them only because a package was matched as a
# prefix, and a package is matched as a whole name now (`package_hits`). `packages_prefix` names a family of packages
# (`expo-camera`, `@expo/vector-icons`, `react-native-maps`): a config lists them under `deny_package_prefixes`.
CAPABILITY_TRIGGERS = {
    "crypto": {"match": ["crypto", "web3", "blockchain", "крипт", "блокчейн", "токен", "smart contract", "смарт-контракт"],
               "packages": ["web3", "ethers", "solana", "wagmi", "viem", "bitcoinlib", "hardhat", "truffle"], "paths": ["web3/"],
               "keywords": ["web3", "solidity", "ethereum", "metamask", "erc20", "smart contract", "wallet connect"]},
    "microservices": {"match": ["microservice", "микросервис", "kafka", "rabbitmq"],
                      "packages": ["kafka-python", "aiokafka", "pika", "celery", "grpcio", "nameko"], "paths": [],
                      "keywords": ["kafka", "rabbitmq", "grpc", "consul", "istio", "service mesh"]},
    "native_mobile": {"match": ["ios", "android", "native mobile", "мобильн", "flutter", "react native"],
                      "packages": ["react-native", "expo", "flutter", "capacitor", "cordova", "create-expo-app"],
                      "packages_prefix": ["expo-", "@expo/", "react-native-", "@react-native/"], "paths": ["ios/", "android/"],
                      "keywords": ["react native", "swiftui", "xcode", "android studio", "com.android.application", "kotlin android"]},
    "open_banking": {"match": ["open banking", "банковск", "core ledger", "psd2"],
                     "packages": ["plaid", "tink", "truelayer"], "paths": [], "keywords": ["open banking", "psd2", "plaid", "core ledger"]},
    "payments": {"match": ["payment", "платеж", "платёж", "billing", "эквайринг", "stripe"],
                 "packages": ["stripe", "braintree", "adyen", "paypal-checkout", "paypalrestsdk", "paypalcheckoutsdk"],
                 "paths": ["billing/"], "keywords": ["stripe", "paypal", "braintree", "adyen"]},
    "complex_auth": {"match": ["saml", "sso", "ldap", "enterprise auth", "kerberos"],
                     "packages": ["python3-saml", "ldap3", "keycloak", "onelogin", "pysaml2", "saml2"], "paths": [],
                     "keywords": ["saml", "ldap", "kerberos", "keycloak"]},
    "websockets": {"match": ["websocket", "вебсокет", "realtime", "real-time"],
                   "packages": ["socket.io", "ws", "websockets", "socketio", "python-socketio", "flask-socketio"], "paths": [],
                   "keywords": ["websocket", "socket.io", "web socket"]},
    "email": {"match": ["email sending", "рассылк", "newsletter", "smtp"],
              "packages": ["nodemailer", "sendgrid", "resend", "mailgun", "smtplib", "aiosmtplib", "fastapi-mail", "flask-mail"],
              "paths": [], "keywords": ["smtp", "sendgrid", "mailgun", "resend.emails", "send mail", "django.core.mail"]},
    "multi_tenancy": {"match": ["multi-tenan", "multitenan", "мультитенант", "team accounts", "organizations", "командн"],
                      "packages": [], "paths": ["tenants/", "organizations/"], "keywords": ["tenant_id", "organization_id", "workspace_id", "multi-tenancy", "multi-tenant", "multitenancy", "multitenant"]},
    "marketplace": {"match": ["marketplace", "маркетплейс", "plugin store", "adapter sdk"],
                    "packages": [], "paths": ["marketplace/"], "keywords": ["marketplace", "plugin registry", "adapter sdk"]},
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
    "paddle", "recurly", "razorpay", "mollie",
    "blockchain", "solidity", "ethereum", "bitcoin", "metamask", "web3", "erc20",
    "electron", "tauri", "flutter", "expo", "swiftui", "xcode", "cordova", "capacitor",
    "django", "flask", "fastapi", "express", "nestjs", "nextjs", "rails", "laravel", "spring",
    "sqlalchemy", "sqlmodel", "prisma", "drizzle", "typeorm", "sequelize", "mongoose",
    "microservice", "microservices", "serverless", "istio", "consul", "airflow", "spark",
    "tensorflow", "pytorch", "langchain", "pinecone", "weaviate", "chromadb",
}
# The words of a Non-Goal phrase that code uses every day for something else (founder decision 2026-09-29). Inside a
# short boundary the phrase blocks («payment collection»), and so does each of its words — `payment` and `billing`
# name the capability itself — except a word on this list, which only warns: `collections` is a standard library
# module, `session` an HTTP or database session, `mobile` a layout breakpoint, `yarn` and `lockfile` what every
# JavaScript repository names in its ignore files, CI and lockfiles; `connection`, `pool`, `generated`, `mocks` what
# every Go or Java repository says in its own code (decision 1б, 29.09: the phrases `connection pool` and `generated
# mocks` still block). No capability word (`CAPABILITY_TRIGGERS`) and no technology is on it (test_boundary_markers).
# The product's `boundary_markers.CODE_HOMONYMS` is the same list.
CODE_HOMONYMS = {
    "collection", "collections", "session", "sessions", "record", "records", "mobile", "yarn", "lockfile", "lockfiles",
    "token", "tokens", "cache", "caches", "queue", "queues", "stream", "streams", "channel", "channels",
    "message", "messages", "connection", "connections", "pool", "pools", "generated", "generate", "modify", "modified",
    "manually", "manual", "persistent", "mock", "mocks",
}
SHORT_BOUNDARY_WORDS = 4  # longer than this, in the founder's own words, and the boundary's lone words only warn
PHRASE_BRIDGES = {"of"}   # the one dropped word a phrase steps over (see markers_for); the product's list is the same
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
# A token the founder writes as code: anything in backticks without a space (`eval`, `package-lock.json`) and an
# annotation or decorator (`@Transactional`), an `@` that opens a word (`admin@example.com` is not one). It blocks as
# written, and its plain words only warn: «never use @Transactional» armed a bare `transactional` that refused comment
# lines that merely said a method was transactional (retro of a public repository, 2026-09-29).
CODE_SPAN_RE = re.compile(r"`([^`\s]{2,80})`")
ANNOTATION_RE = re.compile(r"(?<![\w@.`/])@[A-Za-z_](?:[\w.\-/]*\w)?")
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


def code_names(text: str) -> list:
    """The tokens a boundary writes as code, lower-cased, in order (`@Transactional` → `@transactional`); a trailing
    `()` and sentence punctuation dropped. A backticked word every repository contains is not a name; a token under
    three characters is too short to mean one thing. The product's `boundary_markers.code_names`, ported."""
    raw = [m.group(1) for m in CODE_SPAN_RE.finditer(str(text or ""))] + \
          [m.group(0) for m in ANNOTATION_RE.finditer(str(text or ""))]
    out: list = []
    for token in raw:
        token = token.strip().rstrip(".,;:!?").lower()
        if token.endswith("()"):
            token = token[:-2]
        body = token.lstrip("@")
        if len(body) < 3 or not re.search(r"[^\W\d_]", body):
            continue
        if token.isalnum() and (token in COMMON_CODE_WORDS or token in GENERIC_ARCHITECTURAL_STOPWORDS
                                or token in FUNCTION_WORDS):
            continue
        if token not in out:
            out.append(token)
    return out


CODE_MASK = str.maketrans({".": "\x00", ";": "\x01", ":": "\x02"})
CODE_UNMASK = str.maketrans({"\x00": ".", "\x01": ";", "\x02": ":"})


def refused_code_names(boundary: str) -> list:
    """`code_names` of the statements that refuse (a code token in the half that prescribes is what the founder
    wants), split with the code tokens masked so the dot of `package-lock.json` does not end a statement."""
    text = str(boundary or "")
    chars = list(text)
    for m in list(CODE_SPAN_RE.finditer(text)) + list(ANNOTATION_RE.finditer(text)):
        for i in range(*m.span()):
            chars[i] = chars[i].translate(CODE_MASK)
    segments = SEGMENT_RE.split("".join(chars))
    kept = [p for p in segments if not prescribes(p)] or segments
    return code_names(" ".join(kept).translate(CODE_UNMASK))


def markers_for(boundary: str, vocabulary: set) -> tuple:
    """(blocking markers, warn-only markers) for one boundary — code names first, then phrases, then words."""
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
        # only words that stand next to each other in the founder's sentence: «users at once» is not a phrase
        # «users once», and «editing between several» is not «editing several» — those refused `# remind users once
        # per day` (audit 2026-09-23). A dropped word ends the run instead of being stepped over — except «of», which
        # keeps one noun phrase together («sharing of patient records»).
        run: list = []
        for t in clause.split() + [""]:
            if t in PHRASE_BRIDGES:
                continue
            if t and len(t) > 2 and t not in FUNCTION_WORDS:
                run.append(t)
                continue
            phrases += ["%s %s" % (a, b) for a, b in zip(run, run[1:]) if a != b]
            run = []
    # an item of an enumeration that is one rare word is that item in full: such items lead the list, because the
    # per-boundary cap cuts from the tail and a word the founder listed on its own must survive it
    enumerated = len(clauses) >= LIST_ITEMS_MIN and len(clauses[0].split()) <= LIST_HEAD_WORDS
    list_items = {c for c in clauses if len(c.split()) == 1 and len(c) > 3} if enumerated else set()
    # a token written as code leads (the most specific marker); its plain words are a part of it and only warn
    code = refused_code_names(boundary)
    code_parts = {w for token in code for w in normalize(PUNCTUATION_RE.sub(" ", token)).split()} - set(code)
    raw = list(dict.fromkeys(code + [t for t in tokens if t in list_items] + phrases + tokens))
    whole = not raw
    if whole:
        raw = [normalize(boundary)]
    short = len(words) <= SHORT_BOUNDARY_WORDS
    blocking, warning = [], []
    phrase_words: set = set()  # the words of the phrases armed so far: every phrase comes before the first word
    for text in raw:
        parts = text.split()
        if text in code:
            if text not in vocabulary:
                blocking.append(text)
            continue
        if not text or len(text) < 3 or text in GENERIC_ARCHITECTURAL_STOPWORDS:
            continue
        if not whole and any(len(w) < 3 or w.isdigit() for w in parts):
            continue
        if all(w in vocabulary or w in COMMON_CODE_WORDS or w in GENERIC_ARCHITECTURAL_STOPWORDS for w in parts):
            continue
        if whole:
            continue  # nothing but function words: a marker nobody would ever write into a file
        if " " in text:
            blocking.append(text)
            phrase_words.update(parts)
        elif short and text in TECHNOLOGY_WORDS:
            blocking.append(text)  # a short boundary whose one word is the name of the thing refused
        elif text in code_parts or (short and text in phrase_words and text in CODE_HOMONYMS):
            # one part of a longer name the boundary gives, and a word code uses for something else: the phrase or
            # the code name blocks, the word warns — a lone `collection` refused `from collections import
            # defaultdict` (2026-09-29). `payment` and `billing` name the capability itself and keep blocking.
            warning.append(text)
        elif short or text in list_items:
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
    code that crosses it is not. These warn and are logged (`noted`), they are never refused.

    Narrowed on 2026-09-23: the exemption followed the directory, so `docs/checkout.py` and a billing module parked in
    `tests/fixtures/` were prose. Code is code wherever it lives; a test directory exempts its test files and the files
    directly in it (conftest, helpers), not everything beneath it. A Markdown plan that *announces* crossing a
    boundary is still `noted`: telling a plan that describes the Non-Goal from one that schedules it is a judgement
    about meaning, and a text hook cannot make it — the founder reads the `noted` line and decides."""
    p = _clean_path(path)
    if not p:
        return False
    if p.endswith(PROSE_SUFFIXES):
        return True
    parts = p.split("/")
    base = parts[-1]
    if base.startswith(("test_", "test-")) or any(m in base for m in ("_test.", ".test.", ".spec.", "_spec.")):
        return True
    if len(parts) > 1 and parts[-2] in TEST_DIRS:
        return True  # tests/conftest.py, spec/helpers.rb: the support files a test directory holds
    if p.endswith(CODE_SUFFIXES):
        return False
    return bool(set(parts[:-1]) & DOC_DIRS)


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
    return sorted(set(hits + architecture_text_hits(cfg, path, text)))


def architecture_text_hits(cfg: dict, path: str, text: str) -> list[str]:
    """Routes, models and tables in `text` (the content of the file at `path`) that ARCHITECTURE.md does not declare.
    The part of `check_architecture` that reads text only, so `check-diff` can run it on the added lines of a diff
    with the same regexes. Empty for a file that is not code (`CODE_SUFFIXES`)."""
    arch = cfg.get("architecture") if isinstance(cfg.get("architecture"), dict) else {}
    if not str(path or "").lower().endswith(CODE_SUFFIXES):
        return []
    hits: list[str] = []
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
        found = MODEL_RE.findall(text) + TABLE_RE.findall(text) + (PRISMA_RE.findall(text) if str(path).lower().endswith(".prisma") else [])
        for name in found:
            if name.lower() not in known and name.lower() not in {"base", "model", "table", "meta"}:
                hits.append(f"new model/table '{name}' is not among the entities of ARCHITECTURE.md")
    return hits


# --- boundary classes: what is the founder's to decide whatever the Non-Goals say ----------------------------------
# A Non-Goal names a feature. Three things are the founder's in every project and no Non-Goal sentence spells them:
# a dependency added to the stack, a command that leaves the machine (a push, a publish, a deploy), a write outside
# the project. Each is held for approval by default ("ask"); `"classes"` in the config sets allow | ask | block.
# Read-only commands are never a class hit, and a package the Non-Goals already forbid stays a refusal: the class
# check runs only after the Non-Goal check found nothing.
PIP_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url", "--extra-index-url",
                   "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--src", "--upgrade-strategy", "--python-version",
                   "--platform", "--implementation", "--abi", "--only-binary", "--no-binary", "--progress-bar", "--log",
                   "--cache-dir", "--trusted-host", "--proxy", "--timeout", "--retries", "--python", "-p", "--group", "-G",
                   # these take a value too: without them `pip install -e . --config-settings editable_mode=compat` held
                   # `editable_mode` as a new dependency, `--exists-action w` held `w` (audit 2026-09-23)
                   "--config-settings", "-C", "--exists-action", "--report", "--use-feature", "--use-deprecated",
                   "--global-option", "--install-option", "--root-user-action", "--keyring-provider", "--cert",
                   "--client-cert", "--extra", "--extras", "-E", "--source", "--markers", "--index", "--default-index",
                   "--index-strategy", "--resolution", "--prerelease", "--python-platform", "--categories", "--package"}
JS_VALUE_FLAGS = {"--registry", "--prefix", "-w", "--workspace", "--filter", "-F", "--cwd", "--tag", "--save-prefix", "--scope",
                  # `npm install --omit dev` held `dev`, `--loglevel error` held `error` (audit 2026-09-23)
                  "--omit", "--include", "--loglevel", "--cache", "--userconfig", "--install-strategy", "--before", "--otp",
                  "--location", "--dir"}
OTHER_VALUE_FLAGS = {"-v", "--version", "--source", "--git", "--branch", "--rev", "--path", "--features", "-F", "--package", "-p",
                     "--group", "-G", "--registry", "--vers", "--rename"}
CONDA_VALUE_FLAGS = {"-c", "--channel", "-n", "--name", "-p", "--prefix", "--file", "--solver", "--repodata-fn"}
# `rye add resend --features x`: rye's own options with a value, besides pip's (third review of 30.09)
RYE_VALUE_FLAGS = PIP_VALUE_FLAGS | {"--features", "--optional", "--git", "--url", "--path", "--branch", "--rev", "--tag",
                                     "--pyproject"}
# An unknown long flag followed by one of these words: the word is the flag's value, not a package
# (`--omit dev`, `--loglevel error`, `--exists-action w`).
FLAG_VALUE_WORDS = {"dev", "prod", "production", "development", "optional", "peer", "error", "warn", "silent", "info",
                    "verbose", "http", "timing", "notice", "true", "false", "global", "project", "user", "w", "s", "i", "b", "a"}
# manager -> subcommands that name a package to add. The same manager with no package named (`npm install`,
# `pip install -r requirements.txt`, `uv sync`, `bundle install`) installs what is already declared: not a change.
ADD_SUBCOMMANDS = {
    "pip": {"install"}, "uv": {"add"}, "poetry": {"add"}, "pipenv": {"install"}, "pdm": {"add"}, "rye": {"add"},
    "npm": {"install", "i", "add", "in"}, "pnpm": {"add", "install", "i"}, "yarn": {"add"}, "bun": {"add", "a", "install", "i"},
    "expo": {"install"}, "cargo": {"add"}, "go": {"get"}, "gem": {"install"}, "bundle": {"add"}, "composer": {"require"},
    "conda": {"install"}, "mamba": {"install"}, "micromamba": {"install"},
}
# a tool installed for the whole machine (`npm install -g vercel`) is not a dependency of this project; `pipx`,
# `uv tool install`, `cargo install`, `go install` and `yarn global add` never reach ADD_SUBCOMMANDS for the same reason
GLOBAL_INSTALL_FLAGS = {"-g", "--global", "--location=global"}
# upgrading the installer itself is housekeeping, not a dependency of the product
INSTALLER_SELF = {"pip", "setuptools", "wheel", "npm", "pnpm", "yarn", "uv", "poetry", "bun"}
GH_OUTBOUND = {("repo", "create"), ("repo", "delete"), ("repo", "rename"), ("repo", "edit"), ("repo", "archive"),
               ("repo", "fork"), ("repo", "sync"), ("release", "create"), ("release", "upload"), ("release", "delete"),
               ("release", "edit"), ("pr", "merge"), ("pr", "create"), ("gist", "create"), ("alias", "set"),
               ("secret", "set"), ("secret", "delete"), ("variable", "set"), ("variable", "delete")}
# gh's own commands. Anything else after `gh` is an alias or an extension the guard cannot read (`gh alias set rd
# 'repo delete'` and then `gh rd x/y`), so it is held rather than guessed at.
GH_COMMANDS = {"auth", "browse", "codespace", "cs", "gist", "issue", "org", "pr", "project", "release", "repo", "cache",
               "run", "workflow", "alias", "api", "completion", "config", "extension", "extensions", "ext", "gpg-key",
               "label", "ruleset", "rs", "search", "secret", "ssh-key", "status", "variable", "attestation", "copilot",
               "help", "agent-task", "preview", "accessibility", "licenses", "version"}
# (executable, first word) pairs that publish, deploy or rewrite something that is not on this machine
OUTBOUND_VERBS = {
    ("twine", "upload"), ("cargo", "publish"), ("docker", "push"), ("podman", "push"),
    ("flyctl", "deploy"), ("fly", "deploy"), ("railway", "up"), ("railway", "deploy"),
    ("wrangler", "publish"), ("wrangler", "deploy"), ("vercel", "deploy"), ("netlify", "deploy"), ("firebase", "deploy"),
    ("serverless", "deploy"), ("sls", "deploy"),
    ("uv", "publish"), ("poetry", "publish"), ("flit", "publish"), ("hatch", "publish"), ("pdm", "publish"),
    ("bun", "publish"), ("gem", "push"), ("mvn", "deploy"), ("gradle", "publish"), ("gradlew", "publish"),
    ("terraform", "apply"), ("terraform", "destroy"), ("tofu", "apply"), ("tofu", "destroy"),
    ("pulumi", "up"), ("pulumi", "destroy"), ("helm", "install"), ("helm", "upgrade"), ("helm", "uninstall"),
    ("helm", "rollback"), ("kubectl", "apply"), ("kubectl", "create"), ("kubectl", "delete"), ("kubectl", "replace"),
    ("kubectl", "patch"), ("kubectl", "rollout"), ("kubectl", "scale"), ("kubectl", "edit"), ("kubectl", "set"),
}
# git configuration that redirects what a later command does: an alias (`alias.p=push`, then `git p`), a remote's
# URL (the same effect as the held `git remote set-url`), a URL rewrite
GIT_REDIRECT_KEY = re.compile(r"^(?:alias\..+|remote\..+\.(?:url|pushurl)|url\..+\.(?:insteadof|pushinsteadof))$", re.I)
COPY_MOVE = {"cp", "mv", "copy", "move", "xcopy", "robocopy", "copy-item", "cpi", "move-item", "mi"}
CMD_SWITCH = re.compile(r"^/[A-Za-z]+(?::\S*)?$")  # `copy /Y`, `robocopy /MIR`: a switch of a cmd verb, not a path
CMD_VERBS = {"copy", "move", "xcopy", "robocopy", "del", "erase", "rd", "md"}
# What removes or creates the paths it is given: each of them is a write to that path (audit 2026-09-23 — `rm -rf
# C:/Users/…/Documents`, `Remove-Item ..\sibling`, `touch ../x`, `mkdir ../newdir` all walked past the class).
PATH_WRITERS = {"rm", "rmdir", "rd", "del", "erase", "unlink", "shred", "truncate", "touch", "mkdir", "md",
                "remove-item", "ri", "new-item", "ni"}
# the flags of each that take a value; `-r` is a value only for truncate and touch — for rm it is "recursive"
PATH_WRITER_VALUE_FLAGS = {"truncate": {"-s", "--size", "-r", "--reference"}, "touch": {"-d", "--date", "-t", "-r", "--reference"},
                           "shred": {"-n", "--iterations", "-s", "--size"}, "mkdir": {"-m", "--mode"}, "md": {"-m", "--mode"},
                           "new-item": {"-itemtype", "-type", "-name", "-value"}, "ni": {"-itemtype", "-type", "-name", "-value"}}
PS_ITEM_FLAGS = {"-include", "-exclude", "-filter"}
# PowerShell's writers: the target is -Path / -FilePath / -LiteralPath, or the first positional
PS_WRITERS = {"set-content", "sc", "add-content", "ac", "out-file", "clear-content", "clc", "export-csv", "export-clixml"}
PS_VALUE_FLAGS = {"-value", "-encoding", "-width", "-inputobject", "-delimiter", "-stream", "-filter", "-include", "-exclude"}
PS_PATH_FLAGS = {"-path", "-literalpath", "-filepath", "-pspath", "-lp"}
# The agent's own client keeps state in its home folder: its memory, its sessions, its plans. Writing those is not
# "outside the project" for this class, and asking about them on every turn would teach the founder to click "yes".
# Only these state folders are open; the rest of an agent's home — ~/.codex/config.toml (approval and sandbox
# policy), ~/.cursor/mcp.json (a new MCP server), ~/.claude/hooks, agents and commands — is configuration that
# changes what the agent may do, and it is held like any other write outside the project (audit 2026-09-23).
AGENT_STATE_DIRS = (".claude/projects", ".claude/todos", ".claude/plans", ".claude/shell-snapshots", ".claude/statsig",
                    ".claude/ide", ".codex/sessions", ".codex/log", ".codeium/windsurf/memories")
# what only starts another command: `time git push`, `command git push`, `exec git push`, `xargs git push`
COMMAND_PREFIXES = {"time", "command", "exec", "builtin", "nice", "ionice", "xargs", "watch", "stdbuf", "chronic",
                    "unbuffer", "caffeinate", "noglob", "call", "start"}
PREFIX_VALUE_FLAGS = {"-n", "-i", "-I", "-L", "-P", "-d", "-a", "-s", "-E", "-c", "-o", "-e", "--max-args", "--max-procs",
                      "--delimiter", "--arg-file", "--replace", "--interval", "--adjustment"}
# a shell reading its script from a pipe runs whatever the left side prints: `echo git push | sh`
PIPE_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "pwsh", "powershell", "iex", "invoke-expression"}
START_PROCESS_VALUE_FLAGS = {"-workingdirectory", "-windowstyle", "-verb", "-redirectstandardoutput",
                             "-redirectstandarderror", "-redirectstandardinput", "-credential"}


def _exe_name(token: str) -> str:
    exe = str(token or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if exe.endswith(suffix):
            return exe[: -len(suffix)]
    return exe


_SHELL_SPECIAL_RE = re.compile(r"[\"'`&|;\n]")


def _split_shell(text: str) -> list[tuple[str, str]]:
    """(segment, the separator in front of it) for a shell line, split on `;`, `&&`, `||`, `|`, `&` and newlines —
    outside quotes. `echo "done; git push later" >> NOTES.txt` is one command, not two; `>|`, `2>&1`, `&>` are
    redirects, `git push&` is a push sent to the background (audit 2026-09-23). It jumps from one quote or separator
    character to the next (`_SHELL_SPECIAL_RE`): the walk one character at a time took 0.4 s per call on a 1 MB command,
    and a call reads a command about eight times (third review of 30.09)."""
    s = str(text or "")
    out: list[tuple[str, str]] = []
    sep = ""
    start = pos = 0
    while True:
        m = _SHELL_SPECIAL_RE.search(s, pos)
        if not m:
            break
        i = m.start()
        ch = s[i]
        if ch in "'\"`":
            close = s.find(ch, i + 1)
            if close < 0:
                break  # an unclosed quote runs to the end, part of the last segment
            pos = close + 1
            continue
        pair = s[i:i + 2]
        prev = s[i - 1] if i else ""
        if pair in ("&&", "||"):
            out.append((s[start:i], sep))
            sep, start = pair, i + 2
        elif ch == "|" and prev != ">":
            out.append((s[start:i], sep))
            sep, start = "|", i + (2 if pair == "|&" else 1)
        elif ch == "&" and prev not in "<>" and s[i + 1:i + 2] != ">":
            out.append((s[start:i], sep))
            sep, start = "&", i + 1
        elif ch in ";\n":
            out.append((s[start:i], sep))
            sep, start = ch, i + 1
        else:  # a `|` or `&` of a redirect (`>|`, `2>&1`, `&>`): part of the segment
            pos = i + 1
            continue
        pos = start
    out.append((s[start:], sep))
    return [(seg, sep) for seg, sep in out if seg.strip()]


def _shell_tokens(segment: str) -> list[str]:
    """Words of one command with the quotes taken off and quoted spaces kept: `"C:\\Program Files\\Git\\bin\\git.exe"
    push` is two words, `cp a.txt "../my dir/"` is three. Backslashes are not escapes here — on Windows they are
    the path separator. The reading `shlex` gives in POSIX mode with no escape and no comments, in one pass: shlex
    grows a token one character at a time, and a command of one 1 MB word took 23 s (third review of 30.09)."""
    s = str(segment or "")
    out: list[str] = []
    buf: list[str] = []
    quote = ""
    for ch in s:
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
        elif ch in "'\"":
            quote = ch
        elif ch in " \t\r\n":
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if quote:  # an unbalanced quote: the plain split is the best reading left
        return [t.strip("'\"`") for t in s.split() if t.strip("'\"`")]
    if buf:
        out.append("".join(buf))
    return out


def _start_process(tokens: list[str]) -> list[str]:
    """`Start-Process git -ArgumentList push` -> ['git', 'push']."""
    prog, args = "", []
    i = 1
    while i < len(tokens):
        a, low = tokens[i], tokens[i].lower()
        if low == "-filepath" and i + 1 < len(tokens):
            prog, i = tokens[i + 1], i + 2
            continue
        if low in ("-argumentlist", "-args") and i + 1 < len(tokens):
            args += [x for x in re.split(r"[,\s]+", tokens[i + 1]) if x]
            i += 2
            continue
        if low.startswith("-"):
            i += 2 if low in START_PROCESS_VALUE_FLAGS else 1
            continue
        if not prog:
            prog = a
        else:
            args += [x for x in re.split(r"[,\s]+", a) if x]
        i += 1
    return [prog] + args if prog else []


def _bare_command(tokens: list[str]) -> list[str]:
    """The command itself, with what only surrounds it taken off: a group (`(git push)`, `{ git push; }`), a
    background `&`, leading `VAR=value` assignments, `npx`, prefixes (`time`, `command`, `exec`, `xargs`, `watch`,
    `nice -n 5`) and `Start-Process`."""
    tokens = [t for t in tokens if t]
    for _ in range(8):
        while tokens and tokens[0] in ("(", "{", "!", "if", "then", "do", "else", "elif", "while", "until"):
            tokens = tokens[1:]
        if tokens and tokens[0].startswith("(") and not tokens[0].startswith("(("):
            tokens = [tokens[0].lstrip("(")] + tokens[1:]
        while tokens and tokens[-1] in (")", "}", "&", "fi", "done"):
            tokens = tokens[:-1]
        if tokens and tokens[-1].endswith((")", "}")) and not tokens[-1].startswith("$("):
            tokens = tokens[:-1] + [tokens[-1].rstrip(")}")]
        tokens = [t for t in tokens if t]
        while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            return []
        exe = _exe_name(tokens[0])
        if exe in ("npx", "pnpx", "bunx") or exe in COMMAND_PREFIXES:
            rest = tokens[1:]
            while rest and (rest[0].startswith("-") or rest[0].isdigit() or rest[0] == ""
                            or (exe in ("start", "call") and CMD_SWITCH.match(rest[0]))):
                rest = rest[2:] if (rest[0] in PREFIX_VALUE_FLAGS and exe not in ("npx", "pnpx", "bunx")) else rest[1:]
            tokens = rest
            continue
        if exe in ("start-process", "saps"):
            tokens = _start_process(tokens)
            continue
        return tokens
    return tokens


def _xargs_runs_a_manager(segment: str, exe: str) -> bool:
    """The segment is `xargs [options] <manager> …` fed by the pipe (not `-a <file>`: `_xargs_program`, the reading
    the tamper check gives xargs) and the program is a package manager or a package runner — the only case where the
    words the pipe carries are read as that command's arguments."""
    raw = _shell_tokens(segment)
    if not raw or _exe_name(raw[0]) != "xargs":
        return False
    prog, from_file = _xargs_program(raw[1:])
    manager = _manager_exe(prog)
    return (not from_file and manager == _manager_exe(exe)
            and (manager in ADD_SUBCOMMANDS or manager in MANAGER_READINGS or manager in NPX_RUNNERS
                 or manager in ("pipx", "uvx") or bool(re.match(r"^(?:pip|python|py)\d*(?:\.\d+)?$", manager))))


def _command_words(text: str, depth: int = 0, sudo_values: bool = False) -> list[list[str]]:
    """The commands a shell line runs, as token lists: separators read outside quotes, wrappers opened (`bash -c`,
    `sudo`, `env X=1`), `eval` and a pipe into a shell read as the command they run, `$(…)` read too, and
    `_bare_command` applied. What `cd` does to them is left to the caller. `sudo_values` (the package reading only):
    `sudo -u deploy pip install x` runs `pip install x`, not `deploy`."""
    out: list[list[str]] = []
    prev: list[str] = []
    for segment, sep in _split_shell(text):
        if depth < 2:
            for a, b in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", segment):
                if (a or b).strip():
                    out += _command_words(a or b, depth + 1, sudo_values)
        inner = _wrapped_command(segment, sudo_values)
        if inner and depth < 2:
            out += _command_words(inner, depth + 1, sudo_values)
            prev = []
            continue
        tokens = _bare_command(_shell_tokens(segment))
        if not tokens:
            prev = []
            continue
        exe = _exe_name(tokens[0])
        if exe == "eval" and depth < 2:
            out += _command_words(" ".join(tokens[1:]), depth + 1, sudo_values)
            prev = []
            continue
        if (sep == "|" and exe in PIPE_SHELLS and all(t.startswith("-") for t in tokens[1:]) and prev
                and _exe_name(prev[0]) in ("echo", "printf", "write-output") and depth < 2):
            out += _command_words(" ".join(t for t in prev[1:] if not t.startswith("-")), depth + 1, sudo_values)
        if sep == "|" and prev and _exe_name(prev[0]) in ("echo", "printf") and _xargs_runs_a_manager(segment, exe):
            # `echo resend | xargs pip install`: xargs puts what the pipe carries after the command (review 30.09)
            tokens = tokens + [w for t in prev[1:] if not t.startswith("-") for w in re.split(r"\s+|\\n", t) if w]
        out.append(tokens)
        prev = tokens
    return out


def _package_name(token: str) -> str:
    """`stripe>=5` -> stripe, `@scope/pkg@1.2` -> @scope/pkg, `serde@1` -> serde, a PEP 508 direct reference
    `resend @ https://…/resend-2.0.0.tar.gz` -> resend; any other URL is kept as it is."""
    t = token.strip()
    direct = re.match(r"^([A-Za-z0-9][A-Za-z0-9._\-]*)\s*(?:\[[^\]]*\]\s*)?@\s*[A-Za-z][\w+.\-]*://", t)
    if direct:
        return direct.group(1)
    if "://" in t or t.startswith("git+"):
        return t[:120]
    if t.startswith("@"):
        return "@" + t[1:].split("@", 1)[0]
    return re.split(r"[<>=!~\[;@:\s]", t, maxsplit=1)[0]


@lru_cache(maxsize=8192)  # a long file compares the same few names against every package: one spelling each
def _pep503(name: str) -> str:
    """One spelling per package for comparing names: lower case, runs of `-`, `_`, `.` as one `-` (PyPI's own rule).
    It never makes `fast-api` equal `fastapi`: those are two different projects."""
    return re.sub(r"[-_.]+", "-", str(name or "").strip().lower())


def _is_local_path(token: str) -> bool:
    """`.`, `./dist/x.whl`, `../lib`, `C:\\wheels\\x.whl`: the project or a local build, not a package from outside."""
    t = token.strip()
    if "://" in t or t.startswith("git+"):
        return False
    return (t.startswith((".", "/", "~")) or "\\" in t or bool(re.match(r"^[A-Za-z]:", t))
            or t.endswith((".whl", ".tar.gz", ".tgz", ".zip")))


def _named(args: list[str], value_flags: set[str]) -> list[str]:
    """The positional arguments, with the value of each flag that takes one skipped — a run of short flags too, when
    its last one takes a value (`pdm add -dG test resend`: `test` is the group). After a long flag this list does not
    know, a word that is an ordinary flag value (`dev`, `error`, `w`) is taken as that flag's value."""
    out: list[str] = []
    skip = False
    after_unknown = False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a in value_flags or (bool(re.fullmatch(r"-[A-Za-z]{2,}", a)) and f"-{a[-1]}" in value_flags)
            after_unknown = not skip and a.startswith("--") and "=" not in a
            continue
        if after_unknown and a.lower() in FLAG_VALUE_WORDS:
            after_unknown = False
            continue
        after_unknown = False
        out.append(a)
    return out


def dependency_additions(command: str) -> list[str]:
    """The packages a shell command adds to the project, by name. Empty for an install of what is already declared,
    and for a tool installed for the whole machine (`npm install -g`)."""
    found: list[str] = []
    for _manager, name in _installs(command):
        if name not in found:
            found.append(name)
    return found


def _machine_installs(exe: str, rest: list[str]) -> list[tuple[str, str]] | None:
    """(manager, package) for an install for the whole machine (`pipx install|run|inject`, `uv tool install|run`,
    `uvx`, `cargo install`, `go install|run`, `yarn global add`, a system package manager); None when the command is
    not one of these forms."""
    words = [a for a in rest if not a.startswith("-")]
    low = [w.lower() for w in words]
    names: list[str] | None = None
    if exe == "pipx" and low[:1] and low[0] in ("install", "run"):
        names = words[1:] if low[0] == "install" else words[1:2]
    elif exe == "pipx" and low[:1] == ["inject"]:
        names = words[2:]
    elif exe == "uv" and low[:2] in (["tool", "install"], ["tool", "run"]):
        names = words[2:3]
    elif exe == "uvx":
        names = words[:1]
    elif exe == "cargo" and low[:1] == ["install"]:
        names = words[1:]
    elif exe == "go" and low[:1] in (["install"], ["run"]):
        names = words[1:2]
    elif exe == "yarn" and low[:2] == ["global", "add"]:
        names = words[2:]
    elif exe in SYSTEM_INSTALLERS and low[:1] and low[0] in ("install", "reinstall"):
        names = words[1:]
    if names is None:
        return None
    return [(exe, _package_name(n)) for n in names if n and not _is_local_path(n) and _package_name(n)]


# The options a JS manager takes before its subcommand in a monorepo — `pnpm --filter web add ws`, `pnpm -C apps/web
# add ws`, `yarn --cwd web add ws`, `npm --prefix web i ws`, `bun --cwd web add ws` — each with its value; and yarn's
# `workspace <name>`, which runs the rest in one workspace (`yarn workspace web add ws`). Until the second review of 30.09 the first
# word after the options was taken as the subcommand and these installs were not read (review 30.09).
JS_GLOBAL_VALUE_FLAGS = {"--filter", "-F", "-C", "--dir", "--prefix", "--cwd", "-w", "--workspace", "--registry",
                         "--loglevel", "--userconfig", "--cache"}


def _manager_exe(token: str) -> str:
    """The program a command word runs, as `_exe_name` reads it — and a shell variable named after a manager read as
    that manager (`$PIP install resend`, `${NPM_BIN} i ws`, make's `$(PIP) install resend`): a Makefile or a CI script
    that keeps the manager in a variable installs with it all the same."""
    exe = _exe_name(token)
    var = re.fullmatch(r"\$[{(]?([a-z_][a-z0-9_]*)[})]?", exe)
    if var:
        for manager in ("pnpm", "yarn", "npm", "pip"):
            if manager in var.group(1):
                return manager
    return exe


# Where a package is installed inside a container the project runs: `docker compose exec api pip install resend`,
# `docker exec api pip install …`, `docker run --rm python:3.12 pip install …` — the command after the service, the
# container or the image is the install, read like any other (review 30.09).
CONTAINER_CLIS = {"docker", "podman", "nerdctl"}
COMPOSE_CLIS = {"docker-compose", "podman-compose"}
# every option of `docker run|exec` and `docker compose run|exec` that takes a value (the third review of 30.09: an
# option missing here made its value the container, and the image the command)
CONTAINER_VALUE_FLAGS = {"-v", "--volume", "-e", "--env", "--env-file", "-w", "--workdir", "--name", "-p", "--publish",
                         "--network", "--net", "--network-alias", "--net-alias", "-u", "--user", "--entrypoint", "--mount",
                         "--platform", "-l", "--label", "--label-file", "-h", "--hostname", "--domainname", "--add-host",
                         "--cpus", "--cpu-period", "--cpu-quota", "--cpu-rt-period", "--cpu-rt-runtime", "-c",
                         "--cpu-shares", "--cpuset-cpus", "--cpuset-mems", "-m", "--memory", "--memory-swap",
                         "--memory-reservation", "--memory-swappiness", "--kernel-memory", "--gpus", "--device",
                         "--device-cgroup-rule", "--device-read-bps", "--device-read-iops", "--device-write-bps",
                         "--device-write-iops", "--blkio-weight", "--blkio-weight-device", "--pull", "--restart",
                         "--log-driver", "--log-opt", "--cap-add", "--cap-drop", "--security-opt", "--ulimit",
                         "--shm-size", "--tmpfs", "--dns", "--dns-option", "--dns-opt", "--dns-search", "--ipc", "--pid",
                         "--pids-limit", "--uts", "--userns", "--cgroupns", "--cgroup-parent", "--runtime",
                         "--volumes-from", "--volume-driver", "--expose", "--link", "--link-local-ip", "--cidfile", "-a",
                         "--attach", "--detach-keys", "--index", "--stop-signal", "--stop-timeout", "--health-cmd",
                         "--health-interval", "--health-retries", "--health-start-period", "--health-start-interval",
                         "--health-timeout", "--ip", "--ip6", "--mac-address", "--isolation", "--oom-score-adj",
                         "--storage-opt", "--sysctl", "--group-add", "--annotation"}
# `poetry|uv|pdm|rye|pipenv|hatch run <command…>` and `conda|mamba|micromamba run -n <env> <command…>` run the command
# in the project's environment: an install there is read like any other (the third review of 30.09), as is the command
# after the `--` of `kubectl|oc exec <pod> -- <command…>`
ENV_RUNNERS = {"poetry", "uv", "pdm", "rye", "pipenv", "hatch"}
ENV_RUNNER_VALUE_FLAGS = {"--with", "--with-editable", "--with-requirements", "--python", "-p", "--package",
                          "--directory", "--project", "--env-file", "--extra", "--group", "--index", "--default-index",
                          "-C", "--venv", "-e", "--env"}
CONDA_RUN_VALUE_FLAGS = {"-n", "--name", "-p", "--prefix", "--cwd"}
COMPOSE_GLOBAL_VALUE_FLAGS = {"-f", "--file", "-p", "--project-name", "--profile", "--env-file", "--project-directory",
                              "--ansi", "--progress", "--parallel"}


def _skip_options(words: list[str], values: set[str]) -> list[str]:
    i = 0
    while i < len(words) and words[i].startswith("-"):
        i += 2 if (words[i] in values and "=" not in words[i]) else 1
    return words[i:]


def _container_inner(tokens: list[str]) -> list[str] | None:
    """The command a container CLI runs inside a container — `docker exec|run [options] <container|image> <command…>`,
    `docker compose [options] exec|run [options] <service> <command…>` — or None for any other command (and for one that
    names no command: the image's own)."""
    exe, rest = _exe_name(tokens[0]) if tokens else "", list(tokens[1:])
    if exe in CONTAINER_CLIS and rest[:1] and rest[0].lower() == "compose":
        exe, rest = "docker-compose", rest[1:]
    if exe in COMPOSE_CLIS:
        rest = _skip_options(rest, COMPOSE_GLOBAL_VALUE_FLAGS)
    elif exe in CONTAINER_CLIS:
        if rest[:1] and rest[0].lower() == "container":
            rest = rest[1:]
    else:
        return None
    if not rest or rest[0].lower() not in ("exec", "run"):
        return None
    rest = _skip_options(rest[1:], CONTAINER_VALUE_FLAGS)
    return rest[1:] if len(rest) > 1 else None


def _runner_inner(tokens: list[str]) -> list[str] | None:
    """The command a runner runs in its place — a container CLI (`_container_inner`), `poetry|uv|pdm|rye|pipenv|hatch
    run …`, `conda|mamba|micromamba run -n <env> …`, `kubectl|oc exec … -- …` — or None."""
    exe, rest = _exe_name(tokens[0]) if tokens else "", list(tokens[1:])
    if exe in ENV_RUNNERS or exe in ("conda", "mamba", "micromamba"):
        values = ENV_RUNNER_VALUE_FLAGS if exe in ENV_RUNNERS else CONDA_RUN_VALUE_FLAGS
        rest = _skip_options(rest, values)
        if rest[:1] and rest[0].lower() == "run":
            return _skip_options(rest[1:], values) or None
        return None
    if exe in ("kubectl", "oc") and "exec" in [r.lower() for r in rest[:3]] and "--" in rest:
        return rest[rest.index("--") + 1:] or None
    return _container_inner(tokens)


def _install_commands(command: str, depth: int = 0) -> list[list[str]]:
    """`_command_words` (with `sudo`'s options read: `_command_words(sudo_values=True)`), with the command a runner
    runs read in its place (`_runner_inner`: a container, an environment, a pod)."""
    import shlex

    out: list[list[str]] = []
    for tokens in _command_words(command, sudo_values=True):
        inner = _runner_inner(tokens)
        if inner and depth < 3:
            out += _install_commands(" ".join(shlex.quote(t) for t in inner), depth + 1)
        else:
            out.append(tokens)
    return out


def _after_global_options(exe: str, rest: list[str]) -> list[str]:
    """The words of a manager's command from its subcommand on: the options before it skipped with their values (the
    JS managers' `JS_GLOBAL_VALUE_FLAGS`, pip's `PIP_VALUE_FLAGS`), and `yarn workspace <name>` / `pnpm --filter`
    taken off. `npm i -w apps/web ws` is unchanged: the subcommand comes first there."""
    values = JS_GLOBAL_VALUE_FLAGS if exe in JS_RUNNERS else PIP_VALUE_FLAGS if exe in ("pip", "uv", "pdm", "rye") else set()
    if exe == "pnpm":
        values = values - {"-w"}  # pnpm's `-w` is `--workspace-root`, a switch
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if (rest[i] in values and "=" not in rest[i]) else 1
    rest = rest[i:]
    if exe == "yarn" and len(rest) > 2 and rest[0].lower() == "workspace":
        return _after_global_options(exe, rest[2:])
    return rest


def _npm_workspace_value_is_package(after: list[str]) -> bool:
    """npm's `-w` takes the workspace (`npm i -w apps/web ws`), alone or at the end of a run of short flags (`-Pw`). When
    its value is the last word, names no path (`@scope/x` is a name) and nothing else was named (`npm install -Pw ws`),
    the word is read as the package: the reading that holds or refuses, not the one that passes (fourth review of 30.09)."""
    last = after[-1] if after else ""
    if len(after) < 2 or last.startswith("-") or "\\" in last or ("/" in last and not last.startswith("@")):
        return False
    return bool(re.fullmatch(r"-[A-Za-z]*w", after[-2]))


def _installs(command: str, machine: bool = False) -> list[tuple[str, str]]:
    """(manager, package) for every package a shell command installs by name — what `dependency_additions` reads,
    with the manager that installs it. `machine` also takes what installs for the whole machine rather than the project
    (`-g`, `yarn global add`, `pipx`, `uv tool`, `uvx`, `cargo install`, `go install`, `brew`/`apt`/`choco`/…): not a
    dependency of this project, still an install of the package (the Non-Goal reading, 2026-09-30)."""
    found: list[tuple[str, str]] = []
    for tokens in _install_commands(command):
        exe, rest = _manager_exe(tokens[0]), tokens[1:]
        if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe) and "-m" in rest:
            i = rest.index("-m")
            if i + 1 < len(rest) and re.match(r"^pip\d*(?:\.\d+)?$", rest[i + 1].lower()):
                exe, rest = "pip", rest[i + 2:]
            else:
                continue
        elif re.match(r"^pip\d+(?:\.\d+)?$", exe):
            exe = "pip"
        if exe == "uv" and rest[:1] and rest[0].lower() == "pip":
            exe, rest = "pip", rest[1:]
        if exe == "dotnet":  # `dotnet add [<project>] package <name>`
            words = [a for a in rest if not a.startswith("-")]
            low = [w.lower() for w in words]
            if low[:1] == ["add"] and "package" in low[1:3] and low.index("package") + 1 < len(words):
                found.append(("dotnet", words[low.index("package") + 1]))
            continue
        if machine:
            elsewhere = _machine_installs(exe, rest)
            if elsewhere is not None:
                found += elsewhere
                continue
        subs = ADD_SUBCOMMANDS.get(exe)
        if not subs:
            continue
        given, low_rest = list(rest), [a.lower() for a in rest]
        rest = _after_global_options(exe, rest)
        words = [a for a in rest if not a.startswith("-")]
        if not words or words[0].lower() not in subs:
            continue
        # a lone `-g` (case matters: `pdm add -G dev x` names a group, third review of 30.09), `--global`,
        # `--location=global` / `--location global`
        if not machine and ("-g" in given or any(a in GLOBAL_INSTALL_FLAGS for a in low_rest if a != "-g")
                            or any(a == "--location" and low_rest[i + 1:i + 2] == ["global"] for i, a in enumerate(low_rest))):
            continue  # a tool for the machine, not a dependency of this project
        after = rest[rest.index(words[0]) + 1:]
        flags = RYE_VALUE_FLAGS if exe == "rye" else PIP_VALUE_FLAGS if exe in ("pip", "uv", "poetry", "pipenv", "pdm") else (
            JS_VALUE_FLAGS if exe in ("npm", "pnpm", "yarn", "bun", "expo") else
            CONDA_VALUE_FLAGS if exe in ("conda", "mamba", "micromamba") else OTHER_VALUE_FLAGS)
        if exe == "pnpm":
            flags = flags - {"-w"}  # pnpm's `-w` is `--workspace-root`, a switch: `pnpm add -Dw ws` names ws
        named = _named(after, flags)
        if exe == "npm" and not named and _npm_workspace_value_is_package(after):
            named = [after[-1]]
        for arg in named:
            if _is_local_path(arg):
                continue
            name = _package_name(arg)
            if name and name.lower() not in INSTALLER_SELF:
                found.append((exe, name))
    return found


# --- what a dependency manifest declares ----------------------------------------------------------------------
# `requirements.txt`, `requirements-dev.in`, and since the second review of 30.09 a name with the word anywhere (`dev-requirements.txt`,
# `test_requirements.txt`): pip reads any of them with `-r` (review 30.09)
MANIFEST_FILE = re.compile(r"^(?:[\w.\-]*requirements[\w.\-]*\.(?:txt|in)|pyproject\.toml|package\.json|cargo\.toml|go\.mod|"
                           r"gemfile|composer\.json|pipfile)$", re.I)
PACKAGE_JSON_DEPENDENCIES = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "require",
                             "require-dev")
MANIFEST_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist", "build", "target", "vendor"}


def _is_manifest(path: str) -> bool:
    parts = str(path or "").replace("\\", "/").rstrip("/").split("/")
    return bool(MANIFEST_FILE.match(parts[-1][-255:])) or (len(parts) > 1 and parts[-2].lower() == "requirements"
                                                     and parts[-1].lower().endswith((".txt", ".in")))


def _toml_names(text: str) -> set[str]:
    """Package names a pyproject.toml, Pipfile or Cargo.toml declares — read line by line, because the hook runs on
    Python 3.9 and `tomllib` arrived in 3.11. Arrays (`dependencies = ["stripe>=5"]`) and tables
    (`[tool.poetry.dependencies]`, `[dependencies]`, `[packages]`) are both read."""
    names: set[str] = set()
    section = ""
    in_array = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if in_array:
            names |= {_package_name(s) for s in re.findall(r"[\"']([^\"']+)[\"']", line.split(" #", 1)[0])}
            in_array = "]" not in line
            continue
        if line.startswith("["):
            section = line.strip("[] ").lower()
            continue
        m = re.match(r"^([A-Za-z0-9_.\-\"']+)\s*=\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1).strip("\"'"), m.group(2).strip()
        dep_section = ("dependencies" in section or "dependency-groups" in section
                       or section in ("packages", "dev-packages"))
        if value.startswith("[") and (dep_section or key.lower() in ("dependencies", "requires", "dev-dependencies")):
            names |= {_package_name(s) for s in re.findall(r"[\"']([^\"']+)[\"']", value.split(" #", 1)[0])}
            in_array = "]" not in value
        elif dep_section and key.lower() != "python" and not value.startswith("["):
            names.add(key)
    return {n for n in names if n}


def declared_names(text: str, filename: str) -> set[str]:
    """What one manifest declares, as `_pep503` names."""
    base = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    names: set[str] = set()
    if base in ("package.json", "composer.json"):
        try:
            data = json.loads(text or "{}")
        except Exception:
            data = {}
        for key in PACKAGE_JSON_DEPENDENCIES:
            if isinstance(data, dict) and isinstance(data.get(key), dict):
                names |= set(data[key])
    elif base in ("pyproject.toml", "pipfile", "cargo.toml"):
        names = _toml_names(text)
    elif base == "go.mod":
        names = set(re.findall(r"^\s*(?:require\s+)?([\w\-]*(?:\.[\w\-]*)+/\S+)\s+v\d", str(text or ""), re.M))
    elif base == "gemfile":
        names = set(re.findall(r"^\s*gem\s+[\"']([^\"']+)[\"']", str(text or ""), re.M))
    else:  # requirements*.txt / *.in
        for raw in str(text or "").splitlines():
            line = raw.split(" #", 1)[0].strip()
            # a line continued with a backslash (pip-compile's `resend==2.0.0 \` before its `--hash=` lines) is the
            # requirement without it: the backslash made it a Windows path and hid it (review 30.09)
            line = line[:-1].rstrip() if line.endswith("\\") else line
            egg = re.search(r"[#&]egg=([A-Za-z0-9][\w.\-]*)", raw)
            if egg and line.startswith("-"):  # `-e git+https://…#egg=resend`
                names.add(egg.group(1))
            elif line and not line.startswith(("#", "-")) and not _is_local_path(line):
                names.add(_package_name(line))
    return {_pep503(n) for n in names if n}


def project_declared_packages(root: Path) -> set[str]:
    """Everything the project's manifests already declare, at the root and one folder down (`frontend/package.json`,
    `requirements/dev.txt`). `pip install pytest` after an ImportError, for a package requirements.txt names, is
    not a change of the stack (audit 2026-09-23)."""
    found: set[str] = set()
    try:
        files = [p for p in root.iterdir() if p.is_file() and _is_manifest(p.name)]
        for d in root.iterdir():
            if d.is_dir() and not d.name.startswith(".") and d.name.lower() not in MANIFEST_SKIP_DIRS:
                files += [p for p in d.iterdir() if p.is_file() and _is_manifest(f"{d.name}/{p.name}")]
    except Exception:
        files = []
    for p in files[:60]:
        try:
            with p.open(encoding="utf-8", errors="replace") as fh:  # the head only: never the whole of a huge file
                found |= declared_names(fh.read(400_000), p.name)
        except Exception:
            continue
    return found


def manifest_additions(tool_name: str, tool_input: dict) -> list[str]:
    """The packages a Write or an Edit adds to a dependency manifest: requirements*.txt, pyproject.toml,
    package.json, Pipfile, Cargo.toml, go.mod, Gemfile, composer.json. Adding `stripe` to package.json and then
    running `npm install` added a dependency with no event at all (audit 2026-09-23): the install of a declared
    manifest is rightly not held, so the declaration is where the stack changes. An Edit is applied to the file as it
    is on disk; an edit that would not apply is left to the client, which refuses it anyway."""
    tool_input = tool_input or {}
    if is_command(tool_name, tool_input) or is_read_only_tool(tool_name, tool_input):
        return []
    _text, path = text_of_tool_input(tool_name, tool_input)
    if not path or not _is_manifest(path):
        return []
    target = Path(path) if os.path.isabs(path) else project_root() / path
    # a manifest past PACKAGE_READ_MAX is not read: every name the change writes is then held as new (fail closed)
    on_disk, _why = _read_for_packages(target)
    readable, old = on_disk is not None, on_disk or ""
    content = next((tool_input[k] for k in ("content", "contents") if isinstance(tool_input.get(k), str)), None)
    if content is not None:
        new = content
    else:
        edits: list[tuple[str, str, bool]] = []
        for e in [tool_input] + [x for x in (tool_input.get("edits") or []) if isinstance(x, dict)]:
            o = next((e[k] for k in ("old_string", "old_str", "oldText", "old_text") if isinstance(e.get(k), str)), None)
            n = next((e[k] for k in EDIT_BODY_KEYS if isinstance(e.get(k), str)), None)
            if o is not None and n is not None:
                edits.append((o, n, bool(e.get("replace_all"))))
        if not edits:
            return []
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        new = old
        for k, (o, n, every) in enumerate(edits):
            if not o and not new:
                new = n
                continue
            if not o or o not in new:
                if readable:
                    return []  # an edit that would not apply to the file: the client refuses it anyway
                # the file is not there to read (review 30.09): what the new text declares line by line and the old
                # text did not is held, and every later edit is read the same way
                added = set(declared_names(new, name) - declared_names(old, name))
                for o2, n2, _every in edits[k:]:
                    added |= _declared_by_lines(n2, name) - _declared_by_lines(o2, name)
                return sorted(added)
            new = new.replace(o, n) if every else new.replace(o, n, 1)
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return sorted(declared_names(new, name) - declared_names(old, name))


# the keys of package.json / composer.json a line can hold that are not a dependency: a line read without its object
# (`_declared_by_lines`) cannot see which object it is in
MANIFEST_METADATA_KEYS = frozenset({"name", "version", "description", "main", "module", "types", "typings", "license",
                                    "private", "type", "author", "homepage", "packagemanager", "browser", "bin", "files",
                                    "keywords", "repository", "bugs", "url", "email", "sideeffects", "funding", "node",
                                    "npm", "pnpm", "yarn", "php", "minimum-stability", "prefer-stable", "directory"})


def _declared_by_lines(text: str, filename: str) -> set[str]:
    """What the lines of a manifest fragment declare, read one by one (`manifest_line_uses`) — for an edit whose file
    cannot be read — as `_pep503` names; a package.json key that is the manifest's own metadata is not one."""
    if _base_name(filename) in ("package.json", "composer.json"):  # a key whose value is a version or a source
        names = set(re.findall(r"\"([^\"\\\n]{1,214})\"\s*:\s*\"(?:[\^~<>=*\d][^\"]*|(?:latest|next|beta|canary)|"
                               r"(?:workspace:|npm:|file:|link:|git|https?:|github:|dev-)[^\"\s]*)\"", str(text or "")))
    else:
        names = {n for line in str(text or "").split("\n") for _reading, n in manifest_line_uses(line, filename)}
    return {_pep503(n) for n in names if n and str(n).lower() not in MANIFEST_METADATA_KEYS}


def stack_packages(cfg: dict) -> set[str]:
    """Package names the founder's approved stack already names, spelled exactly (`_pep503`): `FastAPI` is fastapi,
    `Next.js` is next, `Tailwind CSS` is tailwindcss or tailwind-css, plus the technology names in the pack's stored
    vocabulary. Not the idea's other words and not a hyphen-stripped form: `fast-api` is another PyPI project than
    `fastapi`, and `pip install <any idea word>` passed silently while the message claimed the stack was checked
    (audit 2026-09-23)."""
    names: set[str] = set()
    stack = str((cfg or {}).get("stack") or "").lower()
    for item in re.split(r"[,;()\n+]|\band\b|\bwith\b|\bплюс\b", stack):
        words = re.findall(r"[a-z0-9@][a-z0-9._@/\-]*", item)
        for w in words:
            w = w.rstrip(".")
            names |= {w, re.sub(r"\.?js$", "", w) if w.endswith("js") and len(w) > 3 else w}
        for a, b in zip(words, words[1:]):
            names |= {a + b, f"{a}-{b}"}
    vocabulary = {str(w).lower() for w in (cfg or {}).get("vocabulary") or []}
    names |= vocabulary & TECHNOLOGY_WORDS
    return {_pep503(n) for n in names if n}


def _git_subcommand(args: list[str]) -> tuple[str, list[str], list[str]]:
    """(subcommand, what follows it, the `-c key=value` settings) for `git [-C dir] [-c k=v] <sub> ...`."""
    i = 0
    settings: list[str] = []
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-c" and i + 1 < len(args):
            settings.append(args[i + 1])
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env") else 1
    return ((args[i].lower(), args[i + 1:]) if i < len(args) else ("", [])) + (settings,)


def _git_config_key(args_after_config: list[str]) -> str:
    positional: list[str] = []
    skip = False
    for a in args_after_config:
        if skip:
            skip = False
            continue
        if a.startswith("-"):
            skip = a.lower() in GIT_CONFIG_VALUE_FLAGS
            continue
        positional.append(a)
    if positional[:1] and positional[0].lower() in ("set", "unset"):
        positional = positional[1:]
    return positional[0] if positional else ""


def _remote_spec(token: str) -> bool:
    """`host:path`, `user@host:path`, `rsync://host/…` — and not `C:\\x` or `C:/x`."""
    t = str(token or "")
    if t.startswith("rsync://"):
        return True
    return bool(re.match(r"^[^\s/\\:]+:", t)) and not re.match(r"^[A-Za-z]:(?:[\\/]|$)", t)


def outbound_actions(command: str) -> list[str]:
    """What in a shell command leaves the machine or rewrites a remote: `git push`, `gh repo delete`, `npm publish`,
    `docker push`, a deploy, an upload. Named the way the log will show them."""
    found: list[str] = []
    for tokens in _command_words(command):
        exe = _exe_name(tokens[0])
        if re.match(r"^(?:python|py)(?:\d+(?:\.\d+)?)?$", exe) and "-m" in tokens[1:]:
            i = tokens.index("-m")
            if i + 1 >= len(tokens):
                continue
            tokens = tokens[i + 1:]  # `python -m twine upload` is twine
            exe = _exe_name(tokens[0])
        words = [a.lower() for a in tokens[1:] if not a.startswith("-")]
        flags = [a.lower() for a in tokens[1:] if a.startswith("-")]
        hit = ""
        if exe == "git":
            sub, after, settings = _git_subcommand(tokens[1:])
            rest = [a.lower() for a in after if not a.startswith("-")]
            redirect = next((s.split("=", 1)[0] for s in settings if GIT_REDIRECT_KEY.match(s.split("=", 1)[0])), "")
            if redirect:
                hit = f"git -c {redirect}"
            elif sub == "push" and not any(a in ("-n", "--dry-run") for a in after):
                hit = "git push"
            elif sub == "remote" and rest[:1] and rest[0] in ("add", "set-url"):
                hit = f"git remote {rest[0]}"
            elif sub == "config" and git_config_writes(after) and GIT_REDIRECT_KEY.match(_git_config_key(after)):
                hit = f"git config {_git_config_key(after)}"
            elif sub == "send-pack":
                hit = "git send-pack"
            elif sub == "subtree" and rest[:1] == ["push"]:
                hit = "git subtree push"
            elif sub == "svn" and rest[:1] == ["dcommit"]:
                hit = "git svn dcommit"
        elif exe == "gh":
            if words[:1] == ["api"]:
                method = ""
                for i, a in enumerate(tokens):
                    if a in ("-X", "--method") and i + 1 < len(tokens):
                        method = tokens[i + 1].upper()
                    elif a.startswith("--method="):
                        method = a.split("=", 1)[1].upper()
                    elif a.startswith("-X") and len(a) > 2:
                        method = a[2:].upper()
                if not method and any(a in ("-f", "-F", "--field", "--raw-field", "--input")
                                      or a.startswith(("--field=", "--raw-field=", "--input=")) for a in tokens):
                    method = "POST"  # gh api sends a POST as soon as a field is given
                if method and method != "GET":
                    hit = f"gh api {method}"
            elif tuple(words[:2]) in GH_OUTBOUND:
                hit = f"gh {words[0]} {words[1]}"
            elif words and words[0] not in GH_COMMANDS:
                hit = f"gh {words[0]} (an alias or extension the guard cannot read)"
        elif exe in ("npm", "pnpm", "yarn") and words[:1] == ["publish"]:
            hit = f"{exe} publish"
        elif exe == "yarn" and words[:2] == ["npm", "publish"]:
            hit = "yarn npm publish"
        elif exe == "docker" and (words[:2] == ["image", "push"]):
            hit = "docker push"
        elif exe == "docker" and (words[:1] == ["build"] or words[:2] in (["buildx", "build"], ["buildx", "bake"])) and (
                "--push" in flags or any("type=registry" in a for a in flags)):
            hit = "docker build --push"
        elif exe == "dotnet" and words[:2] == ["nuget", "push"]:
            hit = "dotnet nuget push"
        elif exe == "aws" and words[:1] == ["s3"] and words[1:2] and (
                words[1] in ("rm", "rb") or (words[1] in ("cp", "sync", "mv") and words[-1:] and words[-1].startswith("s3://"))):
            hit = f"aws s3 {words[1]}"
        elif exe in ("aws", "gcloud", "az") and "deploy" in words:
            hit = f"{exe} … deploy"
        elif exe == "supabase" and (words[:2] == ["db", "push"] or "deploy" in words[:2]):
            hit = f"supabase {' '.join(words[:2])}"
        elif exe in ("scp", "rsync"):
            positional = [a for a in tokens[1:] if not a.startswith("-")]
            if positional and _remote_spec(positional[-1]):
                hit = f"{exe} to a remote host"
        elif exe == "curl" and any(a in ("-T", "--upload-file") or a.startswith("--upload-file=") for a in tokens[1:]):
            hit = "curl --upload-file"
        elif exe == "surge":
            hit = "surge"  # surge publishes whatever folder it is given
        elif (exe, words[0] if words else "") in OUTBOUND_VERBS:
            hit = f"{exe} {words[0]}" if words else exe
        elif exe == "vercel" and not words:
            hit = "vercel"  # a bare `vercel` deploys
        if hit and hit not in found:
            found.append(hit)
    return found


def _home() -> str:
    try:
        home = os.path.expanduser("~")
        return "" if home == "~" else home
    except Exception:
        return ""


def _within(path: str, base: str) -> bool:
    try:
        p = os.path.normcase(os.path.realpath(path))
        b = os.path.normcase(os.path.realpath(base))
        return os.path.commonpath([p, b]) == b
    except Exception:
        return False  # another drive on Windows, or a path the OS cannot read


def _allowed_outside() -> list[str]:
    """Where a write outside the project is not the founder's question: the system temp folder, the guard's own
    folder in the home directory (its baseline; a write there is a tamper refusal anyway), the agents' state folders."""
    bases: list[str] = []
    try:
        import tempfile

        bases.append(tempfile.gettempdir())
    except Exception:
        pass
    try:
        bases.append(str(baseline_home().parent))
    except Exception:
        pass
    home = _home()
    if home:
        bases += [os.path.join(home, ".lumis")] + [os.path.join(home, *d.split("/")) for d in AGENT_STATE_DIRS]
    return bases


def _resolve_target(raw: str, cwd: Path | None) -> str:
    """The absolute path a written-to token names, or "" when it cannot be read (a variable, a flag, a relative path
    after a `cd` the hook could not follow)."""
    t = str(raw or "").strip().strip("'\"`")
    if not t or t.startswith(("-", "&")) or len(t) > 1024:
        return ""
    home = _home()
    if home:
        t = re.sub(r"^(?:~|\$\{?HOME\}?|\$env:USERPROFILE|%USERPROFILE%)(?=$|[/\\])", lambda _m: home, t, flags=re.I)
    if "$" in t or "%" in t or t.startswith("~"):
        return ""
    if os.name == "nt":
        t = re.sub(r"^/([A-Za-z])(?=/|$)", r"\1:", t)  # Git Bash spells C:\x as /c/x
    if os.path.isabs(t) or t.startswith(("/", "\\")):
        return os.path.abspath(t)
    return os.path.abspath(str(cwd / t)) if cwd is not None else ""


def _outside_root(raw: str, cwd: Path | None) -> bool:
    low = str(raw or "").strip().strip("'\"`").replace("\\", "/").lower()
    if low.startswith("/"):
        # `..` is resolved before the scratch-place test: `/tmp/../Users/x/evil.py` is /Users/x/evil.py, and the raw
        # string starting with /tmp/ let it through (audit 2026-09-23)
        import posixpath

        low = posixpath.normpath(low)
    if low in ("nul", "con", "/dev/null") or low.startswith("/dev/"):
        return False
    target = _resolve_target(raw, cwd)
    if not target or _within(target, str(project_root())):
        return False
    if any(_within(target, base) for base in _allowed_outside()):
        return False
    home = _home()
    if home and _within(target, home):
        # an agent's own configuration under the home folder is the founder's question even when the home folder
        # itself sits under /tmp (a CI runner, a container): the scratch-place allowance below must not reach it
        return True
    if low.startswith(("/tmp/", "/var/tmp/", "/private/tmp/")) or low in ("/tmp", "/var/tmp"):
        return False  # the POSIX scratch places, whatever the OS maps them to
    return True


REDIRECT_TOKEN = re.compile(r"^(?:\d|&)?(?:>\||>>?)(.*)$")  # `>|` first: it is noclobber's redirect, not `>` then a pipe


def _redirect_targets(tokens: list[str]) -> list[str]:
    """Where `>`, `>>`, `>|`, `2>`, `&>` send output, read word by word after the quotes are off: `> "a b/x.txt"` is
    one path. `2>&1`, `>&2` and `>(…)` are not files."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        m = REDIRECT_TOKEN.match(t)
        if m:
            rest = m.group(1)
            if rest and not rest.startswith(("&", "(")):
                out.append(rest)
            elif not rest and i + 1 < len(tokens):
                out.append(tokens[i + 1])
                i += 1
        elif ">" in t and not re.search(r"\s", t) and not t.startswith(("-", "=")):
            glued = re.match(r"^(.*?[^=\-<>\d])\d?(?:>\||>>?)(?![&(])(.+)$", t)  # `echo hi>out.txt`
            if glued:
                out.append(glued.group(2))
        i += 1
    return out


def _flag_value(args: list[str], names: tuple[str, ...]) -> list[str]:
    """Values of the given flags, spelled `-o x`, `--output x`, `--output=x` (and `-ox` for a one-letter flag)."""
    out: list[str] = []
    for i, a in enumerate(args):
        for n in names:
            # a one-letter flag is case-sensitive (`tar -C` is not `-c`); a PowerShell parameter is not (`-Path`)
            same = a == n if len(n) == 2 else a.lower() == n.lower()
            if same and i + 1 < len(args):
                out.append(args[i + 1])
            elif n.startswith("--") and a.lower().startswith(n + "="):
                out.append(a.split("=", 1)[1])
            elif len(n) == 2 and a.startswith(n) and len(a) > 2 and not a.startswith("--"):
                out.append(a[2:])
    return out


def _positional(args: list[str], value_flags: set[str], exe: str = "") -> list[str]:
    """Positional arguments, skipping flags, their values and a cmd switch (`/q`, `/s`)."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a.startswith("-") and a != "-":
            skip = a.lower() in value_flags
            continue
        if re.match(r"^/[A-Za-z]$", a) or (exe in CMD_VERBS and CMD_SWITCH.match(a)):
            continue
        out.append(a)
    return out


def _writes_of(exe: str, args: list[str]) -> list[str]:
    """The paths one command writes, removes or creates (not counting redirects)."""
    low = [a.lower() for a in args]
    if exe == "tee":
        return [a for a in args if not a.startswith("-")]
    if exe in COPY_MOVE:
        dest = next(iter(_flag_value(args, ("-destination", "-t", "--target-directory"))), "")
        if dest:
            return [dest]
        positional = [a for a in args if not a.startswith("-") and not (exe in CMD_VERBS and CMD_SWITCH.match(a))]
        if exe == "robocopy" and len(positional) >= 2:
            return [positional[1]]
        written = positional[-1:] if len(positional) >= 2 else []
        if exe in ("mv", "move", "move-item", "mi"):
            written += positional[:-1]  # a move also removes its sources
        return written
    if exe in PATH_WRITERS:
        paths = _flag_value(args, tuple(PS_PATH_FLAGS))
        value_flags = PATH_WRITER_VALUE_FLAGS.get(exe, set()) | PS_ITEM_FLAGS | PS_PATH_FLAGS
        return paths + [a for a in _positional(args, value_flags, exe) if a not in paths]
    if exe in PS_WRITERS:
        paths = _flag_value(args, tuple(PS_PATH_FLAGS))
        return paths or _positional(args, PS_VALUE_FLAGS | PS_PATH_FLAGS)[:1]
    if exe in ("sed", "perl"):
        in_place = any(a.startswith("-i") or a == "--in-place" or a.startswith("--in-place=")
                       or (exe == "perl" and re.match(r"^-[a-z]*i", a)) or (exe == "sed" and re.match(r"^-[a-zA-Z]*i", a))
                       for a in args if a.startswith("-") and not a.startswith("--expression"))
        if not in_place:
            return []
        scripted = any(a in ("-e", "-f", "--expression", "--file") or a.startswith(("--expression=", "--file="))
                       or (exe == "perl" and re.match(r"^-[a-z]*e$", a)) for a in low)
        positional = _positional(args, {"-e", "-f", "--expression", "--file", "-l", "--line-length"}
                                 | ({a for a in args if exe == "perl" and re.match(r"^-[a-z]*e$", a.lower())}))
        return positional if (scripted or exe == "perl") else positional[1:]
    if exe == "curl":
        return _flag_value(args, ("-o", "--output", "--output-dir"))
    if exe == "wget":
        return _flag_value(args, ("-O", "--output-document", "-P", "--directory-prefix"))
    if exe == "git":
        words = [a for a in args if not a.startswith("-")]
        if words[:1] and words[0].lower() == "clone":
            positional = _positional(args[args.index(words[0]) + 1:], {"-b", "--branch", "--depth", "-o", "--origin",
                                                                      "--reference", "-c", "--config", "--template",
                                                                      "--separate-git-dir", "-j", "--jobs", "-u"})
            return positional[1:2]
        output = reader_output_file("git", args)
        return [output] if output else []
    if exe in ("sort", "uniq", "tree"):
        output = reader_output_file(exe, args)
        return [output] if output else []
    if exe == "tar":
        first = args[0] if args else ""
        cluster = "".join(a.lstrip("-") for a in args if re.match(r"^-?[A-Za-z]+$", a) and not a.startswith("--")
                          and (a.startswith("-") or a is first))
        creates = any(c in cluster for c in "cru") or any(a in ("--create", "--append", "--update") for a in low)
        extracts = "x" in cluster or any(a in ("--extract", "--get") for a in low)
        out: list[str] = []
        if creates:
            out += _flag_value(args, ("--file",))
            for i, a in enumerate(args):
                if re.match(r"^-?[A-Za-z]+$", a) and "f" in a and not a.startswith("--") and (a.startswith("-") or a is first) \
                        and i + 1 < len(args):
                    out.append(args[i + 1])
                    break
        if extracts:
            out += _flag_value(args, ("-C", "--directory"))
        return out
    if exe == "unzip":
        return _flag_value(args, ("-d",))
    if exe == "7z":
        return [a[2:] for a in args if a.startswith("-o") and len(a) > 2]
    if exe == "dd":
        return [a.split("=", 1)[1] for a in args if a.lower().startswith("of=")]
    if exe in ("install", "ln"):
        positional = _positional(args, {"-m", "--mode", "-o", "--owner", "-g", "--group", "-t", "--target-directory", "-S", "--suffix"})
        targets = _flag_value(args, ("-t", "--target-directory"))
        if exe == "install" and "-d" in low:
            return targets + positional
        return targets or (positional[-1:] if len(positional) >= 2 else [])
    if exe in ("rsync", "scp"):
        positional = _positional(args, {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "-i", "-p", "-P",
                                        "-o", "-F", "-l", "-c", "--password-file"} if exe == "scp" else
                                 {"-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--password-file"})
        dest = positional[-1] if len(positional) >= 2 else ""
        return [dest] if dest and not _remote_spec(dest) else []  # a remote destination is the outbound class
    return []


def _command_write_targets(command: str) -> list[tuple[str, Path | None]]:
    """(token, directory it is relative to) for every place a shell line writes a file: a redirect, `tee`, a copy or
    a move, and what removes, creates, edits in place, downloads or unpacks (`rm`, `mkdir`, `touch`, `sed -i`,
    `Set-Content`, `curl -o`, `git clone … <dest>`, `tar -C`, `dd of=`). `cd` is followed while the hook can read where
    it goes. Not seen: a path an interpreter opens (`python -c "open('../x', 'w')"`)."""
    root = project_root()
    cwd: Path | None = root
    out: list[tuple[str, Path | None]] = []
    for tokens in _command_words(command):
        scan_checkpoint()
        exe = _exe_name(tokens[0])
        if exe in ("cd", "set-location", "sl", "pushd", "chdir"):
            nxt = [a for a in tokens[1:] if not a.startswith("-")]
            if len(nxt) > 1 and nxt[0].lower() == "/d":
                nxt = nxt[1:]  # cmd's `cd /d <dir>`: the switch, not the D: drive
            where = _resolve_target(nxt[0], cwd) if nxt else ""
            cwd = Path(where) if where else None
            continue
        out += [(t, cwd) for t in _redirect_targets(tokens)]
        # the redirects are not arguments of the command itself
        args: list[str] = []
        skip = False
        for t in tokens[1:]:
            if skip:
                skip = False
                continue
            m = REDIRECT_TOKEN.match(t)
            if m:
                skip = not m.group(1)
                continue
            args.append(t)
        out += [(t, cwd) for t in _writes_of(exe, args) if t and t != "-"]
    return out


def outside_root_writes(tool_name: str, tool_input: dict) -> list[str]:
    """The paths outside the project a tool call writes to, as the agent spelled them."""
    tool_input = tool_input or {}
    if is_read_only_tool(tool_name, tool_input):
        return []
    if is_command(tool_name, tool_input):
        found: list[str] = []
        for token, cwd in _command_write_targets(_command_without_data(str(tool_input.get("command", "")), files_too=True)):
            scan_checkpoint()  # each target is resolved on disk: under the clock, like the tamper check's probes
            if _outside_root(token, cwd) and token not in found:
                found.append(token)
        return found
    _text, path = text_of_tool_input(tool_name, tool_input)
    writes = (any(tool_input.get(k) for k in BODY_KEYS) or tool_input.get("edits")
              or any(w in WRITE_TOOL_WORDS for w in tool_words(tool_name)))
    targets = ([path] if (path and writes) else []) + destination_paths(tool_name, tool_input)
    return [p for p in dict.fromkeys(targets) if _outside_root(p, project_root())]


def check_classes(cfg: dict, tool_name: str, tool_input: dict) -> list[tuple[str, str]]:
    """(class, what) for every boundary class a tool call touches: ("dependency", "stripe"), ("outbound", "git push"),
    ("outside_root", "C:/elsewhere/x.py"). The verdict (allow | ask | block) is the caller's, from `class_verdict`."""
    tool_input = tool_input or {}
    if is_read_only_tool(tool_name, tool_input):
        return []
    hits: list[tuple[str, str]] = []
    outbound: list[str] = []
    if is_command(tool_name, tool_input):
        command = str(tool_input.get("command", ""))
        if is_read_only_command(command) or _only_guard_self_run(command):
            return []
        # what a command writes into a file (a Dockerfile, a workflow, notes.txt) is file content, judged like the same
        # content written with the Write tool — not a command this call runs
        text = _command_without_data(command, files_too=True)
        installs = _installs(text)  # what `dependency_additions` reads, with the manager that reads each name
        candidates = list(dict.fromkeys(name for _manager, name in installs))
        readings: dict[str, str] = {}
        for manager, name in installs:
            readings.setdefault(name, MANAGER_READINGS.get(manager, "exact"))
        outbound = outbound_actions(text)
    else:
        candidates = manifest_additions(tool_name, tool_input)
        reading = _manifest_reading(text_of_tool_input(tool_name, tool_input)[1])
        readings = {name: reading for name in candidates}
    if candidates:
        # what the approved stack names, and what the project's manifests already declare, is not a new dependency;
        # a package the Non-Goals forbid was refused before this check ran (read as that manager reads it: a family
        # is npm's only, so `pip install expo-helpers` is held here)
        known = stack_packages(cfg) | project_declared_packages(project_root())
        denied = {_pep503(p) for p in cfg.get("deny_packages") or []}
        for pkg in candidates:
            if (_pep503(pkg) in denied or _pep503(pkg) in known
                    or forbidden_package(cfg, pkg, readings.get(pkg, "exact"))):
                continue
            hits.append(("dependency", pkg))
    hits += [("outbound", act) for act in outbound]
    hits += [("outside_root", p) for p in outside_root_writes(tool_name, tool_input)]
    return list(dict.fromkeys(hits))


CLASS_REASONS = {
    "dependency": lambda what: (f"dependency '{what}' — adding a dependency is a change of the stack, not a side effect: {what} is "
                                "not in ARCHITECTURE.md's stack — confirm it with the founder (Feature Delta) or add it to the architecture first"),
    "outbound": lambda what: f"outbound '{what}' — this leaves the machine or rewrites a remote — irreversible; the founder decides",
    "outside_root": lambda what: (f"outside_root '{what}' — this writes outside the project ({project_root()}): a change there is not "
                                  "part of this project's scope — the founder decides"),
}


# how a class hit reads in the log: "dependency 'stripe'", "outbound 'git push'", "outside_root '<path>'"
CLASS_HIT = re.compile(r"^(?:dependency|outbound|outside_root)\s+'")


def class_message(active: list[tuple[str, str]], blocking: bool, skips: list[str] | tuple = ()) -> str:
    """The refusal or the question for the class hits of one call, and the pre-commit skips held with them
    (`pre_commit_skips`): those are not a class — `classes` does not set them, they are always asked."""
    head = ("⛔ LUMIS Scope Guard blocked this (.lumis/scope_guard.json → \"classes\"): " if blocking else
            "⏸ LUMIS Scope Guard holds this for the founder: ")
    reasons = [CLASS_REASONS[c](w) for c, w in active] + [pre_commit_skip_reason(s) for s in skips]
    tail = (". Each class is set in .lumis/scope_guard.json → \"classes\" (allow | ask | block); the agent never changes it."
            if active else ". The founder approves it once, or the commit goes through the check.")
    return head + "; ".join(reasons) + tail


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
    # only a head far longer than what is kept is read: a 2.8 MB Write was redacted whole to keep 160 characters
    out = " ".join(str(text or "")[:limit * 20 + 20_000].split())
    for pattern, replacement in SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out[:limit] + ("…" if len(out) > limit else "")


def log_event(cfg: dict, event: str, tool_name: str, tool_input: dict, hits: list[str], agent: str = "", attempted: str = "",
              observed: bool = False) -> None:
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
        "attempted": redact(attempted or (tool_input or {}).get("command", ""), limit=600 if event in ("blocked", "tamper", "held", "timeout") else 160),
        "hits": [h[:300] for h in hits if str(h).strip()][:8],
    }
    if observed:
        # observe mode: the event the guard WOULD have produced, under its own name, marked as not enforced
        entry["observed"] = True
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
    return f"hook {HOOK_VERSION} · hook {hook} · config {config}"


HOOK_VERSION_RE = re.compile(r'^HOOK_VERSION\s*=\s*["\']([^"\']+)["\']', re.M)


def script_version(path: Path) -> str:
    """HOOK_VERSION of the hook script at `path`, read as text (never imported); "" for a script written before
    versions existed, or one that cannot be read."""
    try:
        m = HOOK_VERSION_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else ""
    except Exception:
        return ""


def write_request(reason: str) -> int:
    """`scope_guard.py request --reason "…"`: the last refusal, written into .lumis/requests/<ts>-<slug>.md with the
    exact payload the guard recorded, the boundary it named, and the agent's reason — a file, so it survives the
    agent's context being compacted, and paste-ready for LUMIS Amend. The founder's agent wrote such a file by hand,
    twice, because the first copy had drifted from the file by the time a decision came (field report 2026-09-22)."""
    root = project_root()
    # a `held` call (a dependency, a push, a write outside the project) is a request by nature; an observed event
    # stopped nothing, so there is no refusal to ask about
    events = [e for e in read_log({"log": ".lumis/guard.log"})
              if e.get("event") in ("blocked", "tamper", "held", "timeout") and not e.get("observed")]
    if not events:
        print("no refusal on record: nothing to request")
        return 1
    last = events[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", (reason or "request").lower()).strip("-")[:40] or "request"
    stamp = re.sub(r"[^0-9T]", "", str(last.get("ts", ""))[:19]) or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = root / ".lumis" / "requests" / f"{stamp}-{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    hits = last.get("hits") or []
    # a class set to "block" logs `blocked` with class hits and no NG-n: it is a class decision, not a Non-Goal and not
    # the guard's own files (review 2026-09-23 — the request called it both)
    by_class = any(CLASS_HIT.match(str(h)) for h in hits)
    kind = {"tamper": "the guard's own files", "held": "a boundary class held for you"}.get(
        str(last.get("event")), "a boundary class set to block" if by_class else "a Non-Goal")
    amend_lines = [f"- Consider lifting or narrowing the boundary behind: {h}" for h in hits if "NG-" in str(h)] or (
        ["- A dependency, a push or a write outside the project waits for your decision: approve it once, or set the class "
         "in .lumis/scope_guard.json → \"classes\" (allow | ask | block)."] if (last.get("event") == "held" or by_class) else
        ["- The refusal concerned the guard's own files: if the change was meant, run Amend or edit the boundary yourself; the agent must not."])
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


def request_lines(root: Path, limit: int = 10) -> list[str] | None:
    """`<filename> · <first line of the reason>` for the newest request files in .lumis/requests; None when the folder
    does not exist. The reason is the first line under «## Why the agent asks» (what `request` writes), or else the
    first non-empty line after the file's heading — a request written by hand is listed too."""
    folder = root / ".lumis" / "requests"
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    out = [f"requests (.lumis/requests): {len(files)}"]
    for p in files[:limit]:
        try:
            lines = [l.strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        except Exception:
            lines = []
        reason = ""
        if "## Why the agent asks" in lines:
            reason = next((l for l in lines[lines.index("## Why the agent asks") + 1:] if l), "")
        if not reason:
            start = next((i + 1 for i, l in enumerate(lines) if l.startswith("#")), 0)
            reason = next((l for l in lines[start:] if l and not l.startswith("#")), "")
        reason = reason[:140] + ("…" if len(reason) > 140 else "")
        out.append(f"  {p.name} · {reason or '(empty)'}")
    return out


def report(cfg: dict) -> int:
    entries = read_log(cfg)
    counts = {"blocked": 0, "warned": 0, "possible": 0, "drift": 0, "tamper": 0, "timeout": 0}
    observed = 0
    for e in entries:
        if e.get("observed"):
            observed += 1  # would have been stopped; it was not, so it is not counted as stopped
            continue
        counts[e.get("event", "")] = counts.get(e.get("event", ""), 0) + 1
    agents = sorted({str(e.get("agent") or "unknown") for e in entries})
    stopped = counts.get("blocked", 0) + counts.get("tamper", 0) + counts.get("timeout", 0)
    print(f"LUMIS Scope Guard — {len(entries)} events in {cfg.get('log', '.lumis/guard.log')} · {fingerprints()}")
    # «blocked: 0» beside eighteen tamper refusals read as «the guard never stepped in» (field report 2026-09-22);
    # every kind is printed even at zero, so a missing word never has to be read as «not counted»
    print(f"  stopped: {stopped} (blocked: {counts.get('blocked', 0)} · tamper: {counts.get('tamper', 0)})"
          f" · timeout (refused, not read in time): {counts.get('timeout', 0)}"
          f" · held: {counts.get('held', 0)} · asked: {counts.get('asked', 0)} · inspected: {counts.get('inspected', 0)}"
          f" · warned: {counts.get('warned', 0)} · possible: {counts.get('possible', 0)} · noted: {counts.get('noted', 0)}"
          f" · drift prompts: {counts.get('drift', 0)}"
          + (f" · agents: {', '.join(agents)}" if entries else ""))
    if guard_mode(cfg) == "observe" or observed:
        print(f"  mode: {guard_mode(cfg)} — {observed} event(s) would have been stopped"
              + (" (observe mode records them and stops nothing but changes to the guard itself)" if guard_mode(cfg) == "observe" else ""))
    if counts.get("held"):
        print("  ('held' is a new dependency, a push or deploy, or a write outside the project, handed to you to approve —")
        print("   `classes` in .lumis/scope_guard.json sets each to allow, ask or block; a commit that skips the LUMIS")
        print("   pre-commit check is always asked. A decision, not a violation.)")
    if counts.get("possible"):
        print("  ('possible' is a single word out of a long Non-Goal sentence that turned up in a change: a match for you")
        print("   to judge, not a violation. Nothing was blocked; the word alone does not prove the boundary was crossed.)")
    if counts.get("inspected"):
        print("  ('inspected' is a read-only command — grep, git log, ls, an MCP read tool — that merely mentions a boundary: allowed, never a violation.)")
    if counts.get("noted"):
        print("  ('noted' is a document or a test that writes a boundary down — docs/, *.md, tests/: allowed, never a violation.)")
    # an observed block did reach a tool, and the hook would have refused it: the legend would be false then
    if counts.get("asked") and not counts.get("blocked") and not observed:
        print("  ('asked' without 'blocked' means the agent was told to cross a boundary and stopped before touching a tool —")
        print("   the written rules held; the hook never had to. Both are the guard doing its job.)")
    for e in entries[-10:]:
        where = f" {e.get('path')}" if e.get("path") else ""
        who = f"[{e.get('agent')}] " if e.get("agent") else ""
        # "(observed)" after the name: pasted into the studio, the text form must not count it as a real block
        event = f"{e.get('event', ''):7}" + (" (observed)" if e.get("observed") else "")
        print(f"  {e.get('ts', '')} {event} {who}{e.get('tool', '')}{where}: " + "; ".join(e.get("hits", [])))
        if e.get("attempted"):
            print(f"      attempted: {e['attempted']}")
    if not entries:
        print("  nothing yet — the guard has not had to step in.")
    # what the agent asked the founder for, next to what the guard did: the workspace reads both from here
    for line in request_lines(project_root()) or []:
        print(line)
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
            loose = [w for w in downgraded_markers(cfg) if w not in stale]
            if loose:
                print(f"  · {len(loose)} blocking keyword(s) would only warn if the markers were derived again today "
                      "(a word code uses for something else, inside a longer name the boundary gives): "
                      + ", ".join(f"'{w}'" for w in loose[:8]) + ("…" if len(loose) > 8 else ""))
                print("    (they still block on a line of code until you run `python scripts/scope_guard.py rebuild-markers`;"
                      " `--dry-run` shows the change first. A keyword that only a comment line or an ignore file names is"
                      " logged as `noted`, not blocked, whether you rebuild or not.)")
            families = missing_package_families(cfg)
            if families:
                print("  · this config predates package families (hook 2026-09-30): packages whose name starts with "
                      + ", ".join(f"'{p}'" for p in families) + " are not refused, only the packages it lists by name")
                print("    (`python scripts/scope_guard.py rebuild-markers` adds them as `deny_package_prefixes`, next to"
                      " re-deriving the markers; `--dry-run` shows every change first.)")
            gained = lexicon_packages_missing(cfg)
            if gained:
                print(f"  · the lexicon has gained packages since this config's hook_version ({cfg.get('hook_version') or 'none'}"
                      "), not refused here until they arrive with `python scripts/scope_guard.py rebuild-markers`: "
                      + ", ".join(f"'{p}'" for p in gained[:12]) + ("…" if len(gained) > 12 else ""))
            if guard_mode(cfg) == "observe":
                print("  · mode: observe — nothing is refused except a change to the guard itself; what would have been stopped is"
                      " logged (`python scripts/scope_guard.py observe off` to enforce)")
            else:
                print("  · mode: enforce")
            print("  · classes: " + " · ".join(f"{name} {class_verdict(cfg, name)}" for name in DEFAULT_CLASSES))
            # the config names the hook it was written for: a newer config read by an older hook loses its new keys
            # in silence (the old script simply does not know them), the reverse only means new keys take defaults
            wanted = str(cfg.get("hook_version") or "")
            have = script_version(script) if script.exists() else HOOK_VERSION
            if wanted and (not have or have < wanted):
                message = (f"the hook in scripts/ is older than the config ({have or 'unversioned'} < {wanted}): copy "
                           "scripts/scope_guard.py from the ZIP, then run write-manifest")
                print(f"  ✗ {message}")
                problems.append(message)
            elif wanted and have > wanted:
                print(f"  · the hook ({have}) is newer than the config's hook_version ({wanted}): fine — keys the config lacks take their defaults")
            elif not wanted:
                print(f"  · the config names no hook_version (written before versions existed, or by hand); the hook is {have or 'unversioned'}")
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
    # the optional local checkpoint before each commit: one line, never a problem (hooks are not cloned with a repository)
    print(pre_commit_doctor_line(root))
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
# `write-manifest` — `GUARD_SELF_RUN` whitelists `report|doctor|request` (and the read-only `check-diff`) and nothing else, so a tool call
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
    # LF on every OS (as `.gitattributes` checks it out): CRLF bytes written on Windows were fingerprinted, and every
    # other clone's doctor then read the guard as changed (review 2026-10-01)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest, write_baseline(root, manifest["files"])


# The variable each agent client sets in the shells it spawns for the agent's commands. CLAUDECODE=1 was read in a
# Claude Code session on the founder's machine (2026-09-23); CODEX_SANDBOX and CODEX_SANDBOX_NETWORK_DISABLED are
# what Codex CLI documents for its sandboxed commands. Cursor, Windsurf and Copilot set nothing this script knows of,
# so there the check cannot tell an agent from the founder — it is a speed bump, not a lock.
AGENT_SHELL_MARKERS = ("CLAUDECODE", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")


def agent_shell() -> str:
    """The marker variable of the agent session this process runs in, or "" for a shell of the founder's own."""
    return next((name for name in AGENT_SHELL_MARKERS if str(os.environ.get(name) or "").strip()), "")


def set_observe(root: Path, on: bool) -> int:
    """`python scripts/scope_guard.py observe on|off` — the founder's own command, refused to the agent like
    `write-manifest` (it is not in `GUARD_SELF_RUN`): an agent that could switch observe on would own an off switch.
    Only the `mode` key changes; the config is fingerprinted, so the manifest and the baseline are taken again,
    or `doctor` would report the guard as rewritten — which it was, by the founder, on purpose.

    The hook refuses the command line; it cannot see the same switch reached through code (`python -c "… import
    scope_guard; scope_guard.main()"` with argv set to `observe on`), and that route left doctor clean because the
    re-baseline came with it (audit 2026-09-23). So the switch itself looks at where it runs: a shell an agent
    client spawned carries that client's marker, and there it writes nothing."""
    marker = agent_shell()
    if marker:
        print(f"observe is the founder's switch, and this shell belongs to an agent session ({marker} is set): nothing was "
              "written. Run it in a terminal of your own — a command typed into the agent's own prompt runs inside its "
              "session too.", file=sys.stderr)
        return 1
    path = config_path(root)
    if path is None:
        print("No .lumis/scope_guard.json here — nothing to switch.", file=sys.stderr)
        return 1
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{path} is not valid JSON ({exc}) — nothing was written. Fix the file first.", file=sys.stderr)
        return 1
    if not isinstance(cfg, dict):
        print(f"{path} does not hold a JSON object — nothing was written.", file=sys.stderr)
        return 1
    cfg["mode"] = "observe" if on else "enforce"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:  # LF on every OS, like the manifest
            fh.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    except Exception as exc:
        print(f"could not write {path}: {exc}", file=sys.stderr)
        return 1
    manifest, outside = rebaseline(root)
    if on:
        print("mode: observe — the guard records what it would have stopped (`report`) and stops nothing but changes to "
              "itself. Back to enforcing: python scripts/scope_guard.py observe off")
    else:
        print("mode: enforce — Non-Goals are refused and the boundary classes are held again.")
    print(f"{MANIFEST}: {len(manifest['files'])} guard file(s) fingerprinted")
    print(f"baseline outside the repository: {outside}" if outside else
          "baseline outside the repository: not written (switched off, or the home folder is read-only)")
    return 0


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
# The packages the capability lexicon gained, by the hook version that added them. `rebuild-markers` brings into an
# older config the ones added after its `hook_version`, for the capabilities it records (`lexicon_packages_missing`);
# a package the lexicon had when the config was written and the config no longer lists was taken out by the founder,
# and stays out. Every entry is in CAPABILITY_TRIGGERS (a test pins it).
LEXICON_PACKAGES_ADDED = {
    "2026-09-30": {"native_mobile": ["create-expo-app"], "payments": ["paypalrestsdk", "paypalcheckoutsdk"],
                   "complex_auth": ["onelogin", "pysaml2", "saml2"], "websockets": ["python-socketio", "flask-socketio"],
                   "email": ["smtplib", "aiosmtplib", "fastapi-mail", "flask-mail"]},
}


def lexicon_packages_missing(cfg: dict) -> list[str]:
    """The lexicon packages this config should list and does not: for each capability it records (`capabilities`),
    those the lexicon added after its `hook_version` — every entry of LEXICON_PACKAGES_ADDED when it records no version
    (written before versions existed, or by hand) or one that is not a YYYY-MM-DD date. Never one in `allowed_markers`, never one it already lists, never a
    package of a capability the config does not record (a hand-written config with `"capabilities": {}` gets none).
    Pure."""
    cfg = cfg or {}
    have = {str(p).strip().lower() for p in cfg.get("deny_packages") or []}
    allowed = {str(w).strip().lower() for w in cfg.get("allowed_markers") or []}
    version = str(cfg.get("hook_version") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        version = ""  # not a date (`"latest"`, `"z"`, a typo): older than every entry, so its packages ARE added
    out: list[str] = []
    for cap in [str(c) for c in (cfg.get("capabilities") or {})]:
        candidates = [p for added, caps in sorted(LEXICON_PACKAGES_ADDED.items()) if added > version
                      for p in caps.get(cap, []) if p in (CAPABILITY_TRIGGERS.get(cap) or {}).get("packages", [])]
        out += [p for p in candidates if p.lower() not in have and p.lower() not in allowed and p not in out]
    return out


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
    # kept as they are (the founder may have added some), plus what the lexicon gained since the config was written
    # (`lexicon_packages_missing`, after the boundaries are matched below)
    packages: list[str] = list(cfg.get("deny_packages") or [])
    paths: list[str] = list(cfg.get("deny_paths") or [])
    # the package families (2026-09-30): kept as they are when the config has the key, taken from the lexicon for the
    # capabilities matched here when it predates them
    has_prefixes = "deny_package_prefixes" in cfg
    prefixes: list[str] = [str(p) for p in (cfg.get("deny_package_prefixes") or [])] if has_prefixes else []
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
                if not has_prefixes:
                    prefixes += list(spec.get("packages_prefix") or [])
                for t in spec["packages"] + list(spec.get("packages_prefix") or []) + spec["paths"] + spec["keywords"]:
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
    packages_added = lexicon_packages_missing(cfg)
    packages += packages_added
    warn_only = [w for w in dedupe(warn_keywords) if w not in set(blocking_keywords) and w.lower() not in allowed][:240]
    return {
        "boundaries": boundaries, "per_boundary": per_boundary, "keywords": blocking_keywords,
        "warn_keywords": warn_only, "trigger_sources": trigger_sources, "capabilities": matched,
        "deny_packages": dedupe(packages), "deny_paths": dedupe(paths),
        "deny_package_prefixes": dedupe(prefixes), "prefixes_added": [] if has_prefixes else dedupe(prefixes),
        "packages_added": packages_added,
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
                lines.append(f"    → warn   {text}   (was blocking; one word of a long sentence, or a word code uses"
                             " for something else inside a longer name the boundary gives)")
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
    if fresh["prefixes_added"]:
        # a config written before 2026-09-30 has no package families; the lexicon's are added for what it matched
        print("  + package families (deny_package_prefixes, hook 2026-09-30): "
              + ", ".join(f"{p}…" for p in fresh["prefixes_added"])
              + " — a package whose name starts with one is refused like the package itself")
    if fresh["packages_added"]:
        # the lexicon's packages added after the config's hook_version; one the founder took out earlier stays out
        print(f"  + packages (deny_packages, the lexicon since {cfg.get('hook_version') or 'the start'}): "
              + ", ".join(fresh["packages_added"])
              + " — list one under \"allowed_markers\" to keep it out")
    if not rows and not fresh["prefixes_added"] and not fresh["packages_added"]:
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
    if fresh["prefixes_added"]:  # a config that already has the key keeps it exactly as it is
        rewritten["deny_package_prefixes"] = fresh["deny_package_prefixes"]
    if fresh["packages_added"]:  # a union: every package the config lists stays
        rewritten["deny_packages"] = fresh["deny_packages"]
    # the config now carries what this hook's lexicon adds: its hook_version says so, and the next rebuild adds only
    # what a later lexicon gains
    rewritten["hook_version"] = HOOK_VERSION
    if origins:  # a preserved marker keeps its recorded origin; one this rebuild dropped no longer has an entry
        rewritten["marker_origins"] = {k: v for k, v in (cfg.get("marker_origins") or {}).items()
                                       if str(k).lower() in {t.lower() for t in fresh["keywords"] + fresh["warn_keywords"]}}
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:  # LF on every OS, like the manifest
            fh.write(json.dumps({**cfg, **rewritten}, ensure_ascii=False, indent=2) + "\n")
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


# The same kind of advice for the rule of 2026-09-29: a config derived before it blocks on `collection` out of
# «No payment collection or billing», where today's derivation arms the phrase and lets that word only warn
# (`payment` and `billing` keep blocking: they name the capability, and `collection` is also a library's name).
def downgraded_markers(cfg: dict) -> list[str]:
    try:
        fresh = derive_config_markers(cfg)
    except Exception:
        return []
    warn_now = {str(w).lower() for w in fresh["warn_keywords"]}
    return sorted({str(k) for k in (cfg.get("keywords") or []) if " " not in str(k) and str(k).lower() in warn_now})


# And for hook 2026-09-30: a config that predates `deny_package_prefixes` has no package families, so `expo-camera` and
# `@expo/vector-icons` pass where `expo` itself is refused. Advice, never a failure: `rebuild-markers` adds them.
def missing_package_families(cfg: dict) -> list[str]:
    if "deny_package_prefixes" in (cfg or {}):
        return []
    out: list[str] = []
    for cap in (cfg or {}).get("capabilities") or {}:
        for prefix in (CAPABILITY_TRIGGERS.get(str(cap)) or {}).get("packages_prefix") or []:
            if prefix not in out:
                out.append(prefix)
    return out


# --- the second checkpoint: the same boundaries on a pull request diff -------------------------------------------
# One contract, two checkpoints. The hook judges a tool call before it runs; `check-diff` judges the added lines of a
# diff — a pull request in CI, a fragment pasted into LUMIS Studio — against the same .lumis/scope_guard.json with the
# same matcher (`trigger_hits`, `warn_triggers`, `is_prose_path`, the architecture regexes, the manifest readers).
# Code the hook never saw arrives there too: a script that wrote files, a teammate without the hook, another machine.
# The diff walker used to live in lumis/core/boundary_check.py; it moved here, stdlib only, and the studio imports it,
# so the paste check and the CI check read a diff the same way and cannot drift apart. It matches words, paths,
# packages and new top-level directories, never meaning: a review aid, not a security boundary.

# How much of a pasted fragment the studio reads: a paste, not a repository. Past these limits the answer says so
# (`truncated`) instead of claiming it read everything. CI lifts them (CI_MAX_*) and says so the same way.
MAX_CHARS = 200_000
MAX_LINES = 5_000
MAX_HITS = 300
EXCERPT_LEN = 200

# The header lines of a unified diff. They must be told apart from removed code: `--- a/file` is a header and
# `- stripe integration` is a removal, and both start with a dash. Without the split, removing a line that itself
# starts with a dash (a Markdown bullet, a YAML item, a `--flag`, an SQL `-- comment`) was either counted as a
# violation or swallowed whole (audit 2026-09-16).
DIFF_HEADERS = ("--- ", "+++ ", "diff --git ", "index ", "@@", "old mode ", "new mode ",
                "new file mode ", "deleted file mode ", "similarity index ", "rename from ",
                "rename to ", "Binary files ", "GIT binary patch")
HUNK_RE = re.compile(r"^@@+ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$")
# The line counts of a hunk header (a missing count is 1). Inside a hunk a line is body by its position, whatever it
# starts with: an added line `++ b/docs/x.md` arrives as `+++ b/docs/x.md`, and reading it as a header moved every
# later line of that code file into a Markdown file, where a crossing is only `noted` (review 2026-09-28).
HUNK_COUNTS_RE = re.compile(r"^@@+ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def diff_text_lines(text: str) -> list[str]:
    """The lines of a diff as git writes them: split on "\\n" only, one trailing "\\r" dropped. `str.splitlines()`
    also breaks on a form feed, U+2028, U+0085 and other characters an added line may carry: the second half of
    such a line lost its sign and was never matched, the hunk counts reset and later lines moved to another file
    or line (review 2026-09-28)."""
    s = str(text or "")
    if not s:
        return []
    parts = s.split("\n")
    if parts[-1] == "":
        parts.pop()
    return [p[:-1] if p.endswith("\r") else p for p in parts]


def looks_like_diff(text: str) -> bool:
    """True for the output of `git diff` / `git show` / any unified diff: a hunk header or a `--- / +++` pair."""
    head = "\n".join(diff_text_lines(text)[:400])
    return ("\n@@" in head or head.startswith("@@") or "diff --git" in head
            or ("\n--- " in head and "\n+++ " in head) or head.startswith("--- "))


def boundary_provenance(boundary: dict) -> dict[str, str]:
    """Who set a boundary and where it is written — what a refusal prints after the NG-n."""
    origin = str((boundary or {}).get("origin") or "")
    return {
        "origin": origin,
        "label": ORIGIN_LABELS.get(origin, origin),
        "source": str((boundary or {}).get("source") or "CONSTITUTION.md, Article I"),
    }


BLOCKING_KEYS = ("deny_packages", "deny_paths", "keywords")
WARN_KEYS = ("warn_keywords",)


def _counts_for(cfg: dict, keys: tuple[str, ...]) -> dict[str, int]:
    """`{boundary_id: n}` over the triggers that actually ship in the config, attributed through `trigger_sources`.

    Counting `trigger_sources` itself — every marker the generator derived, including those the cap then cut —
    reported "49 of 49 boundaries checkable" on the founder's input while 38 of them were unarmed. What counts is
    what the hook carries; anything else is the same invention the health score was removed for."""
    counts = {str(b.get("id") or ""): 0 for b in (cfg.get("boundaries") or [])}
    sources = {str(k).lower(): str(v) for k, v in (cfg.get("trigger_sources") or {}).items()}
    for key in keys:
        for trigger in cfg.get(key) or []:
            bid = sources.get(str(trigger).lower(), "")
            if bid in counts:
                counts[bid] += 1
    return counts


def trigger_counts(cfg: dict) -> dict[str, int]:
    """How many **blocking** triggers stand behind each boundary: `{boundary_id: n}`; zero — nothing to block with.

    A boundary whose triggers came from a `CAPABILITY_TRIGGERS` category already recorded for an earlier boundary
    counts as checked through `capabilities`: it is checked, with the same words."""
    counts = _counts_for(cfg, BLOCKING_KEYS)
    by_text = {str(b.get("text") or "").lower(): str(b.get("id") or "") for b in (cfg.get("boundaries") or [])}
    for texts in (cfg.get("capabilities") or {}).values():
        for text in texts or []:
            bid = by_text.get(str(text).lower())
            if bid and not counts.get(bid):
                counts[bid] = 1
    return counts


def warn_counts(cfg: dict) -> dict[str, int]:
    """How many warn-only markers stand behind each boundary: they fire, they stop nothing."""
    return _counts_for(cfg, WARN_KEYS)


def drop_noise(hits: list[dict]) -> list[dict]:
    """Drop from what is shown a keyword hit wholly inside a phrase or a path that fired on the same line.

    The matching is not rewritten — parity with the hook stays: `smart` inside `smart contract` and `contracts`
    inside `contracts/` stop the agent all the same. Only the duplicate in the output goes, exactly as the grouping in
    `match_triggers` already does; otherwise one line of code is shown as three violations."""
    covers: dict[int, set[tuple[str, str]]] = {}
    for hit in hits:
        if hit["kind"] in ("phrase", "path"):
            covers.setdefault(hit["line"], set()).add((str(hit["trigger"]).lower(), str(hit.get("severity") or "block")))
    out = []
    for hit in hits:
        trigger = str(hit["trigger"]).lower()
        severity = str(hit.get("severity") or "block")
        wider = covers.get(hit["line"], set())
        # a warn-only (or only noted) phrase never hides a blocking word: the stronger verdict must stay in sight
        if hit["kind"] == "keyword" and any(trigger != big and trigger in big and (sev == "block" or severity != "block")
                                            for big, sev in wider):
            continue
        out.append(hit)
    return out


def all_hits(cfg: dict, text: str, path: str = "") -> list[tuple[str, str, str]]:
    """(kind, trigger, severity): the blocking triggers and the warn-only markers, by the hook's own matcher."""
    return ([(kind, trigger, "block") for kind, trigger in trigger_hits(cfg, text, path)]
            + [(kind, trigger, "warn") for kind, trigger in warn_triggers(cfg, text)])


def _walk_diff(lines: list[str], diff: bool) -> Iterator[tuple[str, int, str, int, str]]:
    """(kind, line_no, file, file_line, text) for every line: kind is `header`, `added`, `context`, `removed` or
    `text` (not a diff, or a `\\ No newline` marker). `file` comes from the last `+++ b/<path>` header, `file_line`
    from the hunk header (0 when unknown); `text` is the line without its `+`/`-`/space sign (a header whole).

    Inside a hunk the header's line counts decide what a line is, so an added line that happens to start with `++ `
    or a removed one starting with `-- ` stays body. Past the counts (a hand-trimmed paste) the prefixes decide, as
    they always did."""
    current_file = ""
    new_line_no = 0
    old_left = new_left = 0
    for line_no, raw_line in enumerate(lines, 1):
        if not diff:
            yield "text", line_no, "", 0, raw_line
            continue
        head = raw_line[:1]
        if (old_left > 0 or new_left > 0) and not raw_line.startswith(("@@", "diff --git ")):
            if head == "-":
                old_left -= 1
                yield "removed", line_no, current_file, 0, raw_line[1:]
                continue
            if head in ("+", " ") or raw_line == "":
                file_line = 0
                if new_line_no:
                    file_line, new_line_no = new_line_no, new_line_no + 1
                if head == "+":
                    new_left -= 1
                    yield "added", line_no, current_file, file_line, raw_line[1:]
                else:  # a context line; an empty one is a context line whose space an editor stripped
                    old_left, new_left = old_left - 1, new_left - 1
                    yield "context", line_no, current_file, file_line, raw_line[1:]
                continue
            if head == "\\":
                yield "text", line_no, current_file, 0, raw_line
                continue
            old_left = new_left = 0  # a line no hunk can hold: the counts were wrong, read on by the prefixes
        if raw_line.startswith(DIFF_HEADERS):
            # headers are read, not matched: the file name and the hunk position turn a hit into
            # "api/checkout.py:42" instead of "line 12 of the paste"
            if raw_line.startswith("diff --git "):
                old_left = new_left = 0
            named = NEW_FILE_RE.match(raw_line)
            if named and named.group(1) != "/dev/null":
                current_file = named.group(1).strip()
            hunk = HUNK_RE.match(raw_line)
            if hunk:
                new_line_no = int(hunk.group(1))
                counts = HUNK_COUNTS_RE.match(raw_line)
                if counts:
                    old_left = int(counts.group(1)) if counts.group(1) is not None else 1
                    new_left = int(counts.group(2)) if counts.group(2) is not None else 1
            yield "header", line_no, current_file, 0, raw_line
            continue
        if head == "-":
            yield "removed", line_no, current_file, 0, raw_line[1:]  # removing code never crosses a boundary
            continue
        sign = head if head in ("+", " ") else ""
        body = raw_line[1:] if sign else raw_line
        file_line = 0
        if new_line_no and sign:
            file_line, new_line_no = new_line_no, new_line_no + 1
        yield ("added" if sign == "+" else "context" if sign == " " else "text"), line_no, current_file, file_line, body


def diff_lines(lines: list[str], diff: bool) -> Iterator[tuple[int, str, int, str, str]]:
    """(line_no, file, file_line, sign, body) for every line that is not a header and not a `-` removal. `sign` is
    `+`, ` ` or `""` (not a diff, or a `\\ No newline` marker); `body` is the line without its sign. The one walker
    both the studio's paste check (`scan_fragment`) and the CI check (`line_findings`) read a diff with."""
    for kind, line_no, file_name, file_line, body in _walk_diff(lines, diff):
        if kind in ("header", "removed"):
            continue
        yield line_no, file_name, file_line, ("+" if kind == "added" else " " if kind == "context" else ""), body


def diff_rows(lines: list[str], diff: bool) -> tuple[list[tuple[int, str, int, str, str]], dict[int, list[str]]]:
    """(the rows `diff_lines` yields, {row index: the removed lines right before that row}): the old side of a change,
    for `diff_row_statements` to know what a statement said before the change."""
    rows: list[tuple[int, str, int, str, str]] = []
    removed: dict[int, list[str]] = {}
    pending: list[str] = []
    for kind, line_no, file_name, file_line, body in _walk_diff(lines, diff):
        if kind == "header":
            pending = []
            continue
        if kind == "removed":
            pending.append(body)
            continue
        if pending:
            removed[len(rows)], pending = pending, []
        rows.append((line_no, file_name, file_line, "+" if kind == "added" else " " if kind == "context" else "", body))
    return rows, removed


def diff_row_statements(rows: list[tuple[int, str, int, str, str]], signs: tuple = ("+", " ", ""),
                        removed: dict[int, list[str]] | None = None,
                        spans: dict[int, tuple[int, int]] | None = None) -> dict[int, tuple[str, str]]:
    """{row index: (joined statement, the statement before the change)} for the rows `diff_lines` yields: a statement
    written over several lines of one file (`statement_spans`: `RUN pip install \\` … `resend`, `require(` … `'ws'` …
    `)`), given to its first row whose sign is in `signs` — the first added line for `check-diff` (`("+",)`: the
    statement may start on a context line above it), the first line for the studio's paste. Rows of one file follow
    each other when their file lines do (an unknown line, 0, is taken as following). The hook gives a Write's lines the
    same statements (`judge_tool_input`).

    For `check-diff` (`removed` given, from `diff_rows`) the statement before the change is its context lines and the
    lines the change removed between its first and its last row — never a removed line above its first row, and never
    one of another hunk or another file (the third review of 30.09: a removed comment just above the statement, a
    removed line at the top of the next file, a comment changed 30 lines away in a `-U0` diff all hid the added
    package): a package it already named is not the added line's (`statement_changes`). And when a stretch of rows
    starts inside a statement whose first line the diff does not show — its first row is a bare package token that
    continues a statement (`BARE_CONTINUATION_RE`) — each added bare token of that statement is read as that one package
    (`_candidate_statement`), as the hook reads an Edit whose file it cannot see. An Expo `app.json` whose rows make a
    whole JSON document (a new file, a file the hunk shows whole) is read as one (`stack_config_uses`).

    `spans` (optional) receives {row given a statement: (its first row, its last row)}, so a finding can be reported
    at the row that names the package (`line_findings`)."""
    out: dict[int, tuple[str, str]] = {}
    ci = removed is not None
    got = removed or {}

    def put(row: int, statement: str, base: str, first: int, last: int) -> None:
        had = out.get(row)
        out[row] = (had[0] + "\n" + statement, had[1] or base) if had else (statement, base)
        if spans is not None:
            lo, hi = spans.get(row, (first, last))
            spans[row] = (min(lo, first), max(hi, last))

    def before(a: int, b: int) -> str:
        """Rows a..b as they were: their context lines, and the lines removed between row a and row b."""
        base: list[str] = []
        for x in range(a, b + 1):
            if x > a:
                base += got.get(x, [])
            if rows[x][3] != "+":
                base.append(rows[x][4])
        return "\n".join(base)

    k, n = 0, len(rows)
    while k < n:
        j = k
        while (j + 1 < n and rows[j + 1][1] == rows[k][1]
               and (not rows[j][2] or not rows[j + 1][2] or rows[j + 1][2] == rows[j][2] + 1)):
            j += 1
        found = statement_spans([rows[x][4] for x in range(k, j + 1)], rows[k][1])
        for first, last, joined in found:
            target = next((k + x for x in range(first, last + 1) if rows[k + x][3] in signs), None)
            if target is None:
                continue
            put(target, joined, before(k + first, k + last) if ci else "", k + first, k + last)
        if _base_name(rows[k][1]) in DOCUMENT_NAMES:
            target = next((x for x in range(k, j + 1) if rows[x][3] in signs), None)
            if target is not None:
                whole = "\n".join(rows[x][4] for x in range(k, j + 1))
                put(target, whole, ("\n".join(got.get(k, [])) + "\n" + before(k, j)) if ci else "", k, j)
        if ci and BARE_CONTINUATION_RE.match(rows[k][4]) and rows[k][2] != 1:
            lead = next(((first, last) for first, last, _j in found if first == 0), (0, 0))
            for x in range(lead[0], lead[1] + 1):
                row = rows[k + x]
                m = BARE_CONTINUATION_RE.match(row[4])
                if row[3] == "+" and m and (m.group(2) == "\\" or (x > 0 and rows[k + x - 1][4].rstrip().endswith("\\"))):
                    put(k + x, _candidate_statement(m.group(1)), "", k + x, k + x)
        k = j + 1
    return out


def scan_fragment(cfg: dict, fragment: str, path: str = "", *, max_chars: int = MAX_CHARS, max_lines: int = MAX_LINES,
                  max_hits: int = MAX_HITS) -> dict:
    """The whole reading of a pasted fragment or diff: ``{hits, possible, lines_checked, truncated}``.

    `hits` is what the hook would stop a call on; `possible` are warn-only markers — a single word out of a long
    boundary, which the hook shows and lets through — and, since 2026-09-29, what the hook reads as written down
    rather than crossed (a comment line of a code file, an ignore file: `severity` "noted") or as a keyword only inside
    another tool's option or module name; `why` says which. They are never mixed: a possible match presented as a
    violation is an invented verdict, only from the other side. Each line is read by `line_hits`, with the file of the
    diff header (or `path`) giving the language, exactly as `check-diff` reads an added line.

    `lines_checked` counts the text the matcher actually saw (cut at `max_chars`), not the paste as sent. `truncated`
    is true when the input was cut by characters, by lines, **or** the hits reached `max_hits`: a list cut short in
    silence would look complete. The defaults are the studio's limits; CI passes its own.

    Pure: no files, no network, no state."""
    raw = str(fragment or "")
    text = raw[:max_chars]
    diff = looks_like_diff(text)
    lines = diff_text_lines(text)[:max_lines]
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    capped = False

    def add(kind: str, trigger: str, line_no: int, excerpt: str, file_name: str = "", file_line: int = 0,
            severity: str = "block", why: str = "") -> bool:
        nonlocal capped
        key = (trigger.lower(), line_no)
        if key in seen:
            return True
        seen.add(key)
        boundary = boundary_for(cfg, trigger) or {}
        out.append({
            "boundary_id": boundary.get("id") or "",
            "boundary_text": boundary.get("text") or "",
            "provenance": boundary_provenance(boundary),
            "trigger": trigger,
            "kind": kind,
            "severity": severity,
            "why": why,
            "line": line_no,
            "file": file_name,
            "file_line": file_line,
            "excerpt": excerpt[:EXCERPT_LEN],
        })
        if len(out) >= max_hits:
            capped = True
            return False
        return True

    def result() -> dict:
        kept = drop_noise(out)
        return {
            "hits": [h for h in kept if h["severity"] == "block"],
            "possible": [h for h in kept if h["severity"] != "block"],
            "lines_checked": len(lines),
            "truncated": len(raw) > max_chars or len(diff_text_lines(raw)) > max_lines or capped,
        }

    # a file path sent apart from the text: a hit outside any line (line = 0)
    if path:
        for kind, trigger, severity in all_hits(cfg, "", path):
            if not add(kind, trigger, 0, str(path), file_name=str(path), severity=severity):
                return result()
    technologies = technology_triggers(cfg)
    rows = list(diff_lines(lines, diff))
    statements = diff_row_statements(rows)
    for r, (line_no, file_name, file_line, _sign, body) in enumerate(rows):
        for kind, trigger, severity, why in line_hits(cfg, body, file_name or str(path or ""), technologies=technologies,
                                                      statement=statements.get(r, ("", ""))[0]):
            if not add(kind, trigger, line_no, body.strip(), file_name, file_line, severity=severity, why=why):
                return result()
    return result()


# --- check-diff: what a pull request gets --------------------------------------------------------------------------
# The workflow that runs it, as the three installers write it (the skill's `init --ci`, the guard ZIP, the full pack):
# one text, read from here, so the three cannot differ. ASCII only, no tabs, no backslashes. It runs the checker from
# the BASE commit when the base has one that knows `check-diff`: a pull request that rewrites scripts/scope_guard.py is
# not judged by its own rewrite. Only SHAs and the PR number reach a script — never a title, a body or a branch name.
# A missing checker (or one that wrote no report) leaves a "could not run" report, so the pull request comment is
# refreshed instead of keeping an earlier verdict, and exits 1 in the last step: `python missing.py` exits 2, which
# would read as BLOCK. The YAML itself runs from the pull request's merge commit (GitHub's rule for `pull_request`), so
# a pull request that removes the check step removes the check: the header says so instead of promising a BLOCK.
CI_WORKFLOW_YAML = """# LUMIS boundary check - generated by LUMIS (scripts/scope_guard.py). Do not edit. The boundaries live in
# .lumis/scope_guard.json. The check reports a change to this file as BLOCK, but a pull request runs its own copy of
# it: make this job a required status check and put this file under CODEOWNERS.
# Runs on every pull request, and on a push to main/master so code scanning has an analysis of the base branch.
name: LUMIS boundary check

on:
  pull_request:
  push:
    branches: [main, master]

permissions:
  contents: read
  pull-requests: write
  security-events: write
  actions: read

jobs:
  boundary-check:
    name: LUMIS boundary check
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      EVENT_NAME: ${{ github.event_name }}
      BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}
      HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
      PR_NUMBER: ${{ github.event.pull_request.number }}
      PYTHONIOENCODING: utf-8
      LUMIS_NO_BASELINE: "1"
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Check the diff against .lumis/scope_guard.json
        id: check
        run: |
          mkdir -p "$RUNNER_TEMP/lumis"
          checker="$RUNNER_TEMP/lumis/scope_guard.py"
          report="$RUNNER_TEMP/lumis/report.md"
          sarif="$RUNNER_TEMP/lumis/report.sarif"
          if [ "$EVENT_NAME" = "push" ] && ! git cat-file -e "$BASE_SHA^{commit}" 2>/dev/null; then
            BASE_SHA=$(git rev-parse -q --verify "$HEAD_SHA^" || true)
          fi
          if [ -z "$BASE_SHA" ]; then
            echo "exit=0" >> "$GITHUB_OUTPUT"
            echo "<!-- lumis-boundary-check -->" > "$report"
            echo "## LUMIS boundary check - nothing to compare" >> "$report"
            echo "" >> "$report"
            echo "The first commit on this branch has no parent: nothing was checked." >> "$report"
            echo '{"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "runs": [{"tool": {"driver": {"name": "LUMIS scope guard"}}, "results": []}]}' > "$sarif"
            cat "$report" >> "$GITHUB_STEP_SUMMARY"
            exit 0
          fi
          if git show "$BASE_SHA:scripts/scope_guard.py" > "$checker" 2>/dev/null && grep -q "check-diff" "$checker"; then
            export LUMIS_CHECKER_SOURCE=base
          else
            cp scripts/scope_guard.py "$checker" 2>/dev/null || : > "$checker"
            export LUMIS_CHECKER_SOURCE=head
          fi
          code=1
          if [ -s "$checker" ]; then
            set +e
            python -X utf8 "$checker" check-diff --base "$BASE_SHA" --head "$HEAD_SHA" --root "$GITHUB_WORKSPACE" --markdown "$report" --sarif "$sarif" --json "$RUNNER_TEMP/lumis/report.json"
            code=$?
            set -e
          fi
          if [ ! -s "$report" ]; then
            code=1
            echo "<!-- lumis-boundary-check -->" > "$report"
            echo "## LUMIS boundary check - could not run" >> "$report"
            echo "" >> "$report"
            echo "scripts/scope_guard.py is missing on the base commit and in this change, or it wrote no report. This is not a PASS: nothing was checked." >> "$report"
          fi
          echo "exit=$code" >> "$GITHUB_OUTPUT"
          cat "$report" >> "$GITHUB_STEP_SUMMARY"
      - name: Upload SARIF (code scanning)
        if: always()
        continue-on-error: true
        uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: ${{ runner.temp }}/lumis/report.sarif
          category: lumis-boundary-check
      - name: Post or refresh the pull request comment
        if: always() && github.event_name == 'pull_request'
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          body="$RUNNER_TEMP/lumis/report.md"
          [ -f "$body" ] || exit 0
          id=$(gh api "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" --paginate --jq '.[] | select(.user.login == "github-actions[bot]") | select(.body | startswith("<!-- lumis-boundary-check -->")) | .id' | head -n 1)
          if [ -n "$id" ]; then
            gh api --method PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$id" -F "body=@$body" > /dev/null
          else
            gh api --method POST "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" -F "body=@$body" > /dev/null
          fi
      - name: Verdict
        if: always()
        env:
          CHECK_EXIT: ${{ steps.check.outputs.exit }}
        run: |
          if [ "$CHECK_EXIT" = "0" ]; then exit 0; fi
          if [ "$CHECK_EXIT" = "2" ]; then echo "LUMIS boundary check: BLOCK - see the pull request comment or the job summary"; exit 2; fi
          echo "LUMIS boundary check could not run or could not read the whole diff (exit $CHECK_EXIT) - see the job summary"; exit 1
"""
CI_COMMENT_MARKER = "<!-- lumis-boundary-check -->"
# What a pull request diff is read up to. A diff cut by these limits is INCOMPLETE (exit 1) unless the part read
# already holds a BLOCK: a check that skipped the tail of a diff must not pass a required check, and padding a pull
# request in front of a crossing must not turn a BLOCK into a WARN (review 2026-09-28). The findings list stops at
# CI_MAX_HITS warnings; past it every added line is still read for a BLOCK. CI_MAX_LINES counts added and removed lines
# only — context lines and headers are bounded by the number of hunks (`_change_lines_cut`, third review of 30.09).
CI_MAX_CHARS = 5_000_000
CI_MAX_LINES = 50_000
CI_MAX_HITS = 2_000
# Files git prints as "Binary files … differ". A `.gitattributes` line (`* binary`, `*.py -diff`) or a NUL byte makes
# git print that for a text file, and its added lines went unread (review 2026-09-28): git mode diffs such files
# again with `--text`. Only these suffixes stay unread (listed by name under "Not checked"): images, media, fonts,
# archives, office documents, compiled objects and model weights, whose bytes are not lines.
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".icns", ".webp", ".avif", ".heic", ".tif", ".tiff", ".psd",
    ".ai", ".sketch", ".fig", ".xcf", ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".zst",
    ".jar", ".war", ".ear", ".whl", ".egg", ".class", ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin", ".o",
    ".a", ".lib", ".obj", ".wasm", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".m4a", ".mov", ".avi",
    ".mkv", ".webm", ".wav", ".ogg", ".flac", ".aac", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
    ".ods", ".odp", ".sqlite", ".sqlite3", ".db", ".npy", ".npz", ".pkl", ".pickle", ".parquet", ".onnx", ".pt",
    ".pth", ".h5", ".keras", ".tflite", ".pb", ".dat", ".iso", ".dmg", ".apk", ".ipa", ".aab")
CI_MAX_REREAD = 200
CI_CONTEXT_LINES = 3  # the lines of context `git diff` gives each hunk: where an added line's statement starts
# A pull request comment holds 65 536 characters; the full list is in report.json and the Security tab.
MD_MAX_ROWS = 60
MD_MAX_CHARS = 60_000
# The files through which a boundary itself changes. A change to them is a WARN with the boundary diff, because that
# is how a lift by LUMIS Amend arrives; any other guard file changed in a pull request is a BLOCK.
GUARD_CONTRACT_FILES = (".lumis/scope_guard.json", "CONSTITUTION.md", MANIFEST)
CI_RULES = {
    "LUMIS-ARCH": {
        "short": "Route, model or table not in ARCHITECTURE.md", "level": "warning",
        "source": "ARCHITECTURE.md (API contracts, entities)",
        "full": "An added line declares a route, a persistence model or a table that ARCHITECTURE.md does not list "
                "(architecture.endpoints and architecture.entities in .lumis/scope_guard.json). A warning: a change of "
                "boundaries for the reviewer to confirm, or to add to the architecture first."},
    "LUMIS-DEP": {
        "short": "New dependency in a manifest", "level": "warning",
        "source": ".lumis/scope_guard.json, classes.dependency",
        "full": "A package added to requirements*.txt, pyproject.toml, package.json, Cargo.toml, go.mod, Gemfile, "
                "Pipfile or composer.json that the approved stack does not name and the base branch does not declare. "
                "classes.dependency decides: allow (nothing), ask (WARN, held for the reviewer), block (BLOCK)."},
    "LUMIS-GUARD-FILES": {
        "short": "The guard's own files changed", "level": "error", "source": "the guard's own files",
        "full": "The pull request changes the hook (scripts/scope_guard.py), its client configs or this workflow: "
                "BLOCK, the founder confirms. A change to the boundaries themselves (.lumis/scope_guard.json, "
                "CONSTITUTION.md, the guard's manifest) is a WARN with the boundary diff: that is how a lift by LUMIS "
                "Amend arrives. A config deleted, unreadable or left with no boundary is a BLOCK: after merge the hook "
                "would read no boundaries at all."},
    "LUMIS-NEW-CONTEXT": {
        "short": "New top-level directory (bounded context)", "level": "error", "source": "ARCHITECTURE.md (file plan)",
        "full": "A file is added under a top-level directory that the base branch does not have and the file plan of "
                "ARCHITECTURE.md (architecture.top_level) does not list. A new file inside a known directory is never "
                "this."},
    "LUMIS-NON-GOAL": {
        "short": "Non-Goal trigger with no recorded boundary", "level": "error", "source": ".lumis/scope_guard.json",
        "full": "A trigger listed in .lumis/scope_guard.json (deny_packages, deny_paths, keywords) that "
                "trigger_sources does not attribute to a boundary NG-n."},
}
CI_RULE_ORDER = ("LUMIS-ARCH", "LUMIS-DEP", "LUMIS-GUARD-FILES", "LUMIS-NEW-CONTEXT", "LUMIS-NON-GOAL")
# Said on every report: what this check does not read. Silence about them would be a PASS where nothing was looked at.
NOT_CHECKED_ALWAYS = (
    "outbound actions (a push, a publish, a deploy) and writes outside the project (classes.outbound, "
    "classes.outside_root): they are actions, not lines of a diff",
    "arbitrary shell (bash -c …) inside scripts: a script is matched as text; what it runs is not read",
    "semantics: a home-grown billing module that never says \"stripe\" passes — words, paths, packages and new "
    "top-level directories are matched, not meaning; there is no model and no semantic judge in this check",
    "JS/TS are matched as text patterns; there are no AST rules (planned later, Python only)",
    "visual Non-Goals (DESIGN_CONSTITUTION.md), secrets in the diff, binary files (images, media, archives, compiled "
    "objects) and the content of submodules",
)
CHECKER_SOURCES = {
    "base": "scripts/scope_guard.py from the base commit",
    "head": "scripts/scope_guard.py from this pull request (the base commit has none that knows check-diff)",
    "local": "this scripts/scope_guard.py (a local run)",
}
WARN_LABELS = {"noted": "noted", "possible": "possible", "dependency": "held", "architecture": "architecture",
               "config": "boundary change", "install": "install", "guard-file": "guard file",
               "violation": "violation", "new-context": "new context"}
WARN_LABEL_ORDER = ("noted", "possible", "held", "architecture", "boundary change", "install", "would block")
CHECK_DIFF_USAGE = """LUMIS boundary check — scripts/scope_guard.py check-diff
  --base <ref> [--head <ref>]  git mode: the diff <base>...<head> (head defaults to HEAD), judged against
                               .lumis/scope_guard.json on the base ref — the contract in force
  --diff <file>                a unified diff from a file instead (or pipe one on stdin), judged against the
                               config in the working tree; new directories, dependencies and the boundary diff
                               need git mode and are listed as not checked
  --staged                     the staged change (`git diff --cached` against HEAD; the empty tree before the
                               first commit), judged against the config in HEAD — the pre-commit check
  --root <dir>                 the repository (default: the project root)
  --format markdown|text       what is printed: the markdown report (the default) or a short text for a terminal
  --markdown <file>            write the markdown report there too, whatever --format prints
  --sarif <file>               SARIF 2.1.0 for GitHub code scanning
  --json <file>                the same report for machines
Added lines only: a removal never crosses a boundary. Exit 0 PASS or WARN · 2 BLOCK · 1 could not run, or the diff
was larger than the check reads and no BLOCK was found in the part read (INCOMPLETE) — never a PASS.
Nothing is written but the files named here; the guard's log and baseline are never touched."""


class CheckDiffError(Exception):
    """`check-diff` could not run: no config, no git, a ref that is not a commit, input that is not a diff. Exit 1,
    and the report says so — a check that did not run must never read as a PASS."""


def _first_line(text: str) -> str:
    return next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")[:300]


def _unquote_git_path(name: str) -> str:
    """A path git printed C-quoted (a `"` and backslash escapes, octal for bytes) as the file system spells it."""
    s = str(name or "")
    if len(s) < 2 or not (s.startswith('"') and s.endswith('"')):
        return s
    body, out, i = s[1:-1], bytearray(), 0
    escapes = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            octal = re.match(r"[0-7]{3}", body[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                i += 4
                continue
            if body[i + 1] in escapes:
                out.append(escapes[body[i + 1]])
                i += 2
                continue
        out += ch.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _ci_path(name: str) -> str:
    """A file name as a diff header gave it, as the repository spells it: unquoted, without `b/`, forward slashes."""
    s = str(name or "").strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = _unquote_git_path(s)
        if s.startswith(("a/", "b/")):
            s = s[2:]
    return s.replace("\\", "/")


def _side_name(value: str, prefix: str) -> str:
    """The path of a `--- a/x` / `+++ b/x` header: timestamp (after a tab) and quotes off, the side's prefix off."""
    s = str(value or "").split("\t", 1)[0].rstrip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = _unquote_git_path(s)
    if s == "/dev/null":
        return s
    return (s[len(prefix):] if s.startswith(prefix) else s).replace("\\", "/")


def _diff_git_path(line: str) -> str:
    """The new-side path of `diff --git a/X b/Y` when it can be read without guessing: a C-quoted pair, or the same
    name on both sides. Otherwise "" — the `+++` or `rename to` line that follows names the file."""
    rest = line[len("diff --git "):].rstrip("\r\n")
    quoted = re.match(r'^("(?:[^"\\]|\\.)*"|a/\S+) ("(?:[^"\\]|\\.)*")$', rest)
    if quoted:
        return _ci_path(quoted.group(2))
    if rest.startswith("a/") and (len(rest) - 5) % 2 == 0:
        n = (len(rest) - 5) // 2
        if n > 0 and rest[2 + n:5 + n] == " b/" and rest[2:2 + n] == rest[5 + n:]:
            return rest[2:2 + n]
    return ""


def _guard_file_name(path: str) -> str:
    """The guard file a repository path is, as GUARD_FILES spells it, or ""."""
    low = _clean_path(path)
    return next((f for f in GUARD_FILES if f.lower() == low), "") if low else ""


def _ci_prose(path: str) -> bool:
    """Prose for the CI check: `is_prose_path`, plus the rule files the agent reads (.cursorrules, CLAUDE.md,
    AGENTS.md): LUMIS writes the Non-Goals into them, and writing a boundary down is inside it. An ignore file
    (.gitignore, .dockerignore, …) is read the same way since 2026-09-29, as the hook reads it: it names what a tool
    skips and builds nothing (`yarn-debug.log*` is not a yarn lockfile)."""
    return is_prose_path(path) or is_ignore_file(path) or _clean_path(path) in {f.lower() for f in GUARD_TEXT_FILES}


def _norm_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _boundary_list(cfg: dict) -> list[dict]:
    """`[{id, text, provenance}]` in the config's order (`config_boundaries`, so a config with `non_goals` only
    numbers them by position as both generators do)."""
    raw: dict[str, dict] = {}
    for b in (cfg or {}).get("boundaries") or []:
        if isinstance(b, dict):
            raw.setdefault(str(b.get("id") or ""), b)
    return [{"id": b["id"], "text": b["text"], "provenance": boundary_provenance(raw.get(b["id"]) or {})}
            for b in config_boundaries(cfg or {})]


def boundary_states(cfg: dict) -> dict[str, str]:
    """NG-n -> `armed` (a blocking trigger), `warn-only` (warn markers only) or `unchecked` (nothing to match) — the
    same three states the studio shows (`checkable_boundaries`, `warn_only_boundaries`, `unchecked_boundaries`)."""
    blocking, warning = trigger_counts(cfg), warn_counts(cfg)
    return {b["id"]: ("armed" if blocking.get(b["id"]) else "warn-only" if warning.get(b["id"]) else "unchecked")
            for b in _boundary_list(cfg)}


REVISION_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
NO_REVISION = "not recorded (config written before 2026-09-28)"


def _revision_of(cfg: dict) -> dict:
    """The config's `revision` stamp as `{amend, at}`; `{}` for a config written before the stamp existed. `at` is
    kept only when it is a date: the stamp of a pull request's own config is text the pull request wrote, and it is
    printed in the report."""
    rev = (cfg or {}).get("revision")
    if not isinstance(rev, dict):
        return {}
    try:
        amend = min(max(0, int(rev.get("amend") or 0)), 10 ** 9)
    except (TypeError, ValueError, OverflowError):
        amend = 0
    at = str(rev.get("at") or "").strip()
    return {"amend": amend, "at": at if REVISION_AT_RE.match(at) else ""}


def revision_text(revision: dict, missing: str = NO_REVISION) -> str:
    """`amend #2 (2026-09-27)`, or what a config without the stamp is."""
    if not revision:
        return missing
    return f"amend #{int(revision.get('amend') or 0)}" + (f" ({revision['at']})" if revision.get("at") else "")


def report_meta(cfg: dict, *, config_source: str, input_kind: str = "git", input_name: str = "", base: str = "",
                head: str = "", merge_base: str = "", checker_source: str = "local", actor: str = "", sha: str = "",
                config_commits: list[dict] | None = None) -> dict:
    """What a report says it checked against: the config, its states and revision, the hook, the diff, who ran it.
    Pure: the caller reads the environment (GITHUB_ACTOR, GITHUB_SHA, LUMIS_CHECKER_SOURCE)."""
    states = boundary_states(cfg)
    listed = [states.get(b["id"], "unchecked") for b in _boundary_list(cfg)]
    return {
        "config_source": str(config_source or ""), "config_hook_version": str(cfg.get("hook_version") or ""),
        "revision": _revision_of(cfg), "mode": guard_mode(cfg),
        "boundaries": {"total": len(listed), "armed": listed.count("armed"), "warn_only": listed.count("warn-only"),
                       "unchecked": listed.count("unchecked")},
        "hook_version": HOOK_VERSION, "input": str(input_kind or ""), "input_name": str(input_name or ""),
        "base": str(base or ""), "head": str(head or ""), "merge_base": str(merge_base or ""),
        "checker_source": checker_source if checker_source in CHECKER_SOURCES else "local",
        "actor": str(actor or ""), "sha": str(sha or ""),
        "config_commits": [{"sha": str(c.get("sha") or ""), "author": str(c.get("author") or ""),
                            "subject": str(c.get("subject") or "")} for c in (config_commits or [])],
    }


def parse_name_status(raw: str) -> list[dict]:
    """`git diff --name-status -z` -> `[{status, path, old_path}]`; a rename or a copy carries both paths."""
    parts = str(raw or "").split("\0")
    out: list[dict] = []
    i = 0
    while i < len(parts):
        status = parts[i].strip()
        if not status:
            i += 1
            continue
        code = status[0].upper()
        if code in ("R", "C"):
            old, new = (parts[i + 1] if i + 1 < len(parts) else ""), (parts[i + 2] if i + 2 < len(parts) else "")
            i += 3
            if new:
                out.append({"status": code, "path": new.replace("\\", "/"), "old_path": old.replace("\\", "/")})
            continue
        path = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2
        if path:
            out.append({"status": code, "path": path.replace("\\", "/"), "old_path": ""})
    return out


def changed_files_from_diff(text: str) -> list[dict]:
    """The same `[{status, path, old_path}]` read from the headers of a unified diff, for `--diff` and stdin, where no
    git is asked: `diff --git`, `new file mode`, `deleted file mode`, `rename from/to`, `---`/`+++`. A plain
    `diff -u` without `diff --git` lines is read from its `---`/`+++` pairs."""
    entries: list[dict] = []
    cur: dict | None = None

    def start() -> dict:
        entry = {"status": "M", "path": "", "old_path": "", "old": "", "minus": False, "plus": False}
        entries.append(entry)
        return entry

    for kind, _line_no, _file, _file_line, raw in _walk_diff(diff_text_lines(text), True):
        if kind != "header":
            continue
        if raw.startswith("diff --git "):
            cur = start()
            cur["path"] = _diff_git_path(raw)
        elif raw.startswith("new file mode ") and cur is not None:
            cur["status"] = "A"
        elif raw.startswith("deleted file mode ") and cur is not None:
            cur["status"] = "D"
        elif raw.startswith("rename from ") and cur is not None:
            cur["status"], cur["old_path"] = "R", _ci_path(raw[len("rename from "):])
        elif raw.startswith("rename to ") and cur is not None:
            cur["status"], cur["path"] = "R", _ci_path(raw[len("rename to "):])
        elif raw.startswith("--- "):
            if cur is None or cur["minus"] or cur["plus"]:
                cur = start()
            cur["minus"] = True
            name = _side_name(raw[4:], "a/")
            if name == "/dev/null":
                cur["status"] = "A"
            else:
                cur["old"] = name
        elif raw.startswith("+++ "):
            if cur is None or cur["plus"]:
                cur = start()
            cur["plus"] = True
            name = _side_name(raw[4:], "b/")
            if name == "/dev/null":
                cur["status"] = "D"
                cur["path"] = cur["path"] or cur["old"]
            elif cur["status"] != "R" or not cur["path"]:
                cur["path"] = name
    out: list[dict] = []
    for e in entries:
        path = e["path"] or e["old"]
        if path:
            out.append({"status": e["status"], "path": path,
                        "old_path": e["old_path"] or (e["old"] if e["status"] == "R" else "")})
    return out


BINARY_LINE_RE = re.compile(r"^Binary files (.+) and (.+) differ$")
GITLINK_RE = re.compile(r"^(?:new file mode|new mode|index [0-9a-f]+\.\.[0-9a-f]+) 160000$")


def diff_file_marks(text: str) -> dict[str, list[str]]:
    """What the headers of a diff say about whole files, not lines: `binary` — the new side of every file git printed
    as "Binary files … differ" (a deletion is not listed: removing a file crosses nothing); `submodule` — every path
    added or moved to another commit as a submodule (mode 160000), whose content is another repository."""
    binary: list[str] = []
    submodule: list[str] = []
    cur = {"path": "", "gitlink": False, "deleted": False}

    def close() -> None:
        if cur["gitlink"] and cur["path"] and not cur["deleted"] and cur["path"] not in submodule:
            submodule.append(cur["path"])

    for kind, _line_no, _file, _file_line, raw in _walk_diff(diff_text_lines(text), True):
        if kind != "header":
            continue
        if raw.startswith("diff --git "):
            close()
            cur = {"path": _diff_git_path(raw), "gitlink": False, "deleted": False}
        elif raw.startswith("deleted file mode "):
            cur["deleted"] = True
        elif GITLINK_RE.match(raw):
            cur["gitlink"] = True
        elif raw.startswith("rename to "):
            cur["path"] = _ci_path(raw[len("rename to "):])
        elif raw.startswith("+++ "):
            name = _side_name(raw[4:], "b/")
            if name != "/dev/null":
                cur["path"] = name
        elif raw.startswith("Binary files "):
            m = BINARY_LINE_RE.match(raw)
            new = _side_name(m.group(2), "b/") if m else ""
            if m and new != "/dev/null":
                path = cur["path"] or new
                if path and path not in binary:
                    binary.append(path)
    close()
    return {"binary": binary, "submodule": submodule}


def _binary_suffix(path: str) -> bool:
    return str(path or "").lower().endswith(BINARY_SUFFIXES)


def _ci_finding(cfg: dict, verdict: str, kind: str, *, rule_id: str = "", trigger: str = "", trigger_kind: str = "",
                file: str = "", file_line: int = 0, excerpt: str = "", message: str = "") -> dict:
    """One finding, the same dict in JSON, markdown and SARIF. No None anywhere: "" / 0 / False instead."""
    boundary = boundary_for(cfg, trigger) if (trigger and not rule_id) else None
    if not rule_id:
        rule_id = str((boundary or {}).get("id") or "") or "LUMIS-NON-GOAL"
    if boundary:
        boundary_id, boundary_text = str(boundary.get("id") or ""), str(boundary.get("text") or "")
        provenance = boundary_provenance(boundary)
    else:
        rule = CI_RULES.get(rule_id) or {}
        boundary_id, boundary_text = "", str(rule.get("short") or "")
        provenance = {"origin": "", "label": "", "source": str(rule.get("source") or "")}
    level = "error" if verdict == "BLOCK" else ("note" if kind in ("noted", "possible", "install") else "warning")
    return {"verdict": verdict, "kind": kind, "rule_id": rule_id, "level": level, "boundary_id": boundary_id,
            "boundary_text": boundary_text, "provenance": provenance, "trigger": str(trigger or ""),
            "trigger_kind": str(trigger_kind or ""), "file": str(file or ""), "file_line": int(file_line or 0),
            "excerpt": str(excerpt or ""), "message": str(message or ""), "observed": False, "lifted_in_pr": False}


def _change_lines_cut(lines: list[str], max_changes: int) -> tuple[int, int]:
    """(how many diff lines are read, how many added and removed lines the whole diff has): the diff is read up to
    its `max_changes`-th added or removed line. Context lines and headers are not counted — git gives each hunk at most
    2 × CI_CONTEXT_LINES of them — so three lines of context do not make a diff INCOMPLETE three times sooner (the third
    review of 30.09). A line counts inside a hunk (after an `@@` line, until the next `diff --git`); the `--- a/x` /
    `+++ b/x` headers before a file's first hunk do not."""
    changes, cut = 0, len(lines)
    in_hunk = False
    for i, line in enumerate(lines):
        if line.startswith("@@"):
            in_hunk = True
        elif line.startswith("diff --git "):
            in_hunk = False
        elif in_hunk and line[:1] in ("+", "-"):
            changes += 1
            if changes == max_changes + 1:
                cut = i
    return cut, changes


def _names_trigger(body: str, trigger: str, family: bool, quoted: bool = False) -> bool:
    """The line names the package `trigger` (spelled the `_pep503` way): as a whole name, or as the start of one for a
    family (`deny_package_prefixes`); `quoted`: right after a quote (`from 'resend'`, `"resend": "^2"`)."""
    norm, t = _pep503(body), _pep503(trigger)
    head = r"['\"`]" if quoted else r"(?<![a-z0-9])"
    return bool(t) and bool(re.search(head + re.escape(t) + ("" if family else r"(?![a-z0-9])"), norm))


def line_findings(cfg: dict, diff_text: str, *, max_chars: int = CI_MAX_CHARS, max_lines: int = CI_MAX_LINES,
                  max_hits: int = CI_MAX_HITS, deadline: float = 0.0) -> tuple[list[dict], dict]:
    """Findings on the ADDED lines of a diff; a `-` line never violates anything. A blocking trigger in code is a
    BLOCK, in a document or a test it is `noted` (the hook's own exemption: writing a boundary down is inside it), and
    so it is in a comment line of a code file or an ignore file; a keyword found only inside another tool's option (in
    a CI file, a lockfile or a manifest; never a technology) or a library's import spelling another form of the word
    is `possible` (`line_hits`, the hook's reading of one line, 2026-09-29); a
    warn-only marker is `possible` in code and says nothing in a document, as in the hook; a route, model or table
    ARCHITECTURE.md does not know is a warning on a code file. The guard's own files are skipped: they carry the
    boundaries' own words, and a change to them is `guard_file_findings`' business.

    The list of warnings stops at `max_hits`; past it every added line is still read for a BLOCK, so a pull request
    cannot hide a crossing behind a flood of warnings (review 2026-09-28). The walk stops early only after `max_hits`
    BLOCK findings — the verdict is BLOCK by then — or past `deadline` (time.monotonic(); default: the start of this
    call + CI_SCAN_BUDGET_SECONDS): then the diff was not read to its end and the verdict is INCOMPLETE unless the part
    read holds a BLOCK. `max_lines` counts added and removed lines, not context (`_change_lines_cut`). A package named
    on a later row of a multi-line statement is reported at that row when it is an added one. An added line longer than
    PACKAGE_READ_MAX is read for packages up to there, and the rest is a possible match (WARN), as in the hook.
    Returns (findings, {lines_read, added_lines, total_lines, cut, dropped, stopped, timed_out, capped, truncated}):
    `cut` — the text was longer than `max_chars` / `max_lines` and its tail was not read; `dropped` — warnings not
    listed past the cap; `stopped` — the walk ended at `lines_read` after the BLOCK cap or the deadline (`timed_out`);
    `truncated` — not read to its end."""
    raw = str(diff_text or "")
    text = raw[:max_chars]
    all_lines = diff_text_lines(text)
    read_to, changes = _change_lines_cut(all_lines, max_lines)
    lines = all_lines[:read_to]
    findings: list[dict] = []
    added = walked = dropped = blocks = 0
    stopped = timed_out = False
    deadline = deadline or (time.monotonic() + CI_SCAN_BUDGET_SECONDS)
    kinds: dict[str, tuple[str, bool, bool]] = {}  # header name -> (path, guard file, prose)
    technologies = technology_triggers(cfg)
    families = {str(p).strip().lower() for p in cfg.get("deny_package_prefixes") or [] if str(p or "").strip()}
    placed: set[tuple[str, str, int]] = set()  # (trigger, file, line) already reported: a moved hit is not repeated

    def keep(finding: dict) -> None:
        nonlocal dropped, blocks
        if finding["verdict"] == "BLOCK":
            blocks += 1
            findings.append(finding)
        elif len(findings) < max_hits:
            findings.append(finding)
        else:
            dropped += 1

    rows, removed = diff_rows(lines, True)
    # a statement over several lines, at its first added line — less what it said before the change: a context line
    # only locates the statement an added line belongs to, it never makes a finding of its own
    spans: dict[int, tuple[int, int]] = {}
    statements = diff_row_statements(rows, ("+",), removed, spans)
    for r, (line_no, file_name, file_line, sign, body) in enumerate(rows):
        if time.monotonic() > deadline:
            stopped = timed_out = True
            break
        walked = line_no
        if sign != "+":
            continue
        added += 1
        if file_name not in kinds:
            path = _ci_path(file_name)
            kinds[file_name] = (path, bool(_guard_file_name(path)), _ci_prose(path))
        path, guard, prose = kinds[file_name]
        if guard:
            continue
        seen: set[str] = set()
        hits: list[dict] = []
        # the hook's own reading of one line (`line_hits`): a comment of a code file and an ignore file write a
        # boundary down; a keyword only inside another tool's option (a CI file, a lockfile or a manifest, never a
        # technology) or a library's module name is a possible match
        statement, statement_base = statements.get(r, ("", ""))
        for kind, trigger, severity, why in line_hits(cfg, body, path, technologies=technologies,
                                                      statement=statement, statement_base=statement_base):
            if trigger.lower() in seen:
                continue
            seen.add(trigger.lower())
            hits.append({"kind": kind, "trigger": trigger, "severity": severity, "why": why, "line": file_line})
        if len(body) > PACKAGE_READ_MAX and not prose:
            keep(_ci_finding(cfg, "WARN", "possible", trigger="(not read)", file=path, file_line=file_line,
                             excerpt=redact(body, EXCERPT_LEN),
                             message=f"possible match: this added line is {len(body):,} characters long and was read "
                                     f"for packages only up to {PACKAGE_READ_MAX // 1_000_000} MB — not read past 1 MB"))
        for hit in drop_noise(hits):
            kind, trigger = hit["kind"], hit["trigger"]
            at_line, at_body = file_line, body
            if kind == "package" and r in spans:  # the row of the statement that names the package, if an added one
                lo, hi = spans[r]
                added_rows = [x for x in range(lo, hi + 1) if rows[x][3] == "+" and rows[x][1] == file_name]
                family = trigger.lower() in families
                named = next((x for x in added_rows if _names_trigger(rows[x][4], trigger, family, quoted=True)),
                             next((x for x in added_rows if _names_trigger(rows[x][4], trigger, family)), None))
                if named is not None:
                    at_line, at_body = rows[named][2], rows[named][4]
            if at_line and (trigger.lower(), path, at_line) in placed:
                continue
            placed.add((trigger.lower(), path, at_line))
            where = {"trigger": trigger, "trigger_kind": kind, "file": path, "file_line": at_line,
                     "excerpt": redact(at_body, EXCERPT_LEN)}
            if hit["severity"] == "warn":
                if not prose:  # the hook says nothing about a possible match in a document, and neither does this
                    keep(_ci_finding(cfg, "WARN", "possible", message=possible_line(cfg, trigger, hit["why"]), **where))
                continue
            said = f"{TRIGGER_LABELS.get(kind, 'Non-Goal trigger')} '{trigger}'" + explain(cfg, trigger)
            if hit["severity"] == "noted":
                keep(_ci_finding(cfg, "WARN", "noted", message=f"written down in {hit['why']}, not crossed: " + said,
                                 **where))
            elif prose:
                keep(_ci_finding(cfg, "WARN", "noted", message="written down, not crossed: " + said, **where))
            else:
                keep(_ci_finding(cfg, "BLOCK", "violation", message=said, **where))
        if not prose:
            for arch in architecture_text_hits(cfg, path, body):
                keep(_ci_finding(cfg, "WARN", "architecture", rule_id="LUMIS-ARCH", trigger=arch, file=path,
                                 file_line=file_line, excerpt=redact(body, EXCERPT_LEN), message=arch))
        if blocks >= max_hits:
            stopped = True
            break
    total = len(diff_text_lines(raw))
    cut = len(raw) > max_chars or changes > max_lines
    return findings, {"lines_read": walked if stopped else len(lines), "added_lines": added, "total_lines": total,
                      "changed_lines": changes, "cut": cut, "dropped": dropped, "stopped": stopped,
                      "timed_out": timed_out, "capped": bool(dropped or stopped), "truncated": cut or stopped}


def path_findings(cfg: dict, changed: list[dict]) -> list[dict]:
    """A file added, changed, moved or copied under a forbidden path (`deny_paths`): BLOCK in code, `noted` for a
    document. File-level (file_line 0). A deletion or the old side of a move is leaving the path, not crossing it."""
    out: list[dict] = []
    for ch in changed:
        path = str(ch.get("path") or "")
        if ch.get("status") not in ("A", "M", "T", "R", "C") or not path or _guard_file_name(path):
            continue
        low, prose = path.replace("\\", "/").lower(), _ci_prose(path)
        verb = {"A": "added", "R": "moved", "C": "copied"}.get(str(ch.get("status")), "changed")
        for deny_path in cfg.get("deny_paths") or []:
            deny_path = str(deny_path or "")
            if not deny_path or not deny_path_pattern(deny_path).search(low):
                continue
            said = f"{TRIGGER_LABELS['path']} '{deny_path}'" + explain(cfg, deny_path)
            where = {"trigger": deny_path, "trigger_kind": "path", "file": path, "excerpt": path}
            if prose:
                what = "an ignore file" if is_ignore_file(path) else "a document"
                out.append(_ci_finding(cfg, "WARN", "noted", message=f"written down, not crossed: {said} ({what} {verb} under it)", **where))
            else:
                out.append(_ci_finding(cfg, "BLOCK", "violation", message=f"{said} (a file {verb} under it)", **where))
    return out


def new_context_findings(cfg: dict, changed: list[dict], base_dirs: list[str] | None,
                         submodules: list[str] | tuple = ()) -> tuple[list[dict], str]:
    """A NEW BOUNDED CONTEXT: a file added under a top-level directory the base branch does not have, that the file
    plan of ARCHITECTURE.md (`architecture.top_level`) does not list and that is not one of ALWAYS_ALLOWED_DIRS or a
    dot-directory (tooling). One BLOCK per directory. A new file inside a known directory is never this. A submodule
    is a directory whose content is another repository: one added at the top level is a new top-level directory too.
    Returns (findings, why it was not checked — "" when it was)."""
    arch = cfg.get("architecture") if isinstance(cfg.get("architecture"), dict) else {}
    top_level = {str(d).strip().strip("/").lower() for d in arch.get("top_level") or [] if str(d).strip().strip("/")}
    if not top_level:
        return [], "new bounded contexts (new top-level directories): the config has no ARCHITECTURE inventory (architecture.top_level)"
    if base_dirs is None:
        return [], "new bounded contexts (new top-level directories): no base ref to compare with (--diff / stdin mode)"
    known = {str(d).strip("/").lower() for d in base_dirs} | top_level | ALWAYS_ALLOWED_DIRS
    gitlinks = {str(s).replace("\\", "/").strip("/") for s in submodules or ()}
    first: dict[str, tuple[str, str]] = {}
    for ch in sorted(changed, key=lambda c: str(c.get("path") or "")):
        if ch.get("status") not in ("A", "R", "C"):
            continue
        parts = [p for p in str(ch.get("path") or "").replace("\\", "/").split("/") if p not in ("", ".")]
        is_dir = "/".join(parts) in gitlinks
        if not parts or (len(parts) < 2 and not is_dir) or parts[0].startswith(".") or parts[0].lower() in known:
            continue
        first.setdefault(parts[0].lower(), (parts[0], "/".join(parts)))
    out = [_ci_finding(cfg, "BLOCK", "new-context", rule_id="LUMIS-NEW-CONTEXT", trigger=f"{name}/", trigger_kind="path",
                       file=path, excerpt=path,
                       message=f"new top-level directory '{name}/' is not on the base branch and not in the file plan "
                               "of ARCHITECTURE.md — a new bounded context")
           for _low, (name, path) in sorted(first.items())]
    return out, ""


def _added_lines(diff_text: str, paths: set[str]) -> dict[str, list[tuple[int, str]]]:
    """`{path: [(file_line, body)]}` of the added lines of the given files."""
    out: dict[str, list[tuple[int, str]]] = {}
    if not paths:
        return out
    lines = diff_text_lines(diff_text)
    for _line_no, file_name, file_line, sign, body in diff_lines(lines[:_change_lines_cut(lines, CI_MAX_LINES)[0]], True):
        path = _ci_path(file_name)
        if sign == "+" and path in paths:
            out.setdefault(path, []).append((file_line, body))
    return out


def _line_of_package(lines: list[tuple[int, str]], package: str) -> tuple[int, str]:
    """The first added line that names the package (spelled the `_pep503` way), or (0, "")."""
    rx = re.compile(r"(?<![a-z0-9\-])" + re.escape(package) + r"(?![a-z0-9\-])")
    for file_line, body in lines:
        if rx.search(re.sub(r"[-_.]+", "-", body.lower())):
            return file_line, body
    return 0, ""


def dependency_findings(cfg: dict, manifests: list[dict] | None, base_declared: frozenset | set = frozenset(),
                        diff_text: str = "") -> tuple[list[dict], str]:
    """A dependency added to a manifest (`{path, base_text, head_text}` per changed manifest), read with the hook's
    own readers (`declared_names`): new in the head, not named by the approved stack (`stack_packages`), not already
    declared anywhere on the base branch, not a forbidden package (that is a Non-Goal hit on the line itself).
    `classes.dependency` decides as in the hook: allow — nothing, ask — WARN held for the reviewer, block — BLOCK.
    Returns (findings, why it was not checked — "" when it was)."""
    if manifests is None:
        return [], "dependencies added to a manifest: needs --base/--head (git mode) to read each manifest before and after"
    verdict = class_verdict(cfg, "dependency")
    if verdict == "allow" or not manifests:
        return [], ""
    known = stack_packages(cfg) | {_pep503(p) for p in base_declared}
    denied = {_pep503(p) for p in cfg.get("deny_packages") or []}
    added = _added_lines(diff_text, {str(m.get("path") or "") for m in manifests})
    out: list[dict] = []
    for m in manifests:
        path = str(m.get("path") or "")
        new = declared_names(str(m.get("head_text") or ""), path) - declared_names(str(m.get("base_text") or ""), path)
        for package in sorted(new):
            if package in denied or package in known or forbidden_package(cfg, package, _manifest_reading(path)):
                continue
            file_line, body = _line_of_package(added.get(path, []), package)
            tail = (" — held for the reviewer (classes.dependency: ask)" if verdict == "ask"
                    else " — refused (classes.dependency: block)")
            out.append(_ci_finding(cfg, "BLOCK" if verdict == "block" else "WARN", "dependency", rule_id="LUMIS-DEP",
                                   trigger=package, trigger_kind="package", file=path, file_line=file_line,
                                   excerpt=redact(body, EXCERPT_LEN) if body else path,
                                   message=CLASS_REASONS["dependency"](package) + tail))
    return out, ""


CONTRACT_MESSAGES = {
    ".lumis/scope_guard.json": ".lumis/scope_guard.json changed in this pull request — the boundaries it changes are "
                               "listed under \"Boundaries changed in this PR\"; they take effect after merge",
    "CONSTITUTION.md": "CONSTITUTION.md changed in this pull request — the rules the agent reads; the reviewer confirms "
                       "the change is the founder's (LUMIS Amend rewrites it together with .lumis/scope_guard.json)",
    MANIFEST: ".lumis/guard.manifest.json changed in this pull request — the guard's fingerprints were taken again "
              "(write-manifest or LUMIS Amend); the reviewer confirms",
}


def guard_file_findings(changed: list[dict], first_install: bool = False) -> list[dict]:
    """The guard's own files in a pull request, on either side of a move, deletions included (the log excepted).
    The hook, its client configs and this workflow: BLOCK — the founder confirms. The contract files
    (GUARD_CONTRACT_FILES): WARN, the boundary diff is shown. A first install (no config on the base): WARN."""
    out: list[dict] = []
    seen: set[str] = set()
    for ch in sorted(changed, key=lambda c: str(c.get("path") or "")):
        for side in (str(ch.get("path") or ""), str(ch.get("old_path") or "")):
            name = _guard_file_name(side)
            if not name or name == ".lumis/guard.log" or name in seen:
                continue
            seen.add(name)
            where = {"rule_id": "LUMIS-GUARD-FILES", "trigger": name, "trigger_kind": "path",
                     "file": side.replace("\\", "/"), "excerpt": side}
            if first_install:
                out.append(_ci_finding({}, "WARN", "install", message=f"guard file added in this pull request: {name} — "
                                       "the first install of the guard; there is nothing on the base branch to compare with",
                                       **where))
            elif name in GUARD_CONTRACT_FILES:
                out.append(_ci_finding({}, "WARN", "config", message=CONTRACT_MESSAGES[name], **where))
            else:
                out.append(_ci_finding({}, "BLOCK", "guard-file", message=f"guard file changed in this PR: {name} — the "
                                       "founder confirms; a boundary is lifted through LUMIS Amend, not by editing the hook",
                                       **where))
    return out


# Keys `config_changes` reports on their own terms; every other key of the config is compared as it is, because an
# edit to it can weaken the guard as surely as a lifted boundary (review 2026-09-28): a directory added to
# architecture.top_level is never a new bounded context, a package named in `stack` is never held, `"log": ""` turns
# the hook's journal off. `note` and `generated` are prose and a timestamp.
CONFIG_KEYS_OWN = ("boundaries", "non_goals", "mode", "classes", "deny_packages", "deny_package_prefixes", "deny_paths",
                   "keywords", "warn_keywords", "revision", "note", "generated")
CONFIG_KEY_HINTS = {
    "log": "the hook's journal",
    "stack": "the approved stack: a package it names is not held",
    "architecture.top_level": "the file plan: a directory listed here is never a new bounded context",
    "architecture.endpoints": "routes LUMIS-ARCH knows",
    "architecture.entities": "models and tables LUMIS-ARCH knows",
    "trigger_sources": "which boundary a trigger belongs to",
    "allowed_markers": "markers never armed again",
    "pinned_keywords": "keywords always armed",
    "capabilities": "boundaries checked through a capability lexicon",
    "hook_version": "the hook release the config was written for",
}
_ABSENT = object()


def _config_value(value: object) -> str:
    """A config value in one short line: what a scalar is, or its JSON."""
    if value is _ABSENT:
        return "(absent)"
    if value == "":
        return "(empty)"
    s = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    return s if len(s) <= 120 else s[:119] + "…"


def _config_items(value: object) -> set[str] | None:
    """A list, or a flat mapping (`trigger_sources`), as a set of comparable strings; None for anything else."""
    if value is _ABSENT:
        return set()
    if isinstance(value, list):
        return {x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, sort_keys=True) for x in value}
    if isinstance(value, dict) and all(not isinstance(v, (dict, list)) for v in value.values()):
        return {f"{k} → {v}" for k, v in value.items()}
    return None


def _value_changes(key: str, old: object, new: object, depth: int = 0) -> list[dict]:
    """`[{key, added, removed}]` for lists and flat mappings, `[{key, old, new}]` for anything else; one level of a
    nested mapping (`architecture.top_level`) is opened."""
    if old == new:
        return []
    if (isinstance(old, dict) or old is _ABSENT) and (isinstance(new, dict) or new is _ABSENT) and depth == 0 \
            and (_config_items(old) is None or _config_items(new) is None):
        old_d = old if isinstance(old, dict) else {}
        new_d = new if isinstance(new, dict) else {}
        out: list[dict] = []
        for sub in sorted(set(old_d) | set(new_d), key=str):
            out += _value_changes(f"{key}.{sub}", old_d.get(sub, _ABSENT), new_d.get(sub, _ABSENT), 1)
        return out
    a, b = _config_items(old), _config_items(new)
    if a is not None and b is not None and (old is _ABSENT or new is _ABSENT or type(old) is type(new)):
        return [{"key": key, "added": sorted(b - a), "removed": sorted(a - b)}]
    return [{"key": key, "old": _config_value(old), "new": _config_value(new)}]


def _other_config_changes(base_cfg: dict, head_cfg: dict) -> list[dict]:
    out: list[dict] = []
    for key in sorted((set(base_cfg) | set(head_cfg)) - set(CONFIG_KEYS_OWN), key=str):
        out += _value_changes(str(key), base_cfg.get(key, _ABSENT), head_cfg.get(key, _ABSENT))
    return out


def _revision_via(old_rev: dict, new_rev: dict) -> str:
    """How the stamp moved. Only a higher amend count is LUMIS Amend; the same count with a new date is a pack built or
    downloaded again (the date of amend 0 is the day the pack was written) or a hand edit."""
    old_n, new_n = int(old_rev.get("amend") or 0), int(new_rev.get("amend") or 0)
    if old_rev and not new_rev:
        return "the stamp was removed: not a LUMIS Amend"
    if new_n > old_n:
        return "LUMIS Amend"
    if new_n < old_n:
        return "the amend count went back: an older config"
    if old_rev != new_rev:
        return "same amend count: a pack built or downloaded again, or a hand edit"
    return "not a LUMIS Amend: a hand edit, or the same pack built again"


def config_changes(base_cfg: dict, head_cfg: dict) -> dict:
    """What a pull request changes in .lumis/scope_guard.json. Boundaries are matched by their text first and only
    the leftovers by id, because NG-n is a position — Amend renumbers what follows a lifted boundary, and matching by
    id alone would call every one of them "reworded". Then the mode, the classes, the trigger lists, every other key
    (`other`), the revision."""
    base_cfg, head_cfg = base_cfg or {}, head_cfg or {}
    before, after = _boundary_list(base_cfg), _boundary_list(head_cfg)
    boundaries: list[dict] = []
    taken: set[int] = set()
    left_before: list[dict] = []
    for b in before:
        j = next((i for i, a in enumerate(after) if i not in taken and _norm_text(a["text"]) == _norm_text(b["text"])), None)
        if j is None:
            left_before.append(b)
            continue
        taken.add(j)
        if after[j]["id"] != b["id"]:
            boundaries.append({"change": "renumbered", "id": after[j]["id"], "old_id": b["id"], "text": after[j]["text"],
                               "old_text": b["text"]})
    left_after = {a["id"]: a for i, a in enumerate(after) if i not in taken}
    for b in left_before:
        a = left_after.pop(b["id"], None)
        if a is not None:
            boundaries.append({"change": "reworded", "id": a["id"], "old_id": b["id"], "text": a["text"], "old_text": b["text"]})
        else:
            boundaries.append({"change": "removed", "id": b["id"], "old_id": b["id"], "text": b["text"], "old_text": b["text"]})
    for a in left_after.values():
        boundaries.append({"change": "added", "id": a["id"], "old_id": "", "text": a["text"], "old_text": ""})
    rank = {"removed": 0, "reworded": 1, "added": 2, "renumbered": 3}
    boundaries.sort(key=lambda c: (rank[c["change"]], _ng_order(c["id"])))
    settings: list[dict] = []
    if guard_mode(base_cfg) != guard_mode(head_cfg):
        settings.append({"key": "mode", "old": guard_mode(base_cfg), "new": guard_mode(head_cfg)})
    for name in DEFAULT_CLASSES:
        if class_verdict(base_cfg, name) != class_verdict(head_cfg, name):
            settings.append({"key": f"classes.{name}", "old": class_verdict(base_cfg, name), "new": class_verdict(head_cfg, name)})
    triggers: list[dict] = []
    for key in ("deny_packages", "deny_package_prefixes", "deny_paths", "keywords", "warn_keywords"):
        old = {str(x) for x in base_cfg.get(key) or [] if str(x).strip()}
        new = {str(x) for x in head_cfg.get(key) or [] if str(x).strip()}
        if old != new:
            triggers.append({"key": key, "added": sorted(new - old), "removed": sorted(old - new)})
    old_rev, new_rev = _revision_of(base_cfg), _revision_of(head_cfg)
    return {"boundaries": boundaries, "settings": settings, "triggers": triggers,
            "other": _other_config_changes(base_cfg, head_cfg),
            "revision": {"old": revision_text(old_rev), "new": revision_text(new_rev, "not recorded"),
                         "via": _revision_via(old_rev, new_rev), "changed": old_rev != new_rev}}


def apply_observe(cfg: dict, findings: list[dict]) -> list[dict]:
    """`"mode": "observe"` in the config in force: every BLOCK becomes a WARN marked `observed` ("would block") — the
    hook's own semantics. A change to the guard's own files is not a boundary and stays a BLOCK."""
    if guard_mode(cfg) != "observe":
        return findings
    out: list[dict] = []
    for f in findings:
        if f.get("verdict") == "BLOCK" and f.get("rule_id") != "LUMIS-GUARD-FILES":
            f = dict(f, verdict="WARN", level="warning", observed=True, message="would block (observe mode): " + str(f.get("message") or ""))
        out.append(f)
    return out


VERDICT_EXIT = {"PASS": 0, "WARN": 0, "BLOCK": 2, "INCOMPLETE": 1}


def verdict_of(findings: list[dict], truncated: bool = False, unread: bool = False) -> str:
    """BLOCK when any finding blocks. INCOMPLETE (exit 1) when the diff was not read to its end and the part read
    holds no BLOCK: the tail was not judged, and a pull request padded in front of a crossing must not pass a required
    check. WARN when there is any finding, or a part of the diff the check cannot read (a submodule). Else PASS."""
    if any(f.get("verdict") == "BLOCK" for f in findings):
        return "BLOCK"
    if truncated:
        return "INCOMPLETE"
    return "WARN" if (findings or unread) else "PASS"


def _finding_sort_key(cfg: dict):
    order = {b["id"]: i for i, b in enumerate(_boundary_list(cfg))}

    def key(f: dict) -> tuple:
        rid = str(f.get("rule_id") or "")
        rank = order.get(rid, len(order) + (CI_RULE_ORDER.index(rid) if rid in CI_RULE_ORDER else len(CI_RULE_ORDER)))
        return (0 if f.get("verdict") == "BLOCK" else 1, rank, str(f.get("file") or ""), int(f.get("file_line") or 0),
                str(f.get("trigger") or "").lower())
    return key


def classify_diff(cfg: dict, diff_text: str, changed: list[dict], *, base_dirs: list[str] | None = None,
                  manifests: list[dict] | None = None, base_declared: frozenset | set = frozenset(),
                  head_cfg: dict | None = None, before_cfg: dict | None = None, head_cfg_error: str = "",
                  first_install: bool = False, truncated_input: bool = False, total_lines: int = 0,
                  binary_reread: list[str] | tuple = (),
                  max_chars: int = CI_MAX_CHARS, max_lines: int = CI_MAX_LINES, max_hits: int = CI_MAX_HITS,
                  deadline: float = 0.0) -> dict:
    """The whole verdict on one diff, pure. `cfg` is the config in force (the base's), `changed` the file list
    (`parse_name_status` / `changed_files_from_diff`). What needs git — `base_dirs`, `manifests`, `head_cfg` — is
    None when there was none, and the report then lists that check under "Not checked" instead of passing it.
    `before_cfg` is the config the pull request started from (the merge base) for the boundary diff; `head_cfg` the
    config it ends with. `head_cfg_error` says why there is none to compare with — the pull request deletes the
    config or leaves it unreadable — and is a BLOCK: after merge the hook would read no boundaries at all.
    `binary_reread` are the files git printed as binary that git mode diffed again as text (their lines are in
    `diff_text`). `deadline` (time.monotonic()) bounds the reading of the added lines (`line_findings`)."""
    changed = [{"status": str(c.get("status") or "M")[:1].upper(), "path": str(c.get("path") or "").replace("\\", "/"),
                "old_path": str(c.get("old_path") or "").replace("\\", "/")} for c in (changed or []) if c.get("path")]
    read_text = str(diff_text or "")[:max_chars]
    marks = diff_file_marks(read_text)
    reread = [p for p in (binary_reread or ()) if p]
    unread_binary = [p for p in marks["binary"] if p not in set(reread)]
    submodules = marks["submodule"]
    findings, stats = line_findings(cfg, diff_text, max_chars=max_chars, max_lines=max_lines, max_hits=max_hits,
                                    deadline=deadline)
    findings += path_findings(cfg, changed)
    context, context_reason = new_context_findings(cfg, changed, base_dirs, submodules)
    findings += context
    deps, dep_reason = dependency_findings(cfg, manifests, base_declared, diff_text=read_text)
    findings += deps
    findings += guard_file_findings(changed, first_install)
    touched = {c["path"] for c in changed} | {c["old_path"] for c in changed if c["old_path"]}
    contract = [f for f in GUARD_CONTRACT_FILES if f in touched]
    guard_touched = any(_guard_file_name(p) and _guard_file_name(p) != ".lumis/guard.log" for p in touched)
    changes: dict = {}
    diff_reason = ""
    config_block = ""
    if head_cfg_error and not first_install:
        config_block = head_cfg_error
    elif ".lumis/scope_guard.json" in contract and not first_install:
        if head_cfg is None:
            diff_reason = ("the boundary diff of .lumis/scope_guard.json: needs --base/--head (git mode); only the "
                           "file names were read")
        else:
            before = before_cfg if before_cfg is not None else cfg
            changes = config_changes(before, head_cfg)
            if _boundary_list(before) and not _boundary_list(head_cfg):
                config_block = "this pull request leaves .lumis/scope_guard.json with no boundary"
            removed = {_norm_text(c["text"]) for c in changes["boundaries"] if c["change"] == "removed"}
            lifted = {b["id"] for b in _boundary_list(cfg) if _norm_text(b["text"]) in removed}
            for f in findings:
                if f["boundary_id"] and f["boundary_id"] in lifted:
                    f["lifted_in_pr"] = True
                    f["message"] += (f" — this pull request removes {f['boundary_id']} from .lumis/scope_guard.json; "
                                     "the lift takes effect after merge")
    if config_block:
        # one finding for the file: the BLOCK replaces the contract file's "boundary change" WARN
        findings = [f for f in findings if not (f["kind"] == "config" and f["file"] == ".lumis/scope_guard.json")]
        findings.append(_ci_finding(cfg, "BLOCK", "guard-file", rule_id="LUMIS-GUARD-FILES", trigger=".lumis/scope_guard.json",
                                    trigger_kind="path", file=".lumis/scope_guard.json", excerpt=".lumis/scope_guard.json",
                                    message=f"{config_block} — after merge the hook would read no boundaries at all; "
                                            "the founder confirms"))
    findings = apply_observe(cfg, findings)
    findings.sort(key=_finding_sort_key(cfg))
    truncated = bool(stats["truncated"] or truncated_input)
    total = max(int(total_lines or 0), int(stats["total_lines"]))
    # what the check could not read comes first and the unchecked boundaries last: a long list of unarmed NG-n must
    # never push these lines out of the comment (review 2026-09-28)
    not_checked = list(NOT_CHECKED_ALWAYS)
    not_checked += [r for r in (context_reason, dep_reason, diff_reason) if r]
    if guard_touched:
        not_checked.append("the added lines of the guard's own files (the hook, its configs, this workflow, the "
                           "constitution): they carry the boundaries' own words; a change to them is LUMIS-GUARD-FILES")
    if submodules:
        not_checked.append(f"submodules ({len(submodules)}): what a submodule holds is another repository and is not "
                           "read — " + ", ".join(submodules[:10]) + (", …" if len(submodules) > 10 else ""))
    if unread_binary:
        not_checked.append(f"binary files in this diff ({len(unread_binary)}), not read: "
                           + ", ".join(unread_binary[:10]) + (", …" if len(unread_binary) > 10 else ""))
    if truncated:
        read = stats["lines_read"]
        if stats.get("timed_out"):
            not_checked.append(f"the rest of the diff: the check did not finish reading within "
                               f"{CI_SCAN_BUDGET_SECONDS} s and stopped at diff line {read} of {total} — the rest was "
                               "not judged, so the result is INCOMPLETE (exit 1) unless the part read holds a BLOCK")
        elif stats["stopped"]:
            not_checked.append(f"the rest of the diff: the check stopped at diff line {read} of {total} after "
                               f"{max_hits} BLOCK findings")
        else:
            not_checked.append(f"the diff is larger than the check reads: {read} of {total} diff lines read (the "
                               f"check reads {max_lines:,} added and removed lines and {max_chars:,} characters) — the "
                               "rest was not judged, so the result is INCOMPLETE (exit 1) unless the part read holds a "
                               "BLOCK")
    if stats["dropped"]:
        not_checked.append(f"{stats['dropped']} more warnings: the list stops at {max_hits}; past it every added line "
                           "was still read for a BLOCK")
    states = boundary_states(cfg)
    not_checked += [f"{b['id']} \"{b['text']}\" — no triggers: nothing to match"
                    for b in _boundary_list(cfg) if states.get(b["id"]) == "unchecked"]
    return {"verdict": verdict_of(findings, truncated, unread=bool(submodules)), "findings": findings,
            "boundary_changes": changes, "not_checked": not_checked, "files_changed": len(changed),
            "added_lines": stats["added_lines"], "lines_read": stats["lines_read"], "total_lines": total,
            "truncated": truncated, "capped": bool(stats["capped"]), "dropped": int(stats["dropped"]),
            "contract_changed": contract, "first_install": bool(first_install), "boundary_diff_reason": diff_reason,
            "config_block": config_block, "binary_reread": reread, "binary_unread": unread_binary,
            "submodules": submodules}


# --- the three renderings of one result ---------------------------------------------------------------------------
MD_CONTROL_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
MD_MENTION_RE = re.compile(r"@(?=\w)")


def _md_flat(text: object, limit: int = 0) -> str:
    """One line: control characters out, whitespace (a newline too) collapsed, backticks as `'`, cut at `limit`."""
    s = " ".join(MD_CONTROL_RE.sub(" ", str(text if text is not None else "")).split()).replace("`", "'")
    if limit and len(s) > limit:
        s = s[:limit - 1] + "…"
    return s


def _md_cell(text: object, limit: int = 0) -> str:
    """Text for a table cell or a list item, as plain text whatever it holds: a config on a first install, a route in
    an added line and a boundary id are text a pull request wrote (review 2026-09-28). One line; backslashes, pipes
    and brackets escaped, and a leading `#` (no table break, no link, no heading in a list item); `&`, `<`, `>` as
    entities (no HTML, no entity spelling `@`); `@name` broken with a zero-width space (no mention); backticks as `'`;
    cut at `limit`."""
    s = _md_flat(text, limit)
    s = s.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
    if s.startswith("#"):
        s = "\\" + s
    return MD_MENTION_RE.sub("@&#8203;", s)


def _md_code(text: object, limit: int = 0, table: bool = True) -> str:
    """The same as inline code: what a pull request wrote (a path, an excerpt, a commit subject, a boundary text from
    its config) never renders as markup or as a mention. Empty for empty text."""
    s = _md_flat(text, limit)
    if table:
        s = s.replace("|", "\\|")
    return "`" + s + "`" if s else ""


def _warn_label(f: dict) -> str:
    return "would block" if f.get("observed") else WARN_LABELS.get(str(f.get("kind")), str(f.get("kind") or ""))


def _verdict_cell(f: dict) -> str:
    cell = str(f.get("verdict") or "")
    if cell == "WARN":
        cell += " " + _warn_label(f)
    if f.get("lifted_in_pr"):
        cell += " · lifted in this PR"
    return cell


def _trigger_label(f: dict) -> str:
    kind, trigger = str(f.get("kind") or ""), str(f.get("trigger") or "")
    if kind in ("violation", "noted"):
        return f"{TRIGGER_LABELS.get(str(f.get('trigger_kind')), 'Non-Goal trigger')} '{trigger}'"
    if kind == "possible":
        return f"possible match with '{trigger}'"
    if kind == "architecture":
        return trigger
    if kind == "dependency":
        return f"dependency '{trigger}'"
    if kind == "new-context":
        return f"new top-level directory '{trigger}'"
    return f"guard file '{trigger}'"


def _counts_line(findings: list[dict]) -> str:
    blocks = sum(1 for f in findings if f.get("verdict") == "BLOCK")
    warns = [f for f in findings if f.get("verdict") == "WARN"]
    labels: dict[str, int] = {}
    for f in warns:
        labels[_warn_label(f)] = labels.get(_warn_label(f), 0) + 1
    ordered = [lab for lab in WARN_LABEL_ORDER if lab in labels] + sorted(lab for lab in labels if lab not in WARN_LABEL_ORDER)
    return f"{blocks} BLOCK · {len(warns)} WARN" + (" (" + ", ".join(f"{labels[lab]} {lab}" for lab in ordered) + ")" if warns else "")


def render_markdown(result: dict, meta: dict) -> str:
    """The report a pull request gets, as a comment and as the job summary. The shape is fixed: the marker (the
    workflow finds its own comment by it and edits it), the verdict, what was checked against, the diff, the counts,
    the findings table, the boundaries this PR changes, what was not checked, how a boundary is lifted."""
    findings = result.get("findings") or []
    b = meta.get("boundaries") or {}
    files, added = int(result.get("files_changed") or 0), int(result.get("added_lines") or 0)
    if meta.get("input") == "git":
        what = f"{str(meta.get('base') or '')[:7]}...{str(meta.get('head') or '')[:7]}"
    else:
        what = _md_code(meta.get("input_name") or "stdin", 120, table=False)
    diff_line = f"Diff: {what} · {files} file{'' if files == 1 else 's'} · {added} added line{'' if added == 1 else 's'} read"
    if result.get("truncated"):
        diff_line += f" (not fully read: {result.get('lines_read', 0)} of {result.get('total_lines', 0)} diff lines)"
    reread = list(result.get("binary_reread") or [])
    if reread:
        diff_line += (f" · {len(reread)} file{'' if len(reread) == 1 else 's'} git printed as binary read as text "
                      "(a .gitattributes setting or a NUL byte)")
    diff_line += " · checker: " + CHECKER_SOURCES.get(str(meta.get("checker_source")), CHECKER_SOURCES["local"])
    total = int(b.get("total", 0) or 0)
    head = [
        CI_COMMENT_MARKER,
        f"## LUMIS boundary check — {result.get('verdict', '')}",
        "",
        f"Checked against: .lumis/scope_guard.json ({_md_cell(meta.get('config_source') or 'working tree', 200)}) — "
        f"{total} boundar{'y' if total == 1 else 'ies'} ({b.get('armed', 0)} armed, {b.get('warn_only', 0)} warn-only, "
        f"{b.get('unchecked', 0)} unchecked), hook {_md_cell(meta.get('hook_version') or HOOK_VERSION, 40)}, config "
        f"hook_version {_md_cell(meta.get('config_hook_version') or 'not recorded', 40)}, rules revision "
        f"{_md_cell(revision_text(meta.get('revision') or {}), 80)}",
        "",
        diff_line,
        "",
        _counts_line(findings),
    ]
    if result.get("verdict") == "INCOMPLETE":
        head += ["", "The diff was not read to its end and the part read holds no BLOCK: the rest was not judged. "
                     "Exit 1 — this is not a PASS. Split the pull request, or review the unread part by hand."]
    if meta.get("mode") == "observe":
        head += ["", "Mode: observe (the config in force) — nothing is blocked except a change to the guard itself; "
                     "what would have blocked is marked \"would block\"."]
    head.append("")
    # the table gives way first: "Not checked" and the footer always reach the comment (review 2026-09-28)
    changes: list[str] = []
    if result.get("contract_changed"):
        changes = ["", "### Boundaries changed in this PR", ""]
        size = 0
        for line in _boundary_change_lines(result, meta):
            if size + len(line) > MD_MAX_CHARS // 4:
                changes.append("- …the rest of the boundary changes: report.json")
                break
            changes.append(line)
            size += len(line) + 1
    nc = list(result.get("not_checked") or [])
    tail = ["", "### Not checked", ""] + [f"- {_md_cell(item, 400)}" for item in nc[:60]]
    if len(nc) > 60:
        tail.append(f"- …and {len(nc) - 60} more: report.json")
    tail += ["", "---", "",
             "A boundary is lifted by the founder — through LUMIS Amend (it rewrites CONSTITUTION.md and "
             ".lumis/scope_guard.json together) or by editing .lumis/scope_guard.json in a pull request of its own — "
             "not by editing the hook or this workflow. This check reads the added lines of a diff; it is a review "
             "aid, not a security boundary."]
    budget = MD_MAX_CHARS - sum(len(x) + 1 for x in head + changes + tail) - 200
    table: list[str] = []
    if findings:
        table = ["| verdict | NG-n | boundary (origin; source) | file:line | trigger | excerpt |", "|---|---|---|---|---|---|"]
        used = sum(len(x) + 1 for x in table)
        shown = 0
        for f in findings[:MD_MAX_ROWS]:
            prov = f.get("provenance") or {}
            origin = "; ".join(x for x in (str(prov.get("label") or ""), str(prov.get("source") or "")) if x)
            boundary = str(f.get("boundary_text") or "") + (f" ({origin})" if origin else "")
            where = str(f.get("file") or "") + (f":{f['file_line']}" if f.get("file_line") else "")
            row = (f"| {_verdict_cell(f)} | {_md_cell(f.get('rule_id'), 40)} | {_md_cell(boundary, 240)} | "
                   f"{_md_code(where, 200)} | {_md_cell(_trigger_label(f), 200)} | {_md_code(f.get('excerpt'), 200)} |")
            if used + len(row) + 1 > budget:
                break
            table.append(row)
            used += len(row) + 1
            shown += 1
        if not shown:
            table = [f"{len(findings)} findings do not fit in this comment: report.json / the Security tab"]
        elif shown < len(findings):
            table += ["", f"…and {len(findings) - shown} more: report.json / the Security tab"]
    else:
        table = ["No finding: no added line, file path, new directory or manifest in this diff matches a boundary this "
                 "config can check (see Not checked)."]
    return "\n".join(head + table + changes + tail) + "\n"


def _boundary_change_lines(result: dict, meta: dict) -> list[str]:
    """The "who lifted what, by which change" lines of a pull request that touches the contract files."""
    out: list[str] = []
    changes = result.get("boundary_changes") or {}
    contract = list(result.get("contract_changed") or [])
    if result.get("first_install"):
        out.append("- first install: the whole contract arrives with this pull request; there is no earlier config to "
                   "compare with")
    elif changes:
        for c in (changes.get("boundaries") or [])[:40]:
            text = _md_code(c.get("text"), 160, table=False)
            bid, old_id = _md_cell(c.get("id"), 40), _md_cell(c.get("old_id"), 40)
            if c["change"] == "removed":
                out.append(f"- {bid} {text} — removed (lifted)")
            elif c["change"] == "added":
                out.append(f"- {bid} {text} — added")
            elif c["change"] == "reworded":
                out.append(f"- {bid} — reworded: {_md_code(c.get('old_text'), 160, table=False)} → {text}")
            else:
                out.append(f"- {old_id} → {bid} {text} — renumbered (same text)")
        if len(changes.get("boundaries") or []) > 40:
            out.append(f"- …and {len(changes['boundaries']) - 40} more boundary changes: report.json")
        for s in changes.get("settings") or []:
            out.append(f"- {s['key']}: {_md_cell(s['old'], 40)} → {_md_cell(s['new'], 40)}")

        def listed(entry: dict) -> str:
            parts = []
            for sign, key in (("+", "added"), ("-", "removed")):
                if entry.get(key):
                    parts.append(f"{sign}{len(entry[key])} (" + ", ".join(_md_code(x, 60, table=False) for x in entry[key][:8])
                                 + (", …" if len(entry[key]) > 8 else "") + ")")
            return " · ".join(parts)

        for t in changes.get("triggers") or []:
            out.append(f"- {t['key']}: " + listed(t))
        other = changes.get("other") or []
        for o in other[:30]:
            hint = CONFIG_KEY_HINTS.get(str(o.get("key")), "")
            name = _md_code(o.get("key"), 60, table=False) + (f" ({hint})" if hint else "")
            if "old" in o:
                out.append(f"- {name}: {_md_code(o['old'], 120, table=False) or '(none)'} → "
                           f"{_md_code(o['new'], 120, table=False) or '(none)'}")
            else:
                out.append(f"- {name}: " + listed(o))
        if len(other) > 30:
            out.append(f"- …and {len(other) - 30} more config keys changed: report.json")
        rev = changes.get("revision") or {}
        if rev.get("changed"):
            out.append(f"- rules revision: {_md_cell(rev.get('old'), 80)} → {_md_cell(rev.get('new'), 80)} "
                       f"({rev.get('via')})")
        else:
            out.append(f"- rules revision: {_md_cell(rev.get('new'), 80)}, unchanged ({rev.get('via')})")
        if not (changes.get("boundaries") or changes.get("settings") or changes.get("triggers") or other):
            out.append("- .lumis/scope_guard.json changed, but no key the hook reads did (formatting, `note` or "
                       "`generated` only)")
    elif result.get("config_block"):
        out.append(f"- not compared: {_md_cell(result['config_block'], 300)} — after merge the hook would read no "
                   "boundaries at all")
    elif result.get("boundary_diff_reason"):
        out.append(f"- not compared: {result['boundary_diff_reason']}")
    if "CONSTITUTION.md" in contract and ".lumis/scope_guard.json" not in contract and not result.get("first_install"):
        out.append("- CONSTITUTION.md changed and .lumis/scope_guard.json did not: the hook and this check read the "
                   "config, so a boundary edited only in the constitution is not in force")
    commits = meta.get("config_commits") or []
    who = []
    if commits:
        who.append("changed in " + "; ".join(f"{_md_code(c.get('sha'), 12, table=False)} by {_md_code(c.get('author'), 60, table=False)} "
                                             f"({_md_code(c.get('subject'), 100, table=False)})" for c in commits[:10]))
    if meta.get("actor"):
        who.append(f"pull request event by {_md_code('@' + str(meta['actor']), 60, table=False)}")
    if meta.get("sha"):
        who.append(f"run on {_md_code(str(meta['sha'])[:7], 12, table=False)}")
    if who:
        out.append("- " + " · ".join(who))
    return out


def render_error_markdown(reason: str) -> str:
    """The report of a check that could not run. It says so and says it is not a PASS."""
    return "\n".join([CI_COMMENT_MARKER, "## LUMIS boundary check — could not run", "", _md_cell(reason, 1500), "",
                      "This is not a PASS: nothing was checked. Fix the cause above and run the check again.", "",
                      f"hook {HOOK_VERSION} · `python scripts/scope_guard.py check-diff --help` lists the inputs"]) + "\n"


def _sarif_uri(path: str) -> str:
    """A repository-relative URI: forward slashes, no leading `/` or `./`, percent-encoded."""
    from urllib.parse import quote

    clean = str(path or "").replace("\\", "/")
    while clean.startswith(("./", "/")):
        clean = clean[2:] if clean.startswith("./") else clean[1:]
    return quote(clean, safe="/")


def render_sarif(result: dict, cfg: dict) -> dict:
    """SARIF 2.1.0 for GitHub code scanning: one run, one rule per boundary of the config in force (NG-n) plus the
    LUMIS-* rules, one result per finding that has a file (code scanning rejects a result without a location). A
    file-level finding points at line 1. No `properties`, no nulls."""
    rules: list[dict] = []
    index: dict[str, int] = {}

    def add_rule(rule_id: str, short: str, full: str, level: str) -> None:
        if rule_id in index:
            return
        index[rule_id] = len(rules)
        rules.append({"id": rule_id, "shortDescription": {"text": short or rule_id},
                      "fullDescription": {"text": full or short or rule_id},
                      "defaultConfiguration": {"level": level}})

    for b in _boundary_list(cfg):
        prov = b["provenance"]
        origin = "; ".join(x for x in (prov.get("label") or "", prov.get("source") or "") if x)
        add_rule(b["id"], b["text"], b["text"] + (f" ({origin})" if origin else ""), "error")
    for rule_id in ("LUMIS-ARCH", "LUMIS-DEP", "LUMIS-GUARD-FILES", "LUMIS-NEW-CONTEXT"):
        add_rule(rule_id, CI_RULES[rule_id]["short"], CI_RULES[rule_id]["full"], CI_RULES[rule_id]["level"])
    results: list[dict] = []
    for f in result.get("findings") or []:
        rule_id = str(f.get("rule_id") or "LUMIS-NON-GOAL")
        if not f.get("file"):
            continue
        if rule_id not in index:
            rule = CI_RULES.get(rule_id) or {}
            add_rule(rule_id, str(rule.get("short") or f.get("boundary_text") or rule_id),
                     str(rule.get("full") or f.get("boundary_text") or rule_id), str(rule.get("level") or "error"))
        results.append({
            "ruleId": rule_id, "ruleIndex": index[rule_id], "level": str(f.get("level") or "warning"),
            "message": {"text": str(f.get("message") or rule_id)},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": _sarif_uri(str(f["file"])), "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": max(1, int(f.get("file_line") or 0))}}}],
        })
    return {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "LUMIS scope guard", "version": HOOK_VERSION,
                                          "informationUri": "https://lumis.tools/guard", "rules": rules}},
                      "results": results}]}


def _finding_counts(findings: list[dict]) -> dict:
    warn_by_label: dict[str, int] = {}
    for f in findings:
        if f.get("verdict") == "WARN":
            warn_by_label[_warn_label(f)] = warn_by_label.get(_warn_label(f), 0) + 1
    return {"block": sum(1 for f in findings if f.get("verdict") == "BLOCK"),
            "warn": sum(1 for f in findings if f.get("verdict") == "WARN"), "warn_by_label": warn_by_label}


def render_json(result: dict, meta: dict) -> dict:
    """The same report for machines (`--json`)."""
    return {"schema": "lumis-boundary-check/1", "verdict": result.get("verdict", ""),
            "exit_code": VERDICT_EXIT.get(str(result.get("verdict")), 1), "checked_against": meta,
            "counts": _finding_counts(result.get("findings") or []), "findings": result.get("findings") or [],
            "boundary_changes": result.get("boundary_changes") or {}, "not_checked": result.get("not_checked") or [],
            "diff": {"base": meta.get("base", ""), "head": meta.get("head", ""), "merge_base": meta.get("merge_base", ""),
                     "files_changed": result.get("files_changed", 0), "added_lines": result.get("added_lines", 0),
                     "lines_read": result.get("lines_read", 0), "total_lines": result.get("total_lines", 0),
                     "truncated": bool(result.get("truncated")), "warnings_not_listed": int(result.get("dropped") or 0),
                     "binary_read_as_text": list(result.get("binary_reread") or []),
                     "binary_not_read": list(result.get("binary_unread") or []),
                     "submodules": list(result.get("submodules") or [])},
            "error": ""}


def render_error_json(reason: str) -> dict:
    return {"schema": "lumis-boundary-check/1", "verdict": "ERROR", "exit_code": 1,
            "checked_against": {"hook_version": HOOK_VERSION}, "counts": {"block": 0, "warn": 0, "warn_by_label": {}},
            "findings": [], "boundary_changes": {}, "not_checked": [], "diff": {}, "error": str(reason or "")}


# --- the same result for a terminal (`--format text`: what the pre-commit check prints, hook 2026-10-01) -----------
TEXT_WARNINGS_SHOWN = 5
TEXT_ROW_MAX = 300
TEXT_LIMITS = ("It reads the added lines as text — words, paths, packages, new top-level directories — not meaning: "
               "a review aid, not a security boundary.")


def _text_row(f: dict) -> str:
    """`path:line  NG-n boundary text — what matched: the line`, on one line."""
    where = _md_flat(str(f.get("file") or "") + (f":{f['file_line']}" if f.get("file_line") else ""), 200)
    boundary = " ".join(x for x in (str(f.get("rule_id") or ""), str(f.get("boundary_text") or "")) if x)
    # a guard-file BLOCK carries its reason in the message (deleted, not valid JSON, the hook changed): the trigger
    # label alone said only "guard file '…'" (review 2026-10-01)
    guard_block = f.get("rule_id") == "LUMIS-GUARD-FILES" and f.get("verdict") == "BLOCK" and f.get("message")
    reason = str(f.get("message") or "").replace("in this pull request", "in this change").replace("in this PR", "in this change")
    row = f"{boundary} — {reason if guard_block else _trigger_label(f)}"
    if f.get("excerpt") and f.get("excerpt") != f.get("file") and not guard_block:
        row += f": {f['excerpt']}"
    if f.get("lifted_in_pr"):
        row += " (this change removes the boundary; the lift takes effect once it is committed)"
    return f"{where}  {_md_flat(row, TEXT_ROW_MAX)}"


def render_text(result: dict, meta: dict, note: str = "") -> str:
    """The report for a person at a terminal: the verdict, each BLOCK as `path:line  NG-n boundary — what matched`, the
    warnings counted with the first few shown, then one line on how to go on. Plain text: no markdown, no table."""
    findings = result.get("findings") or []
    verdict = str(result.get("verdict") or "")
    staged = meta.get("input") == "staged"
    files, added = int(result.get("files_changed") or 0), int(result.get("added_lines") or 0)
    lines = [f"LUMIS boundary check — {verdict} ({_counts_line(findings)})",
             f"  {_md_flat(meta.get('input_name') or meta.get('input') or 'diff', 120)} · {files} file{'' if files == 1 else 's'}"
             f" · {added} added line{'' if added == 1 else 's'} read · against .lumis/scope_guard.json "
             f"({_md_flat(meta.get('config_source') or 'working tree', 120)})"]
    if note:
        lines.append(f"  {note}")
    if meta.get("mode") == "observe":
        lines.append("  mode: observe — nothing is blocked except a change to the guard itself (\"would block\" below)")
    for f in findings:
        if f.get("verdict") == "BLOCK":
            lines.append("  BLOCK " + _text_row(f))
    warns = [f for f in findings if f.get("verdict") == "WARN"]
    if warns:
        shown = warns[:TEXT_WARNINGS_SHOWN]
        lines.append(f"  WARN: {len(warns)}" + (f" — the first {len(shown)}:" if len(warns) > len(shown) else ":"))
        lines += [f"  WARN {_warn_label(f)} " + _text_row(f) for f in shown]
    if verdict == "INCOMPLETE":
        lines.append("  The change was not read to its end and the part read holds no BLOCK: the rest was not judged "
                     "(exit 1 — not a PASS). Split the change, or review the unread part by hand"
                     + (" (one oversized file, a regenerated lockfile say: the founder commits it with `git commit "
                        "--no-verify`)." if staged else "."))
    elif verdict == "WARN" and not warns:
        # a WARN with no WARN row: what was left unread (a submodule, a binary file) is the reason — say it
        unread = [r for r in (result.get("not_checked") or []) if r.startswith(("submodules (", "binary files in"))]
        lines += [f"  not read: {_md_flat(r, TEXT_ROW_MAX)}" for r in unread[:3]]
    commit = "the commit" if staged else "the change"
    if verdict in ("BLOCK", "INCOMPLETE"):
        blocks = [f for f in findings if f.get("verdict") == "BLOCK"]
        guard = [f for f in blocks if f.get("rule_id") == "LUMIS-GUARD-FILES"]
        skip = (" `git commit --no-verify` skips this check; the pull request check still reads the diff." if staged else "")
        if blocks and len(guard) == len(blocks):
            # the guard's own files are not a boundary: lifting one, or committing the config alone, changes nothing
            lines.append("To go on: this is a change to the guard itself, not a boundary crossing — the founder "
                         + ("commits it with `git commit --no-verify` and confirms it on the pull request." if staged
                            else "confirms it on the pull request.") + " " + TEXT_LIMITS)
        else:
            lines.append(f"To go on: fix the {'staged ' if staged else ''}change; or the founder lifts the boundary (LUMIS "
                         "Amend, or an edit of .lumis/scope_guard.json committed on its own)."
                         + (" A change to the guard's own files is the founder's to confirm." if guard else "")
                         + skip + " " + TEXT_LIMITS)
    else:
        lines.append(("A WARN does not stop " + commit + ". " if verdict == "WARN" else "") + TEXT_LIMITS)
    return "\n".join(lines) + "\n"


def render_error_text(reason: str, staged: bool = False) -> str:
    return (f"LUMIS boundary check could not run: {_md_flat(reason, 600)}\n"
            "  This is not a PASS: nothing was checked" + (" — the commit is refused (exit 1). Fix the cause, or skip "
                                                          "the check once with `git commit --no-verify`; the pull "
                                                          "request check still reads the diff." if staged else
                                                          " (exit 1).") + "\n")


# --- check-diff: the command ---------------------------------------------------------------------------------------
CHECK_DIFF_VALUE_FLAGS = ("--base", "--head", "--diff", "--root", "--markdown", "--sarif", "--json", "--format")
CHECK_DIFF_FORMATS = ("markdown", "text")


def parse_check_diff_args(argv: list[str]) -> dict:
    """The flags of `check-diff`, read by hand: argparse exits 2 on a bad flag, and 2 means BLOCK here. A problem is
    returned in `error` (exit 1, "could not run"), after every output path has been read, so the report of the
    failure still lands where it was asked for."""
    opts: dict = {key: "" for key in ("base", "head", "diff", "root", "markdown", "sarif", "json", "format")}
    opts.update(help=False, staged=False, error="")
    args = [str(a) for a in (argv or [])]
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--help", "-h", "help"):
            opts["help"] = True
            i += 1
            continue
        if a == "--staged":
            opts["staged"] = True
            i += 1
            continue
        name, eq, value = a.partition("=")
        if name in CHECK_DIFF_VALUE_FLAGS:
            if not eq:
                if i + 1 >= len(args):
                    opts["error"] = opts["error"] or f"{name} needs a value"
                    i += 1
                    continue
                value = args[i + 1]
                i += 2
            else:
                i += 1
            opts[name[2:]] = value
            continue
        opts["error"] = opts["error"] or (f"unknown flag {a}" if a.startswith("-") else f"unexpected argument '{a}'")
        i += 1
    if not opts["error"] and opts["base"] and opts["diff"]:
        opts["error"] = "--base and --diff are two different inputs: give one of them"
    if not opts["error"] and opts["staged"] and (opts["base"] or opts["head"] or opts["diff"]):
        opts["error"] = "--staged reads the staged change against HEAD: it takes no --base, --head or --diff"
    if not opts["error"] and opts["head"] and not opts["base"]:
        opts["error"] = "--head needs --base"
    if not opts["error"] and opts["format"] and opts["format"] not in CHECK_DIFF_FORMATS:
        opts["error"] = f"--format {opts['format']}: markdown or text"
    return opts


def _guard_output(target: str, root: Path) -> bool:
    """True when an output path is one of the guard's own files: a report is never written over the config."""
    names = {f.lower() for f in GUARD_FILES}
    if _clean_path(target) in names:
        return True
    try:
        p = Path(target)
        absolute = p if p.is_absolute() else Path.cwd() / p
        rel = os.path.relpath(os.path.realpath(absolute), os.path.realpath(root))
    except (ValueError, OSError):
        return False  # another drive on Windows: not inside the repository
    return _clean_path(rel) in names


def _git(cwd: Path, *args: str, timeout: int = 120, stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, input=stdin)
    except FileNotFoundError:
        raise CheckDiffError("git is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        raise CheckDiffError(f"`git {' '.join(args[:4])}` did not finish in {timeout} s") from None
    except OSError as exc:
        raise CheckDiffError(f"git could not start: {exc}") from None


def _git_blob(cwd: Path, rev: str, path: str, limit: int = 0) -> str | None:
    """A file as it is in a commit, or None when the commit does not have it."""
    res = _git(cwd, "cat-file", "blob", f"{rev}:{path}")
    if res.returncode != 0:
        return None
    return res.stdout[:limit] if limit else res.stdout


def _git_diff_stream(cwd: Path, args: list[str], max_bytes: int, timeout: int = 300) -> tuple[str, int, bool]:
    """(the first `max_bytes` bytes of git's output as text, the number of lines of the whole output, whether it was
    cut). Streamed: a pull request that vendors a dependency can print hundreds of megabytes, and only the head is
    kept in memory; the rest is counted, so the report can say how much it did not read."""
    import tempfile
    import threading

    with tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(["git", *args], cwd=str(cwd), stdout=subprocess.PIPE, stderr=err)
        except FileNotFoundError:
            raise CheckDiffError("git is not installed or not on PATH") from None
        except OSError as exc:
            raise CheckDiffError(f"git could not start: {exc}") from None
        killed: list[bool] = []

        def kill() -> None:
            killed.append(True)
            proc.kill()

        timer = threading.Timer(timeout, kill)
        timer.start()
        kept = bytearray()
        total = lines = 0
        last = b""
        stream = proc.stdout
        try:
            while stream is not None:
                chunk = stream.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                lines += chunk.count(b"\n")
                last = chunk[-1:]
                if len(kept) < max_bytes:
                    kept += chunk[:max_bytes - len(kept)]
            code = proc.wait()
        finally:
            timer.cancel()
            if stream is not None:
                stream.close()
        if killed:
            raise CheckDiffError(f"`git diff` did not finish in {timeout} s")
        if code != 0:
            err.seek(0)
            raise CheckDiffError("`git diff` failed: " + (_first_line(err.read().decode("utf-8", "replace")) or f"exit {code}"))
    if total and last != b"\n":
        lines += 1
    return kept.decode("utf-8", "replace"), lines, total > max_bytes


def _parse_config(raw: str, where: str) -> dict:
    try:
        cfg = json.loads(str(raw or "").lstrip("﻿"))
    except Exception as exc:
        raise CheckDiffError(f"{where} is not valid JSON ({exc})") from None
    if not isinstance(cfg, dict):
        raise CheckDiffError(f"{where} does not hold a JSON object")
    return cfg


def _read_config_file(root: Path, missing: str = "") -> dict:
    path = root / ".lumis" / "scope_guard.json"
    if not path.is_file():
        raise CheckDiffError(missing or (f"no .lumis/scope_guard.json in {root} — nothing to check against. Install the "
                                         "guard first (the LUMIS guard ZIP, or `python lumis_guard.py init`)."))
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CheckDiffError(f"{path} cannot be read ({exc})") from None
    return _parse_config(raw, ".lumis/scope_guard.json in the working tree")


def _skipped_manifest(path: str) -> bool:
    """A manifest inside a vendored or generated folder (node_modules/, vendor/, .venv/…) is not the project's."""
    parts = str(path or "").replace("\\", "/").split("/")[:-1]
    return any(p.startswith(".") or p.lower() in MANIFEST_SKIP_DIRS for p in parts)


GIT_SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
# How the report names the two sides of the change it read, per input: a pull request (`--base`) or the staged change
# (`--staged`, the pre-commit check), whose "head" is the index.
GIT_SIDES = {
    False: {"change": "this pull request", "on_base": "on the base ref", "base_short": "base",
            "on_head": "in the head commit", "in_change": "in this pull request"},
    True: {"change": "the staged change", "on_base": "in HEAD", "base_short": "HEAD",
           "on_head": "in the staged change", "in_change": "in the staged change"},
}


def git_inputs(root: Path, base: str, head: str = "HEAD", *, staged: bool = False) -> dict:
    """Everything `classify_diff` needs, from git: the diff `<base>...<head>` (added lines from the merge base), the
    changed files, the base's top-level directories, the manifests before and after, what the base already declares,
    the config in force (the base's; the PR's own only on a first install) and, when the PR changes the config, the
    config before and after it. The only function that runs git; every failure is a CheckDiffError (exit 1).

    `staged` (the pre-commit check, hook 2026-10-01): the same reading of the staged change — `git diff --cached`
    against HEAD with the same flags, the empty tree before the first commit. HEAD is the base and the merge base; the
    index is the head: a manifest after the change and the staged config are read from the index (`:path`), never from
    the working tree, so a file staged in part is judged as it will be committed. `base` and `head` are not read."""
    if not staged:
        for ref in (base, head):
            if not ref or ref.startswith("-") or len(ref) > 256 or any(ch.isspace() or ord(ch) < 32 for ch in ref):
                raise CheckDiffError(f"'{ref}' is not a git ref this check will hand to git")
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        raise CheckDiffError(f"{root} is not inside a git repository ({_first_line(top.stderr) or 'git rev-parse failed'})")
    cwd = Path(top.stdout.strip())
    sides = GIT_SIDES[bool(staged)]

    def commit(ref: str) -> str:
        res = _git(cwd, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        sha = res.stdout.strip()
        if res.returncode != 0 or not GIT_SHA_RE.fullmatch(sha):
            raise CheckDiffError(f"'{ref}' is not a commit in this repository — fetch it (actions/checkout with "
                                 "fetch-depth: 0) or check the name")
        return sha

    born = True
    if staged:
        res = _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        base_sha = res.stdout.strip()
        if res.returncode != 0 or not GIT_SHA_RE.fullmatch(base_sha):
            # no commit yet: the first commit is judged against the empty tree (its id depends on the hash function)
            born = False
            empty = _git(cwd, "hash-object", "-t", "tree", "--stdin", stdin="")
            base_sha = empty.stdout.strip()
            if empty.returncode != 0 or not GIT_SHA_RE.fullmatch(base_sha):
                raise CheckDiffError("`git hash-object` could not name the empty tree: " + _first_line(empty.stderr))
        head_sha = ""  # the index: `<rev>:<path>` with no rev is `:<path>`, the staged blob
        merge_base = base_sha
        span = ["--cached", base_sha]
    else:
        base_sha, head_sha = commit(base), commit(head)
        mb = _git(cwd, "merge-base", base_sha, head_sha)
        merge_base = mb.stdout.strip().splitlines()[0] if (mb.returncode == 0 and mb.stdout.strip()) else ""
        if not merge_base:
            raise CheckDiffError("no merge base between the base and the head — fetch the full history (actions/checkout "
                                 "with fetch-depth: 0)")
        span = [f"{base_sha}...{head_sha}"]
    head_name = head_sha[:7] or "the index"
    plain = ["-c", "core.quotepath=off", "-c", "diff.relative=false", "diff", "--no-color", "--no-ext-diff"]
    # three lines of context (the second review of 30.09): only ADDED lines are judged; a context line only shows which statement an
    # added line continues (`    resend \` under `RUN pip install \`, review 30.09). CI_MAX_CHARS counts the diff as
    # fetched; CI_MAX_LINES only its added and removed lines (`_change_lines_cut`, third review of 30.09).
    lines_args = ["--no-textconv", f"--unified={CI_CONTEXT_LINES}", "--find-renames", "--src-prefix=a/", "--dst-prefix=b/"]
    diff_text, total_lines, cut = _git_diff_stream(cwd, plain + lines_args + span, CI_MAX_CHARS)
    names = _git(cwd, *plain, "--name-status", "-z", "--find-renames", *span)
    if names.returncode != 0:
        raise CheckDiffError("`git diff --name-status` failed: " + _first_line(names.stderr))
    changed = parse_name_status(names.stdout)
    # A file git printed as binary is diffed again as text unless its suffix says it is one: a `.gitattributes` in the
    # pull request (`* binary`, `*.py -diff`) or a NUL byte in a script otherwise hid every added line of it. A moved
    # file is asked for with its old path too, so the move is still a move and only its new lines are added lines.
    reread = [p for p in diff_file_marks(diff_text)["binary"] if not _binary_suffix(p)][:CI_MAX_REREAD]
    if reread and not cut:
        olds = {c["path"]: c["old_path"] for c in changed if c.get("old_path")}
        spec = list(dict.fromkeys(q for p in reread for q in (p, olds.get(p, "")) if q))
        extra, extra_lines, extra_cut = _git_diff_stream(
            cwd, ["--literal-pathspecs"] + plain + ["--text"] + lines_args + span + ["--", *spec],
            max(0, CI_MAX_CHARS - len(diff_text.encode("utf-8"))))
        diff_text = diff_text + ("" if not diff_text or diff_text.endswith("\n") else "\n") + extra
        total_lines += extra_lines
        cut = cut or extra_cut
    elif cut:
        reread = []
    tree = _git(cwd, "ls-tree", "-d", "-z", "--name-only", base_sha)
    if tree.returncode != 0:
        raise CheckDiffError("`git ls-tree` failed on the base: " + _first_line(tree.stderr))
    base_dirs = [d for d in tree.stdout.split("\0") if d]

    config = ".lumis/scope_guard.json"
    touched = {c["path"] for c in changed} | {c["old_path"] for c in changed if c["old_path"]}
    base_raw = _git_blob(cwd, base_sha, config)
    first_install = base_raw is None
    head_cfg: dict | None = None
    before_cfg: dict | None = None
    head_cfg_error = ""
    if not first_install:
        cfg = _parse_config(str(base_raw), f"{config} {sides['on_base']} ({base_sha[:7]})")
        source = f"{sides['base_short']} {base_sha[:7]}"
        if config in touched:
            before_raw = _git_blob(cwd, merge_base, config)
            try:
                before_cfg = _parse_config(before_raw, config) if before_raw is not None else cfg
            except CheckDiffError:
                before_cfg = cfg
            head_raw = _git_blob(cwd, head_sha, config)
            if head_raw is None:  # after merge the hook reads no boundary: the same BLOCK as an unreadable config
                head_cfg_error = f"{sides['change']} deletes {config}"
            else:
                try:
                    head_cfg = _parse_config(head_raw, f"{config} {sides['in_change']} ({head_name})")
                except CheckDiffError as exc:
                    head_cfg_error = str(exc)
        if staged and head_cfg is not None:
            # a merge commit concluded by hand (a conflict): when the staged config is the merged branch's, committed
            # there, its boundaries judge — a lift committed on main is not refused again in every branch that merges
            # main (review 2026-10-01). A clean merge runs no pre-commit hook at all (git runs pre-merge-commit).
            merging = _git(cwd, "rev-parse", "--verify", "--quiet", "MERGE_HEAD^{commit}")
            merge_sha = merging.stdout.strip()
            if merging.returncode == 0 and GIT_SHA_RE.fullmatch(merge_sha):
                theirs = _git_blob(cwd, merge_sha, config)
                try:
                    same = theirs is not None and json.loads(theirs) == json.loads(str(head_raw))
                except ValueError:
                    same = False
                if same:
                    cfg = head_cfg
                    source = (f"the merged commit {merge_sha[:7]}: the staged config is the one committed there "
                              f"(HEAD {base_sha[:7]} has another)")
    else:
        head_raw = _git_blob(cwd, head_sha, config)
        if head_raw is not None:
            cfg = _parse_config(head_raw, f"{config} {sides['in_change']} ({head_name})")
            source = f"{sides['change']}: no config {sides['on_base']}, first install"
        else:
            cfg = _read_config_file(root, missing=f"no {config} {sides['on_base']}, {sides['on_head']} or in {root} — "
                                                  "nothing to check against. Install the guard first (the LUMIS guard "
                                                  "ZIP, or `python lumis_guard.py init`).")
            source = f"working tree: no config {sides['on_base']} or {sides['on_head']}"

    manifests: list[dict] = []
    for ch in changed:
        path = ch["path"]
        if ch["status"] == "D" or not _is_manifest(path) or _skipped_manifest(path):
            continue
        if len(manifests) >= 60:
            break
        before = "" if ch["status"] in ("A", "C") else (_git_blob(cwd, merge_base, ch["old_path"] or path, 400_000) or "")
        manifests.append({"path": path, "base_text": before, "head_text": _git_blob(cwd, head_sha, path, 400_000) or ""})
    declared: set[str] = set()
    listing = _git(cwd, "ls-tree", "-r", "-z", "--name-only", base_sha)
    base_manifests = []
    for p in (listing.stdout.split("\0") if listing.returncode == 0 else []):
        parts = p.split("/")
        if not p or len(parts) > 2 or not _is_manifest(p):
            continue
        if len(parts) == 2 and (parts[0].startswith(".") or parts[0].lower() in MANIFEST_SKIP_DIRS):
            continue
        base_manifests.append(p)
    for p in base_manifests[:60]:
        declared |= declared_names(_git_blob(cwd, base_sha, p, 400_000) or "", p)

    commits: list[dict] = []
    if touched & set(GUARD_CONTRACT_FILES) and not staged:  # a staged change has no commits of its own yet
        log = _git(cwd, "log", "--no-color", "--no-show-signature", "--format=%h%x09%an%x09%s", f"{base_sha}..{head_sha}",
                   "--", *GUARD_CONTRACT_FILES)
        for line in (log.stdout.splitlines() if log.returncode == 0 else [])[:10]:
            sha, _t, rest = line.partition("\t")
            author, _t, subject = rest.partition("\t")
            commits.append({"sha": sha.strip(), "author": author.strip(), "subject": subject.strip()})
    return {"cfg": cfg, "diff_text": diff_text, "changed": changed, "base_dirs": base_dirs, "manifests": manifests,
            "base_declared": frozenset(declared), "head_cfg": head_cfg, "before_cfg": before_cfg,
            "head_cfg_error": head_cfg_error, "first_install": first_install, "truncated_input": cut,
            "total_lines": total_lines, "binary_reread": reread, "config_source": source,
            "input": "staged" if staged else "git",
            "input_name": ((f"staged changes against HEAD {base_sha[:7]}" if born else
                            "staged changes, no commit yet (against the empty tree)") if staged else f"{base}...{head}"),
            "base": base_sha, "head": head_sha, "merge_base": merge_base, "config_commits": commits,
            "note": "nothing is staged: nothing to check" if (staged and not changed) else ""}


def _text_inputs(root: Path, diff_path: str) -> dict:
    """`--diff <file>` or stdin: the diff as given, the file list from its headers, the working tree's config.
    Without git there is no base tree, no manifest before/after and no config diff: those are "not checked"."""
    if diff_path:
        p = Path(diff_path)
        if not p.is_file():
            raise CheckDiffError(f"--diff {diff_path}: no such file")
        text, name, kind = p.read_bytes().decode("utf-8", "replace"), diff_path, "file"
    else:
        stdin = sys.stdin
        if stdin is None or stdin.isatty():
            raise CheckDiffError("no diff given: pass --base <ref> [--head <ref>], --diff <file>, or pipe a unified diff "
                                 "on stdin")
        text, name, kind = stdin.buffer.read().decode("utf-8", "replace"), "stdin", "stdin"
    if not text.strip():
        raise CheckDiffError(f"the diff ({name}) is empty: nothing to check")
    if not looks_like_diff(text):
        raise CheckDiffError(f"the input ({name}) is not a unified diff: no `diff --git` line, `@@` hunk or `---`/`+++` pair")
    return {"cfg": _read_config_file(root), "diff_text": text, "changed": changed_files_from_diff(text),
            "config_source": "working tree", "input": kind, "input_name": name}


def _write_report(target: str, text: str) -> bool:
    try:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return True
    except Exception as exc:
        sys.stderr.write(f"LUMIS boundary check: could not write {target}: {exc}\n")
        return False


def _check_diff_failed(reason: str, outputs: dict, refused: set, fmt: str = "markdown", staged: bool = False) -> int:
    """Exit 1, said plainly. The markdown and the JSON are written where they were asked for (never over a guard
    file); SARIF is not: an empty upload would close the open code-scanning alerts as if the code were fixed."""
    markdown = render_error_markdown(reason)
    if fmt == "text":  # one plain statement for a terminal, on stdout like the report it replaces
        print(render_error_text(reason, staged), end="")
    else:
        print(markdown, end="")
        sys.stderr.write(f"LUMIS boundary check could not run: {reason}\n")
    data = json.dumps(render_error_json(reason), ensure_ascii=False, indent=2) + "\n"
    for key, target in outputs.items():
        if key in refused or key == "sarif":
            continue
        _write_report(target, markdown if key == "markdown" else data)
    return 1


def check_diff(argv: list[str]) -> int:
    """`python scripts/scope_guard.py check-diff …` — exit 0 PASS or WARN, 2 BLOCK, 1 could not run or INCOMPLETE
    (the diff was not read to its end; no SARIF then either: a partial upload would close the alerts of the unread
    part as if they were fixed). Never writes the guard's log, never records a baseline; writes nothing but the
    reports it was asked for. The reading of the added lines stops CI_SCAN_BUDGET_SECONDS after the start: INCOMPLETE.
    `--staged` reads the staged change against HEAD (the pre-commit check); `--format text` prints `render_text`."""
    deadline = time.monotonic() + CI_SCAN_BUDGET_SECONDS
    opts = parse_check_diff_args(argv)
    if opts["help"] and not opts["error"]:
        print(CHECK_DIFF_USAGE)
        return 0
    root = Path(opts["root"]) if opts["root"] else project_root()
    outputs = {key: opts[key] for key in ("markdown", "sarif", "json") if opts[key]}
    refused = {key for key, target in outputs.items() if _guard_output(target, root)}
    # the markdown report stays what check-diff prints unless a terminal format is asked for: CI is untouched
    fmt = opts["format"] if opts["format"] in CHECK_DIFF_FORMATS else "markdown"
    try:
        if opts["error"]:
            raise CheckDiffError(opts["error"])
        if refused:
            raise CheckDiffError("will not write the report over the guard's own file: "
                                 + ", ".join(f"--{key} {outputs[key]}" for key in sorted(refused)))
        if not root.is_dir():
            raise CheckDiffError(f"--root {root} is not a directory")
        if opts["staged"]:
            inputs = git_inputs(root, "", staged=True)
        elif opts["base"]:
            inputs = git_inputs(root, opts["base"], opts["head"] or "HEAD")
        else:
            inputs = _text_inputs(root, opts["diff"])
        cfg = inputs["cfg"]
        result = classify_diff(cfg, inputs["diff_text"], inputs["changed"], base_dirs=inputs.get("base_dirs"),
                               manifests=inputs.get("manifests"), base_declared=inputs.get("base_declared") or frozenset(),
                               head_cfg=inputs.get("head_cfg"), before_cfg=inputs.get("before_cfg"),
                               head_cfg_error=inputs.get("head_cfg_error") or "",
                               first_install=bool(inputs.get("first_install")),
                               truncated_input=bool(inputs.get("truncated_input")),
                               total_lines=int(inputs.get("total_lines") or 0),
                               binary_reread=inputs.get("binary_reread") or (), deadline=deadline)
        meta = report_meta(cfg, config_source=inputs["config_source"], input_kind=inputs["input"],
                           input_name=inputs["input_name"], base=inputs.get("base", ""), head=inputs.get("head", ""),
                           merge_base=inputs.get("merge_base", ""),
                           checker_source=str(os.environ.get("LUMIS_CHECKER_SOURCE") or "local").strip().lower(),
                           actor=str(os.environ.get("GITHUB_ACTOR") or ""), sha=str(os.environ.get("GITHUB_SHA") or ""),
                           config_commits=inputs.get("config_commits"))
        markdown = render_markdown(result, meta)
        reports = {"markdown": markdown,
                   "sarif": json.dumps(render_sarif(result, cfg), ensure_ascii=False, indent=2) + "\n",
                   "json": json.dumps(render_json(result, meta), ensure_ascii=False, indent=2) + "\n"}
        printed = markdown if fmt == "markdown" else render_text(result, meta, note=str(inputs.get("note") or ""))
    except CheckDiffError as exc:
        return _check_diff_failed(str(exc), outputs, refused, fmt, bool(opts["staged"]))
    except Exception as exc:  # a crash must read as "could not run", never as a verdict (a traceback exits 1 anyway)
        return _check_diff_failed(f"internal error in check-diff ({type(exc).__name__}: {exc})", outputs, refused,
                                  fmt, bool(opts["staged"]))
    print(printed, end="")
    code = VERDICT_EXIT.get(str(result["verdict"]), 1)
    for key, target in outputs.items():
        if key == "sarif" and code == 1:
            continue
        _write_report(target, reports[key])
    return code


# --- the pre-commit check: the same boundaries on the staged change (hook 2026-10-01) ---------------------------------
# A third checkpoint between the hook and the pull request: `git commit` reads the staged change with `check-diff
# --staged` and refuses the commit on BLOCK — whoever commits, an agent in any client or a person, a GUI client too. It
# is local: hooks are not cloned with a repository (each clone installs it once), `git commit --no-verify` skips it,
# and the pull request check reads the diff again. A review aid, not a security boundary. The free pack ships only
# scripts/scope_guard.py, so the hook writes the git hook itself: one constant, the same bytes from the mode and from
# the skill's `init --pre-commit`. POSIX sh, because Git for Windows runs hooks through its own sh too; the
# interpreter is probed (`python3` may be the Microsoft Store stub on Windows, which exists and does not run).
PRE_COMMIT_MARKER = "# lumis-boundary-check"
PRE_COMMIT_SCRIPT = """#!/bin/sh
# lumis-boundary-check
# LUMIS boundary check before each commit - written by `python scripts/scope_guard.py install-pre-commit`, removed by
# `python scripts/scope_guard.py install-pre-commit --uninstall`. Do not edit: a reinstall writes it again.
# It reads the staged change against .lumis/scope_guard.json as committed (HEAD) and refuses the commit on BLOCK.
# It runs the working tree's scripts/scope_guard.py (the pull request check runs the base commit's copy).
# A review aid, not a security boundary: it runs on this machine only, `git commit --no-verify` skips it, and the pull
# request check reads the diff again.
root=$(git rev-parse --show-toplevel) || exit 1
cd "$root" || exit 1
# the hooks folder serves every branch and worktree: one that never had the guard, or carries an older copy, is let
# through with a note, not refused
if [ ! -f scripts/scope_guard.py ]; then
  if ! git cat-file -e HEAD:scripts/scope_guard.py 2>/dev/null; then
    echo "LUMIS boundary check: this branch has no scripts/scope_guard.py - the staged change was not checked; the commit goes on." >&2
    exit 0
  fi
  echo "LUMIS boundary check: scripts/scope_guard.py is in HEAD but not in the working tree, so the staged change was not checked - commit refused." >&2
  echo "Restore the file, remove this hook ($0), or skip the check once: git commit --no-verify" >&2
  exit 1
fi
if ! grep -q -e 'check-diff --staged' scripts/scope_guard.py; then
  echo "LUMIS boundary check: this branch carries a scripts/scope_guard.py older than hook 2026-10-01 (no --staged mode) - the staged change was not checked; the commit goes on." >&2
  exit 0
fi
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    exec "$py" -X utf8 scripts/scope_guard.py check-diff --staged --format text --root "$root"
  fi
done
if command -v py >/dev/null 2>&1 && py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
  exec py -3 -X utf8 scripts/scope_guard.py check-diff --staged --format text --root "$root"
fi
echo "LUMIS boundary check: no Python 3.9+ found (python3, python or py -3), so the staged change was not checked - commit refused." >&2
echo "Put Python 3.9+ on PATH, or skip the check once: git commit --no-verify" >&2
exit 1
"""
# what goes into a pre-commit hook that is not ours (and into husky's): the check, its exit code passed on
PRE_COMMIT_LINE = "python3 scripts/scope_guard.py check-diff --staged --format text || exit $?"
PRE_COMMIT_FRAMEWORK_SNIPPET = """  - repo: local
    hooks:
      - id: lumis-boundary-check
        name: LUMIS boundary check
        entry: python scripts/scope_guard.py check-diff --staged --format text
        language: system
        pass_filenames: false
        always_run: true"""
PRE_COMMIT_USAGE = """LUMIS pre-commit check — scripts/scope_guard.py install-pre-commit [--uninstall] [--root <dir>]
  writes the git pre-commit hook (where `git rev-parse --git-path hooks` says: core.hooksPath and linked worktrees
  included) that runs `scripts/scope_guard.py check-diff --staged --format text` before each commit and refuses the
  commit on BLOCK, or when the check could not run. A pre-commit hook that is not ours is never overwritten: the line
  to add to it is printed (exit 1). With the pre-commit framework (.pre-commit-config.yaml) or husky (.husky/) the
  snippet for that tool is printed instead, nothing is written (exit 0). --uninstall removes our file and nothing else.
Local only: hooks are not cloned with a repository (each clone installs it once; a hooks folder inside the working
tree, `core.hooksPath .githooks`, is committed instead), `git commit --no-verify` skips it, and the pull request check
reads the diff again. A review aid, not a security boundary."""


def _git_top_and_hooks(root: Path) -> tuple[Path, Path] | None:
    """(the top of the working tree, the folder git runs its hooks from) — `git rev-parse --git-path hooks` follows
    core.hooksPath and a linked worktree's common directory. None outside a repository, or without git."""
    try:
        res = subprocess.run(["git", "rev-parse", "--show-toplevel", "--git-path", "hooks"], cwd=str(root),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if res.returncode != 0 or len(out) < 2:
        return None
    top = Path(out[0])
    hooks = Path(os.path.expanduser(out[1]))
    if hooks.is_absolute():
        return top, hooks
    # a relative answer is relative to where git ran; a relative core.hooksPath is printed as configured, relative to
    # the top of the working tree, where git runs the hooks: asked again from there when `root` is a subfolder
    if os.path.normcase(os.path.realpath(top)) != os.path.normcase(os.path.realpath(root)):
        return _git_top_and_hooks(top) if top.is_dir() and top != Path(root) else None
    return top, top / hooks


def _is_our_pre_commit(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096).decode("utf-8", "replace")
    except OSError:
        return False
    return any(line.strip() == PRE_COMMIT_MARKER for line in head.splitlines()[:10])


def pre_commit_state(root: Path) -> tuple[str, Path | None]:
    """("ours" | "foreign" | "absent" | "no-git", the pre-commit path git would run)."""
    found = _git_top_and_hooks(root)
    if found is None:
        return "no-git", None
    target = found[1] / "pre-commit"
    if not os.path.lexists(target):
        return "absent", target
    return ("ours" if target.is_file() and _is_our_pre_commit(target) else "foreign"), target


def _hooks_folder_is_shared(top: Path, hooks: Path) -> bool:
    """True when git's hooks folder lies outside this repository's working tree and its git directory: a global or
    shared core.hooksPath, which every other repository using it runs too."""
    try:
        res = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(top), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    common = Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else top / ".git"
    folder = os.path.normcase(os.path.realpath(hooks))
    for inside in (top, common if common.is_absolute() else top / common):
        holder = os.path.normcase(os.path.realpath(inside))
        if folder == holder or folder.startswith(holder.rstrip("\\/") + os.sep):
            return False
    return True


def install_pre_commit(root: Path, uninstall: bool = False) -> tuple[str, str]:
    """Writes (or removes) our pre-commit hook; returns (what happened, the path). Installing: "written", "updated" (an
    older copy of ours), "unchanged", "framework" / "husky" (that tool runs the hooks: nothing written), "foreign" (a
    pre-commit hook that is not ours: left as it is), "subfolder" (the guard is not at the top of the working tree:
    the path is that top), "shared" (the hooks folder is outside the repository), "no-git". Removing: "removed",
    "absent", "kept" (not ours: left as it is), "no-git". Written as bytes, LF only, and made executable where the OS
    has the bit."""
    state, target = pre_commit_state(root)
    if state == "no-git" or target is None:
        return "no-git", ""
    if uninstall:
        if state != "ours":
            return ("absent" if state == "absent" else "kept"), str(target)
        target.unlink()
        return "removed", str(target)
    text = PRE_COMMIT_SCRIPT.encode("utf-8")
    top = (_git_top_and_hooks(root) or (Path(root), Path(root)))[0]
    # the script runs scripts/scope_guard.py from the top of the working tree: a pack in a subfolder (a monorepo app)
    # would refuse every commit there with "not in this repository" (review 2026-10-01)
    if not (top / "scripts" / "scope_guard.py").is_file():
        return "subfolder", str(top)
    # a global or shared core.hooksPath serves other repositories too: never written there
    if _hooks_folder_is_shared(top, target.parent):
        return "shared", str(target)
    if state == "ours" and target.read_bytes() == text:
        return "unchanged", str(target)
    if state != "ours":
        if (top / ".pre-commit-config.yaml").is_file():
            return "framework", str(target)
        if (top / ".husky").is_dir():
            return "husky", str(target)
        if state == "foreign":
            return "foreign", str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text)
    try:
        os.chmod(target, os.stat(target).st_mode | 0o111)
    except OSError:
        pass  # Windows has no execute bit; Git for Windows runs the hook without one
    return ("updated" if state == "ours" else "written"), str(target)


def _hooks_file_in_work_tree(hook_file: Path) -> tuple[str, str] | None:
    """(the file, its folder) relative to the top of the working tree when the hooks folder lies inside the working
    tree (`.githooks/pre-commit`, `.githooks`); None for `.git/hooks`, a folder elsewhere, or without git."""
    try:
        res = subprocess.run(["git", "rev-parse", "--is-inside-work-tree", "--show-toplevel"], cwd=str(hook_file.parent),
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        out = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if res.returncode != 0 or len(out) < 2 or out[0] != "true":
            return None
        rel = os.path.relpath(os.path.realpath(hook_file), os.path.realpath(out[1])).replace("\\", "/")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None if rel.startswith("..") else (rel, rel.rsplit("/", 1)[0] if "/" in rel else ".")


def pre_commit_report(state: str, where: str) -> tuple[int, list[str]]:
    """The exit code and the lines `install-pre-commit` prints (the skill's `init --pre-commit` prints the same)."""
    local = ("Local only: hooks are not cloned with a repository, so each clone runs `python scripts/scope_guard.py "
             "install-pre-commit` once; `git commit --no-verify` skips it; the pull request check reads the diff again. "
             "A review aid, not a security boundary.")
    done = {"written": "installed", "updated": "updated (it was an older LUMIS copy)", "unchanged": "already installed"}
    if state in done:
        in_tree = _hooks_file_in_work_tree(Path(where))
        if in_tree:  # untracked, `git clean -fd` or `git stash -u` takes it away; committed, teammates get it
            local =(f"This hooks folder is inside the working tree: commit the file (`git add {in_tree[0]} && git "
                     f"commit`). Teammates get it with the repository once they run `git config core.hooksPath "
                     f"{in_tree[1]}` in their clone, and `git clean` / `git stash -u` leave a tracked file alone. "
                     "`git commit --no-verify` skips it; the pull request check reads the diff again. A review aid, "
                     "not a security boundary.")
        return 0, [f"pre-commit check {done[state]}: {where} — each `git commit` here reads the staged change against "
                   ".lumis/scope_guard.json as committed and refuses the commit on BLOCK (or when the check could not "
                   "run).", local]
    if state == "foreign":
        return 1, [f"{where} already exists and is not the LUMIS check: left as it is. Add this line to it (python "
                   "or py -3 where python3 is not the interpreter):", f"  {PRE_COMMIT_LINE}"]
    if state == "framework":
        return 0, ["This repository uses the pre-commit framework (.pre-commit-config.yaml): not installed by us. Add "
                   "this under `repos:` in .pre-commit-config.yaml, then run `pre-commit install`:",
                   PRE_COMMIT_FRAMEWORK_SNIPPET]
    if state == "husky":
        return 0, ["This repository uses husky (.husky/): not installed by us. Add this line to .husky/pre-commit "
                   "(python or py -3 where python3 is not the interpreter):", f"  {PRE_COMMIT_LINE}"]
    if state == "subfolder":
        return 1, [f"scripts/scope_guard.py is not at the top of this repository ({where}): git runs the pre-commit "
                   "hook from there, and the check reads scripts/scope_guard.py and .lumis/scope_guard.json there. "
                   "Nothing was written."]
    if state == "shared":
        return 1, [f"{where} is outside this repository (a global or shared core.hooksPath): other repositories run "
                   "their hooks from that folder too, so nothing was written. To use the check here, give this "
                   "repository its own hooks folder (`git config core.hooksPath .githooks`), run install-pre-commit "
                   "again, and commit .githooks/pre-commit."]
    if state == "removed":
        return 0, [f"pre-commit check removed: {where}"]
    if state == "kept":
        return 1, [f"{where} is not the LUMIS check: left as it is (--uninstall removes only our own file)"]
    if state == "absent":
        return 0, ["no LUMIS pre-commit check is installed here: nothing to remove"]
    return 1, ["not inside a git repository (or git was not found): nothing was written. Run it in the repository."]


def pre_commit_command(argv: list[str]) -> int:
    """`python scripts/scope_guard.py install-pre-commit [--uninstall] [--root <dir>]`."""
    args = [str(a) for a in (argv or [])]
    if any(a in ("--help", "-h", "help") for a in args):
        print(PRE_COMMIT_USAGE)
        return 0
    root, uninstall, i = project_root(), False, 0
    while i < len(args):
        a = args[i]
        if a == "--uninstall":
            uninstall, i = True, i + 1
        elif a == "--root" and i + 1 < len(args):
            root, i = Path(args[i + 1]), i + 2
        elif a.startswith("--root="):
            root, i = Path(a.split("=", 1)[1]), i + 1
        else:
            print(f"unknown argument {a}\n{PRE_COMMIT_USAGE}", file=sys.stderr)
            return 1
    code, lines = pre_commit_report(*install_pre_commit(root, uninstall=uninstall))
    for line in lines:
        print(line)
    return code


def pre_commit_doctor_line(root: Path) -> str:
    """One line for `doctor`: installed / not installed / another hook is in the way."""
    state, target = pre_commit_state(root)
    if state == "ours":
        stale = target is not None and target.read_bytes() != PRE_COMMIT_SCRIPT.encode("utf-8")
        return (f"  ✓ pre-commit check installed ({target})"
                + (" — an older LUMIS copy: `python scripts/scope_guard.py install-pre-commit` updates it" if stale else ""))
    if state == "foreign":
        return (f"  – pre-commit check not installed: another pre-commit hook is in the way ({target}); "
                "`python scripts/scope_guard.py install-pre-commit` prints the line to add to it")
    if state == "absent":
        return ("  – pre-commit check not installed (optional, local: `python scripts/scope_guard.py install-pre-commit`)")
    return "  – pre-commit check: not a git repository here (or git was not found)"


# The pre-tool hook guards the pre-commit check it installed against an agent that DRIFTS, not an adversary: the
# pull request check is the server-side one, and this is a review aid, not a security boundary. Only where OUR
# pre-commit is installed (`installed_pre_commit`); everywhere else every call is judged exactly as before.
# It holds the plain spellings of a commit past the check for the founder (ask, never `classes`): `git commit
# --no-verify` / `-n` (also inside `-anm`), `git -c core.hooksPath=… commit` and `--config-env core.hooksPath=…`, a
# `git commit` in a command that sets a GIT_CONFIG_* variable, a `git config` write of core.hooksPath (set or unset,
# any scope), `git commit-tree`, and a write to this repository's own `.git/config` or `config.worktree`. It refuses as
# `tamper` a direct delete, move, overwrite or chmod of our file named by its path, or of the folder that holds it;
# `install-pre-commit --uninstall` names the hook script, so it is refused like every other founder-only word.
# Not seen, on purpose (docs/BOUNDARY_CHECK_CI.md, "Limits"): config includes, HOME / XDG_CONFIG_HOME pointing git at
# another config, a script writing git's config, a glob or variable that hides the name, aliases, other plumbing,
# `git clean` / `git stash -u` of an untracked hooks folder in the working tree. `doctor` shows whether the check is
# in place, and the pull request check reads the diff whatever happened locally.
_HOOKS_MENTION_RE = re.compile(r"pre-commit|hook|\.git(?![\w.\-])", re.I)
_COMMIT_MENTION_RE = re.compile(r"\bcommit\b|hookspath|\.git[\\/]config\b|config\.worktree\b", re.I)
# a GIT_CONFIG_* variable set in the command (`X=… git`, `export`, `env`, PowerShell's `$env:`): it adds config git
# reads before the repository's own, core.hooksPath included
_GIT_CONFIG_ENV_RE = re.compile(r"(?<![\w-])GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+|PARAMETERS|GLOBAL|SYSTEM)\s*=", re.I)
# commands that write only their last argument: `cp -r .git/hooks /tmp/backup` reads the hooks folder
DESTINATION_LAST = {"cp", "copy", "copy-item", "cpi", "install", "rsync", "scp"}
GIT_COMMIT_VALUE_SHORT = "mFcCt"   # `-m <msg>`, `-F <file>`, `-c|-C <commit>`, `-t <file>`: the rest is the value
GIT_COMMIT_OPTIONAL_SHORT = "Su"   # `-S[<keyid>]`, `-u[<mode>]`: what follows in the same word is their value
GIT_COMMIT_VALUE_LONG = ("--message", "--file", "--author", "--date", "--template", "--cleanup", "--fixup", "--squash",
                         "--reuse-message", "--reedit-message", "--trailer", "--pathspec-from-file")
PRE_COMMIT_SKIP_REASONS = {
    "git commit --no-verify": "this commits past the LUMIS pre-commit check: the staged change is not read against the "
                              "boundaries",
    "git -c core.hooksPath commit": "this commit runs its hooks from another folder: the LUMIS pre-commit check does not run",
    "git config core.hooksPath": "this changes where git looks for hooks: the LUMIS pre-commit check may stop running",
    "git commit with GIT_CONFIG_*": "this commit runs with config set through GIT_CONFIG_* variables, which can move "
                                    "its hooks to another folder: the LUMIS pre-commit check may not run",
    "git commit-tree": "this writes a commit without `git commit`: no pre-commit hook runs, the LUMIS check included",
    "write to git's config file": "this writes this repository's own git config file directly, where core.hooksPath "
                                  "can move the hooks away from the LUMIS pre-commit check",
}


def installed_pre_commit(root: Path | None = None) -> Path | None:
    """Our pre-commit file where it is installed for `root` (default: the project), else None. It runs git, so the
    callers ask only when the call could concern it."""
    scan_checkpoint()
    try:
        state, target = pre_commit_state(root or project_root())
    except Exception:
        return None
    return target if state == "ours" else None


def _as_absolute(token: str, base: str) -> str:
    """A cleaned path (`_clean_path`) made absolute against `base` (cleaned too); Git Bash's `/c/…` is `c:/…`."""
    t = str(token or "")
    if os.name == "nt" and re.match(r"^/[a-z](?:/|$)", t):
        t = t[1] + ":" + (t[2:] or "/")
    if re.match(r"^[a-z]:/", t) or t.startswith("/"):
        return t
    if t.startswith("~/"):
        return _clean_path(os.path.expanduser("~") + t[1:])
    return _clean_path(base + "/" + t)


def _archive_only_reads(exe: str, raw_args: list[str]) -> bool:
    """`tar czf x.tgz .git`, `zip -r x.zip .git`, `7z a x.7z .git`: an archiver creating an archive reads its inputs."""
    if exe == "zip":
        return True
    if exe in ("7z", "7za"):
        return raw_args[:1] == ["a"]
    # tar's mode comes first: `czf`, `-czf`, `--create`
    return exe == "tar" and bool(raw_args) and bool(re.fullmatch(r"--create|-?[A-Za-z]*c[A-Za-z]*", raw_args[0]))


def pre_commit_tamper(command: str = "", paths: list[str] | tuple = ()) -> list[str]:
    """`["<path> (the LUMIS pre-commit check)"]` when a file tool's paths name our pre-commit file, or a shell command
    names it by its path (or a glob that matches it) to delete, move, overwrite or chmod it — or removes or moves the
    folder that holds it — else []. A copy or a move writes only its last argument; an archiver creating an archive and
    a git command other than rm/mv/checkout/restore/clean/reset only read. Reading never reaches here (check_tamper
    returns before)."""
    if not _HOOKS_MENTION_RE.search(str(command or "") + "\n" + "\n".join(str(p) for p in paths)):
        return []
    root = project_root()
    hook = installed_pre_commit(root)
    if hook is None:
        return []
    real = os.path.realpath(hook)
    base = _clean_path(os.path.realpath(root))
    target = _clean_path(real)
    try:
        rel = os.path.relpath(real, os.path.realpath(root)).replace("\\", "/")
    except ValueError:  # another drive on Windows
        rel = ""
    label = f"{rel if rel and not rel.startswith('..') else real} (the LUMIS pre-commit check)"
    holders = {_clean_path(os.path.dirname(real))}
    git_dir = os.path.dirname(os.path.dirname(real))
    if os.path.basename(os.path.dirname(real)).lower() == "hooks" and _clean_path(git_dir) != base:
        holders.add(_clean_path(git_dir))  # `.git` itself; never the project root (`cp -r . backup` is no rewrite)

    def reaches(raw: str, folder_too: bool) -> bool:
        raw = re.sub(r"^\d*>+", "", raw)  # `echo x >.git/hooks/pre-commit`: the redirect glued to its target
        if not raw:
            return False
        p = _as_absolute(_clean_path(raw), base)
        if p == target or (folder_too and p in holders):
            return True
        if any(ch in p for ch in GLOB_CHARS):  # `rm .git/hooks/*`, `rm .git/hooks/pre-comm?t` (review 2026-10-01)
            return _glob_matches(target, p) or (folder_too and any(_glob_matches(h, p) for h in holders))
        try:
            candidate = raw if os.path.isabs(raw) else os.path.join(str(root), raw)
            return os.path.lexists(candidate) and _clean_path(os.path.realpath(candidate)) == target
        except (OSError, ValueError):
            return False

    for raw in paths:
        if raw and reaches(str(raw), False):
            return [label]
    if command:
        # `(cd .git/hooks && rm -f pre-commit)`: the subshell's parentheses off, its `cd` applies like any other
        text = re.sub(r"(?<![$\w])\(|\)(?=\s*(?:$|[;&|\n]))", " ", command)
        raw_segments = [[w.strip("'\"`") for w in s.split()] for s in SEGMENT_SPLIT.split(text) if s.strip()]
        raw_segments = [w for w in raw_segments if _exe_name(w[0]) != "cd"]  # command_segments drops `cd` too
        for (exe, args, _prefix), raw in zip(command_segments(text), raw_segments):
            if exe == "find":
                if _find_reaches_pre_commit(raw[1:], base, target):
                    return [label]
                continue
            if _archive_only_reads(exe, raw[1:]) or (exe == "git" and not any(a in GIT_MUTATORS for a in args[:2])):
                continue
            if any(reaches(a, exe in DIR_MUTATORS) for a in (args[-1:] if exe in DESTINATION_LAST else args)):
                return [label]
        if PRE_COMMIT_BY_VARIABLE.search(command):
            return [f"{label} (named in the command text)"]
    return []


# `rm $(git rev-parse --git-path hooks)/pre-commit`, `H=.git/hooks; rm $H/pre-commit`, `rm -rf "$(git rev-parse
# --git-dir)/hooks"`: the hook file spelled through a substitution or a variable, which no path comparison resolves
# (review 2026-10-01). Both spellings count only in a segment that runs a remover, a mover or chmod:
# `$BIN/pre-commit run --all-files` is the pre-commit framework's own program. A command that is only a look never
# reaches here (check_tamper returns before).
PRE_COMMIT_BY_VARIABLE = re.compile(
    r"\b(?:rm|rmdir|mv|chmod|unlink|remove-item|ri|del|rd)\b[^;&|\n]*(?:"
    r"\$(?:\{?\w+\}?|\([^)]*\))[\"']?/(?:hooks/)?pre-commit(?![\w.\-])"
    r"|\$\(\s*git\s+rev-parse[^)]*"
    r"(?:--git-path\s+[\"']?hooks|--git-dir|--git-common-dir)[^)]*\)[\"']?(?:/hooks)?/?[\"']?(?:\s|$))",
    re.I)


def _find_reaches_pre_commit(args: list[str], base: str, target: str) -> bool:
    """`find .git/hooks -delete`, `find .git -name pre-commit -delete`, `find . -exec rm {} +`: a find whose start
    holds the hook file, whose name filter (if any) can match it, and whose action rewrites. `find . -name '*.pyc'
    -delete` does not reach it."""
    low = [a.lower() for a in args]
    mutating = "-delete" in low or any(a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(low)
                                       and low[i + 1].rsplit("/", 1)[-1] in FIND_MUTATORS for i, a in enumerate(low))
    if not mutating:
        return False
    starts = low[: next((i for i, a in enumerate(low) if a.startswith("-")), len(low))] or ["."]
    names = [low[i + 1] for i, a in enumerate(low) if a in ("-name", "-iname") and i + 1 < len(low)]
    paths = [low[i + 1] for i, a in enumerate(low) if a in ("-path", "-ipath", "-wholename") and i + 1 < len(low)]
    for start in starts:
        st = _as_absolute(_clean_path(start), base).rstrip("/")
        if not (target == st or target.startswith(st + "/")):
            continue
        shown = start.rstrip("/") + target[len(st):]  # the path as find prints it: `.git/hooks/pre-commit`
        if not names and not paths:
            return True
        if any(fnmatch.fnmatchcase(target.rsplit("/", 1)[-1], n) for n in names) \
                or any(fnmatch.fnmatchcase(shown, p) for p in paths):
            return True
    return False


def _commit_skips_verify(after: list[str]) -> bool:
    """`git commit` arguments that skip the pre-commit hook: `--no-verify` (or an abbreviation git accepts), `-n`,
    also inside a cluster (`-nm`, `-anm "msg"`). A value is not a flag: `-m "-n"`, `-m -n`, `--message=-n`, `-mn`
    (the message "n"); `--no-edit` is another option; nothing after `--` is an option."""
    i = 0
    while i < len(after):
        a = after[i]
        i += 1
        if a == "--":
            return False
        if a.startswith("--"):
            name = a.split("=", 1)[0].lower()
            if len(name) >= len("--no-veri") and "--no-verify".startswith(name):
                return True
            if "=" not in a and len(name) > 3 and any(v.startswith(name) for v in GIT_COMMIT_VALUE_LONG):
                i += 1  # the value is the next word
            continue
        if a.startswith("-") and len(a) > 1:
            cluster = a[1:]
            for j, ch in enumerate(cluster):
                if ch == "n":
                    return True
                if ch in GIT_COMMIT_VALUE_SHORT:
                    if j == len(cluster) - 1:
                        i += 1  # `-m <msg>`: the next word is the value
                    break
                if ch in GIT_COMMIT_OPTIONAL_SHORT:
                    break
    return False


def _config_env_hooks_path(args: list[str]) -> bool:
    """`git --config-env=core.hooksPath=VAR …` / `git --config-env core.hooksPath=VAR …`: the `-c` setting with its
    value read from a variable."""
    for i, a in enumerate(args):
        if not a.startswith("-"):
            return False
        value = a.split("=", 1)[1] if a.lower().startswith("--config-env=") else (
            args[i + 1] if a.lower() == "--config-env" and i + 1 < len(args) else "")
        if value.split("=", 1)[0].lower() == "core.hookspath":
            return True
    return False


def _git_config_candidates(words: list[str]) -> list[str]:
    """The words that could be a git config file by their name (`config`, `config.worktree`), a glued redirect off."""
    out = []
    for w in words:
        p = re.sub(r"^\d*>+", "", str(w or "").strip().strip("'\"`"))
        if p.replace("\\", "/").rsplit("/", 1)[-1].lower() in ("config", "config.worktree"):
            out.append(p)
    return out


def _is_own_git_config(paths: list[str]) -> bool:
    """True when one of `paths` (relative ones against the project) is THIS repository's own config or
    `config.worktree` as `git rev-parse --git-path` names them (the common git dir's config, a linked worktree's own
    config.worktree) — resolved and case-normalised. Not ~/.gitconfig, a fixture named `.gitconfig`, another tree's
    `.git/config`."""
    if not paths:
        return False
    root = project_root()
    try:
        res = subprocess.run(["git", "rev-parse", "--git-path", "config", "--git-path", "config.worktree"],
                             cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        norm = lambda p: os.path.normcase(os.path.realpath(root / os.path.expanduser(p.strip())))
        own = {norm(line) for line in res.stdout.splitlines() if line.strip()} if res.returncode == 0 else set()
        return any(norm(p) in own for p in paths)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def pre_commit_skips(tool_name: str, tool_input: dict) -> list[str]:
    """What in a call steps around OUR pre-commit check, where it is installed — the plain spellings only: "git
    commit --no-verify", "git -c core.hooksPath commit" (`--config-env` too), "git commit with GIT_CONFIG_*", "git
    config core.hooksPath" (any write of that key), "git commit-tree", "write to git's config file" (this repository's
    own, by a shell command or a file tool). [] for any other call, and wherever ours is not installed — the git
    question (`installed_pre_commit`) is asked only when the call has such a step."""
    tool_input = tool_input or {}
    if not is_command(tool_name, tool_input):
        if is_read_only_tool(tool_name, tool_input):
            return []
        targets = [p for p in [text_of_tool_input(tool_name, tool_input)[1]] + destination_paths(tool_name, tool_input) if p]
        named = _git_config_candidates(targets)
        if named and installed_pre_commit() is not None and _is_own_git_config(named):
            return ["write to git's config file"]
        return []
    command = str(tool_input.get("command", ""))
    if not _COMMIT_MENTION_RE.search(command) or is_read_only_command(command):
        return []
    # a commit message and a heredoc body are data; the `-m ""` left in their place keeps a word, so `-m` does not
    # take the next flag as its value
    text = re.sub(r"(?<=\s)(?:\"\"|'')(?=\s|$)", "_", _command_without_data(command, files_too=True))
    env_config = bool(_GIT_CONFIG_ENV_RE.search(text))
    found: list[str] = []
    config_words: list[str] = []  # what a non-git command writes: `>> .git/config`, `sed -i … .git/config`, `cp x …`
    for tokens in _command_words(text):
        if tokens[:1] == ["&"]:
            tokens = tokens[1:]  # PowerShell's call operator: `& git commit -n`
        # `$(git commit-tree …)` inside another git command is one word list with the substitution's words in it
        if any(t.lower() == "commit-tree" and _exe_name(prev.lstrip("$(")) == "git" for prev, t in zip(tokens, tokens[1:])):
            if "git commit-tree" not in found:
                found.append("git commit-tree")
        if not tokens:
            continue
        exe = _exe_name(tokens[0])
        if exe != "git":
            # a copy or a move writes only its last word: `cp .git/config /tmp/x` reads it
            config_words += _git_config_candidates(tokens[-1:] if exe in DESTINATION_LAST | {"mv", "move", "move-item", "mi"}
                                                   else tokens[1:])
            continue
        sub, after, settings = _git_subcommand(tokens[1:])
        hit = ""
        if sub == "commit" and _commit_skips_verify(after):
            hit = "git commit --no-verify"
        elif sub == "commit" and (any(s.split("=", 1)[0].lower() == "core.hookspath" for s in settings)
                                  or _config_env_hooks_path(tokens[1:])):
            hit = "git -c core.hooksPath commit"
        elif sub == "commit" and env_config:
            hit = "git commit with GIT_CONFIG_*"
        elif sub == "commit-tree":
            hit = "git commit-tree"
        elif sub == "config" and git_config_writes(after) and _git_config_key(after).lower() == "core.hookspath":
            hit = "git config core.hooksPath"  # set or unset, any scope, any value: a rare extra ask, never a wrong pass
        if hit and hit not in found:
            found.append(hit)
    if not (found or config_words) or installed_pre_commit() is None:
        return []
    if _is_own_git_config(config_words):
        found.append("write to git's config file")
    return found


def pre_commit_skip_reason(what: str) -> str:
    return (f"pre-commit '{what}' — " + PRE_COMMIT_SKIP_REASONS.get(what, "this steps around the LUMIS pre-commit check")
            + "; skipping it is the founder's decision, not the agent's")


def parse_args(argv: list[str]) -> tuple[str, str]:
    """(mode, agent). `--agent <name>` is optional: the payload itself says which client called us."""
    mode = "pre-tool"
    agent = ""
    rest = [a for a in argv[1:]]
    if rest and (not rest[0].startswith("-") or rest[0] in ("--help", "-h")):
        mode = rest.pop(0)
    while rest:
        arg = rest.pop(0)
        if arg == "--agent" and rest:
            agent = rest.pop(0).strip().lower()
        elif arg.startswith("--agent="):
            agent = arg.split("=", 1)[1].strip().lower()
    return mode, agent


USAGE = """LUMIS Scope Guard — scripts/scope_guard.py <mode>
  report            what the guard did (counts, the last events, the founder's requests)
  doctor            is the guard wired up here: files, interpreters, manifest, baseline, hook version
  request --reason  write a request to the founder about the last refusal or hold (.lumis/requests/)
  observe on|off    founder only, from the founder's own terminal: record without refusing
  write-manifest    founder only: re-baseline the guard files after an Amend or a deliberate edit
  rebuild-markers   founder only: re-derive the markers from the boundaries ([--dry-run])
  check-diff        the same boundaries on a diff (CI): --base <ref> [--head <ref>] | --diff <file> | stdin; exit 2 = BLOCK;
                    --staged: the staged change against HEAD (the pre-commit check); --format text for a terminal
  install-pre-commit  founder only: write the git pre-commit hook that runs check-diff --staged ([--uninstall])
  pre-tool, prompt  run by the client's hooks, never by hand"""


def refuse_unfinished(cfg: dict, agent: str, tool_name: str, tool_input: dict) -> int:
    """The call whose reading ran past SCAN_BUDGET_SECONDS: refused (exit 2) and logged as `timeout` — a guard that
    cannot finish must not pass what it did not read. In observe mode it is recorded and let through, like every
    other refusal there."""
    read, total = _SCAN["read"], _SCAN["total"]
    message = (f"⛔ LUMIS Scope Guard could not finish reading this change within {SCAN_BUDGET_SECONDS:g} s ({read} lines "
               f"read of {total}): refused, not passed. Split the change, or run the guard on the file directly.")
    attempted = text_of_tool_input(tool_name, tool_input)[0] or str((tool_input or {}).get("command", ""))
    reason = [f"not read within {SCAN_BUDGET_SECONDS:g} s ({read} of {total} lines)"]
    if guard_mode(cfg) == "observe":
        sys.stderr.write("👁 OBSERVE (nothing blocked): would have refused this — " + message + "\n")
        log_event(cfg, "timeout", tool_name, tool_input, reason, agent, attempted=attempted, observed=True)
        return 1
    emit_denial(agent, message)
    log_event(cfg, "timeout", tool_name, tool_input, reason, agent, attempted=attempted)
    return 2


def main() -> int:
    started = time.monotonic()  # the budget counts from here (`start_scan_budget`)
    mode, agent = parse_args(sys.argv)
    cfg = load_config()
    if mode in ("--help", "-h", "help"):
        print(USAGE)
        return 0
    if mode == "check-diff":  # CI and a read-only look: no log line, no baseline, nothing written but the named reports
        return check_diff(sys.argv[2:])
    if mode == "install-pre-commit":  # the founder's, from their own terminal; the hook refuses it to the agent (tamper)
        return pre_commit_command(sys.argv[2:])
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
    if mode == "observe":  # the founder switches refusing off and on; the hook refuses this to the agent
        switch = next((a.lower() for a in sys.argv[2:] if not a.startswith("-")), "")
        if switch not in ("on", "off"):
            print("usage: python scripts/scope_guard.py observe on|off   (now: " + guard_mode(cfg) + ")", file=sys.stderr)
            return 1
        return set_observe(project_root(), switch == "on")
    # first contact: the installed state is recorded outside the repository before any tool call is judged
    record_baseline_if_absent(project_root())
    payload = read_stdin_json()
    tool_name, tool_input, prompt, detected = normalize_payload(payload)
    agent = agent or detected or "claude"
    if mode == "prompt" or (not tool_name and prompt):
        # the earliest signal: the request itself names a boundary. The prompt hook cannot block a tool call — none
        # has happened yet — so it advises and records. It used to order the agent to "say so and stop: do not plan
        # it" on any hit, a lone word included, and the founder's agent refused ordinary work because a word of a
        # Non-Goal sentence was in the request (2026-09-23). Only what names the boundary itself counts here: a
        # forbidden package, a forbidden path, a multi-word phrase. The hook still refuses the tool call that crosses.
        asked = match_triggers(cfg, prompt, kinds=("package", "path", "phrase"), prose=True)
        if asked:
            print(
                "🔎 LUMIS Scope Guard: this request mentions a boundary from CONSTITUTION.md — "
                + "; ".join(asked)
                + ". Check the Non-Goal before acting: if the request really is the ruled-out feature, tell the founder "
                  "instead of building it; if it is ordinary work, carry on."
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
    start_scan_budget(SCAN_BUDGET_SECONDS, started)
    try:
        code = pre_tool(cfg, agent, tool_name, tool_input)
        if code != 2:
            scan_checkpoint()  # the parts no reader watches (the classes, the warnings) count against the budget too
        return code
    except ScanBudgetExceeded:
        return refuse_unfinished(cfg, agent, tool_name, tool_input)
    finally:
        stop_scan_budget()


def pre_tool(cfg: dict, agent: str, tool_name: str, tool_input: dict) -> int:
    """The verdict on one tool call (`main`, pre-tool mode): the exit code, with the refusal, the question or the
    warnings written. Reads under the clock `main` armed: a reading past the budget raises ScanBudgetExceeded."""
    command = str((tool_input or {}).get("command", ""))
    attempted_text, tool_path = text_of_tool_input(tool_name, tool_input)
    # the two exemptions a block already has: looking is not doing, and writing a boundary down is inside it.
    # A possible match must not nag about them either, or the founder learns to ignore the guard's stderr.
    looking = (is_command(tool_name, tool_input) and is_read_only_command(command)) or is_read_only_tool(tool_name, tool_input)
    # an ignore file (.gitignore, .dockerignore, …) names what a tool skips: like a document, it builds nothing
    documenting = not is_command(tool_name, tool_input) and (is_prose_path(tool_path) or is_ignore_file(tool_path))
    warnings: list[str] = []
    # one reading of the call for all three answers below (`check_pre_tool`, `check_written_down`,
    # `check_warn_markers` are this, rendered): a long Write is read once, not three times
    judged = judge_tool_input(cfg, tool_name, tool_input)
    marker_hits = [] if (looking or documenting) else sorted({possible_line(cfg, trigger, why)
                                                              for _kind, trigger, why in judged["warn"]})
    if marker_hits:
        warnings.append(
            "🔎 LUMIS Scope Guard — for you to judge (this is not a violation): "
            + "; ".join(marker_hits)
            + ". A single word out of a Non-Goal sentence, or a word found only inside another tool's option or a "
              "library's module name, is a hint, not proof: if this really is the feature the founder ruled out, stop and ask; "
              "if it is ordinary work, carry on — nothing is blocked.")
    # what the reading left unread for packages (a text past 1 MB, the file around an Edit past 1 MB, the edits past
    # the cap): a possible match with its reason — a WARN, never a pass in silence (third review of 30.09)
    unread = [] if (looking or documenting) else unread_lines(judged)
    if unread:
        warnings.append("🔎 LUMIS Scope Guard — possible match, for you to judge: part of this change was not read for "
                        "packages (" + "; ".join(judged.get("unread") or []) + "). A forbidden package named there "
                        "would not be seen: check that part yourself, or split the change. Nothing is blocked.")
    possible = marker_hits + unread
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
        # the git pre-commit file is not written by Amend: its own tail names who writes it (review 2026-10-01)
        only_pre_commit = all("(the LUMIS pre-commit check)" in t for t in tampered)
        emit_denial(agent,
                    "⛔ LUMIS Scope Guard blocked a change to the guard itself: " + ", ".join(tampered)
                    + (". That file is written by the founder with `python scripts/scope_guard.py install-pre-commit` "
                       "and removed with its `--uninstall`, from the founder's own terminal — not by the agent. "
                       if only_pre_commit else
                       ". The boundaries are lifted by the founder through LUMIS Amend, which regenerates these files "
                       "together — not by editing the hook, its config or the constitution. ")
                    + "Ask the founder instead of working around it.")
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
    hits = render_hits(cfg, judged["block"])  # check_pre_tool
    # what only a commit message or a note appended to a document names: the boundary written down, not crossed
    in_data = [] if hits else check_data_mentions(cfg, tool_name, tool_input)
    # what comment lines or an ignore file write down and no line blocks on (2026-09-29). When a line of the same
    # content is a possible match (`marker_hits`), both are shown: the Write is not "only documenting" then.
    in_notes = [] if (hits or in_data) else render_hits(cfg, judged["noted"])
    if (hits or in_data) and looking:
        # the agent is looking, not building: allow it and record that a boundary area was inspected
        log_event(cfg, "inspected", tool_name, tool_input, hits or in_data, agent, attempted=command or attempted_text)
        return 1 if warnings else 0
    noted = False
    if (hits and documenting) or in_data or in_notes:
        # documenting a boundary is not crossing it: the ADR that explains the Non-Goal, the README line restating
        # it and the test that asserts the feature is absent were all refused as violations of the boundary they
        # were writing down — and each refusal then argued in the Amend dialog for lifting it (audit 2026-09-15).
        # A commit message that explains a boundary is the same thing (audit 2026-09-23), and so is a comment in
        # code or a line of .gitignore (2026-09-29).
        written = hits or in_data or in_notes
        where = ("file" if hits else "command's message or note" if in_data
                 else "file's comments (or ignore file)")
        if in_notes and marker_hits:
            # a line of this Write is also a possible match: the file is not only writing the boundary down, and
            # saying so would hide the warning above (review 2026-09-29) — both are shown and both are logged
            sys.stderr.write("📝 LUMIS Scope Guard: comment lines of this file (or its ignore-file lines) name a Non-Goal ("
                             + "; ".join(written) + "): written down there, not crossed, and logged as `noted`. The "
                             "possible match above is a separate line — judge it on its own.\n")
        else:
            sys.stderr.write("📝 LUMIS Scope Guard: this " + where
                             + " writes a Non-Goal down (" + "; ".join(written)
                             + "). Documenting or testing a boundary is inside it — only the code that crosses it is not. "
                               "Allowed and logged as `noted`.\n")
        log_event(cfg, "noted", tool_name, tool_input, written, agent, attempted=attempted_text or command)
        hits, noted = [], True
        # no early return: the same call can still add a dependency, push, or write outside the project
    # observe mode: every refusal and every hold below becomes a warning and a journal line under its own name. The
    # tamper refusal above is deliberately not here — the guard's own files are not a boundary, and a mode that let
    # the agent rewrite the hook would be an off switch, not an observation.
    observing = guard_mode(cfg) == "observe"
    if hits:
        message = ("⛔ LUMIS Scope Guard blocked this change (CONSTITUTION.md, Article I — Non-Goals): "
                   + "; ".join(hits)
                   # "never by bypassing the hook" was the earlier tail: on a screenshot it read as the "cannot be bypassed"
                   # claim the evidence does not support (8 of 77 tamper cases pass). The mechanism is described instead
                   # (founder decision 25.09).
                   + ". The boundary is lifted by the founder (LUMIS Amend / a new consilium run), not by editing the hook or its config.")
        if observing:
            sys.stderr.write("👁 OBSERVE (nothing blocked): would have blocked this — " + message + "\n")
            log_event(cfg, "blocked", tool_name, tool_input, hits, agent, attempted=attempted_text, observed=True)
            return 1
        emit_denial(agent, message)
        log_event(cfg, "blocked", tool_name, tool_input, hits, agent, attempted=attempted_text)
        return 2
    active = [(c, w) for c, w in check_classes(cfg, tool_name, tool_input) if class_verdict(cfg, c) != "allow"]
    # a commit that steps around the LUMIS pre-commit check (`--no-verify`, `-n`, another hooks folder) where it is
    # installed: held for the founder like a class set to `ask`, whatever `classes` says (hook 2026-10-01)
    skips = pre_commit_skips(tool_name, tool_input)
    if active or skips:
        blocking = any(class_verdict(cfg, c) == "block" for c, _w in active)
        message = class_message(active, blocking, skips)
        labels = [f"{c} '{w}'" for c, w in active] + [f"pre-commit '{s}'" for s in skips]
        # "asked" is taken — it is the prompt hook's event — so a call handed to the founder is `held`
        event = "blocked" if blocking else "held"
        if observing:
            sys.stderr.write("👁 OBSERVE (nothing blocked): would have " + ("blocked this — " if blocking else "asked the founder — ")
                             + message + "\n")
            log_event(cfg, event, tool_name, tool_input, labels, agent, attempted=attempted_text or command, observed=True)
            return 1
        log_event(cfg, event, tool_name, tool_input, labels, agent, attempted=attempted_text or command)
        if blocking:
            emit_denial(agent, message)
            return 2
        return emit_ask(agent, message)
    if noted:
        if (in_notes and marker_hits) or unread:  # a possible match on a line of the same Write is its own record
            log_event(cfg, "possible", tool_name, tool_input, (marker_hits if in_notes else []) + unread, agent,
                      attempted=attempted_text)
        return 1  # otherwise the `noted` line is the record; a documented boundary adds no warned/possible lines
    if design_hits or arch_hits:
        log_event(cfg, "warned", tool_name, tool_input, design_hits + arch_hits, agent, attempted=attempted_text)
    if possible:
        # its own event: `warned` is the visual contract and the architecture, `possible` is a boundary word that
        # may or may not mean anything. The Amend question "lift or keep?" must not be argued by a maybe.
        log_event(cfg, "possible", tool_name, tool_input, possible, agent, attempted=attempted_text)
    return 1 if warnings else 0  # 1 = non-blocking: the warning is shown, the change proceeds


if __name__ == "__main__":
    raise SystemExit(main())
