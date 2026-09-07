#!/usr/bin/env python3
"""Reproduce a real scope-guard block with nothing but this repository and Python (stdlib only, no account, no model).

    python examples/record_block.py

Installs the skill's guard into a temporary folder (the same files `lumis-scope-guard init` writes), then calls the hook
exactly the way Claude Code does — PreToolUse with the tool call as JSON on stdin, CLAUDE_PROJECT_DIR set — for a short
scenario: a prompt with a drift phrase, `pip install stripe`, a file under `billing/`, a file under `marketplace/`, an allowed
edit, then `report`. Everything printed after "hook" is the hook's own output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = next((p / "skills" / "lumis-scope-guard" / "scripts" for p in (HERE.parent, HERE.parent.parent) if (p / "skills" / "lumis-scope-guard" / "scripts" / "lumis_guard.py").exists()),
             HERE.parent / "skills" / "lumis-scope-guard" / "scripts")
SHOWN_ROOT = "~/code/rentguard"

NON_GOALS = "No rent payment collection, insurance or financial guarantees; No marketplace for tenants to search apartments; No native iOS/Android apps"
INVARIANTS = "Every verification report is immutable once issued"
STACK = "FastAPI, SQLite (WAL), React"

STEPS = [
    ("prompt", "Add card payments for rent via Stripe and auto-charge utilities — might as well build a billing module while I'm in here", None),
    ("Bash", "pip install stripe", {"tool_name": "Bash", "tool_input": {"command": "pip install stripe"}}),
    ("Write", "billing/stripe_webhook.py", {"tool_name": "Write", "tool_input": {"file_path": "{root}/billing/stripe_webhook.py", "content": "import stripe\n"}}),
    ("Write", "marketplace/listings.py", {"tool_name": "Write", "tool_input": {"file_path": "{root}/marketplace/listings.py", "content": "# listings\n"}}),
    ("Edit", "backend/api/verifications.py", {"tool_name": "Edit", "tool_input": {"file_path": "{root}/backend/api/verifications.py", "new_string": '@router.get("/api/v1/verifications/{id}")\nasync def get_one(): ...'}}),
    ("report", "", None),
]


def run(repo: Path, mode: str, payload: dict | None) -> tuple[int, str, str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "PYTHONIOENCODING": "utf-8"}
    body = json.dumps(payload).replace("{root}", str(repo).replace("\\", "/")) if payload else ""
    res = subprocess.run([sys.executable, str(repo / "scripts" / "scope_guard.py"), mode], input=body, capture_output=True, text=True, encoding="utf-8", env=env, cwd=repo)
    hide = lambda t: t.replace(str(repo), SHOWN_ROOT).replace(str(repo).replace("\\", "/"), SHOWN_ROOT)
    return res.returncode, hide(res.stdout), hide(res.stderr)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    repo = Path(tempfile.mkdtemp(prefix="lumis-guard-demo-"))
    init = subprocess.run([sys.executable, str(SKILL / "lumis_guard.py"), "init", "--project", "RentGuard", "--non-goals", NON_GOALS,
                           "--invariants", INVARIANTS, "--stack", STACK, "--root", str(repo)], capture_output=True, text=True, encoding="utf-8")
    if init.returncode != 0:
        print(init.stderr)
        return 1
    print(f"# RentGuard — founder's boundaries installed by the lumis-scope-guard skill")
    print(f"$ cd {SHOWN_ROOT}   # .claude/settings.json, .lumis/scope_guard.json, scripts/scope_guard.py, CONSTITUTION.md, .cursorrules, CLAUDE.md\n")
    for kind, label, payload in STEPS:
        if kind == "prompt":
            print(f"you › {label}\n")
            _, out, _ = run(repo, "prompt", {"prompt": label})
            if out.strip():
                print(f"  hook UserPromptSubmit → {out.strip()}\n")
        elif kind == "report":
            print("$ python scripts/scope_guard.py report")
            _, out, _ = run(repo, "report", None)
            print("\n".join("  " + l for l in out.rstrip().splitlines()) + "\n")
        else:
            print(f"claude › {kind}: {label}")
            code, _, err = run(repo, "pre-tool", payload)
            verdict = {2: "BLOCKED (exit 2) — the tool call never runs", 1: "WARNING (exit 1) — the change proceeds", 0: "allowed (exit 0)"}[code]
            print(f"  hook PreToolUse → {verdict}")
            for l in err.rstrip().splitlines():
                print("  " + l)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
