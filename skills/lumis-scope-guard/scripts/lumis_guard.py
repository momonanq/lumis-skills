#!/usr/bin/env python3
"""LUMIS scope guard — standalone installer and checker (stdlib only).

    python lumis_guard.py init  --project "Name" --non-goals "no marketplace; no multi-tenancy" [--invariants "..."] [--stack "..."] [--root .]
    python lumis_guard.py check --text "the plan or diff to check" [--root .]
    python lumis_guard.py status [--root .]

`init` writes into the repository root: .lumis/scope_guard.json (triggers), .claude/settings.json (deny rules + hooks,
merged into an existing file), scripts/scope_guard.py (the hook), CONSTITUTION.md (Non-Goals and invariants verbatim)
and a LUMIS section in .cursorrules. `check` reports Non-Goal triggers and drift phrases in a text. No network, no model.
Same engine as https://lumis.tools/guard.
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
NON_GOAL_STOPWORDS = {"the", "and", "for", "with", "without", "only", "stage", "mvp", "support", "feature", "features", "integration",
                      "без", "или", "для", "нет", "только", "этапе", "поддержка", "функционал", "интеграция", "приложения", "приложение", "native", "нативные",
                      "never", "no", "not", "any", "this", "that", "release", "phase", "later", "future"}
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
MARK_START = "# --- LUMIS scope guard (generated; edit .lumis/scope_guard.json instead) ---"
MARK_END = "# --- end LUMIS scope guard ---"


def split_items(text: str) -> list[str]:
    parts = re.split(r"[;\n]", text or "")
    out: list[str] = []
    for p in parts:
        t = re.sub(r"^[\s\-*•·\d.)]+", "", p).strip()[:240]
        if len(t) > 2 and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:25]


def guard_config(project: str, non_goals: list[str]) -> dict:
    packages: list[str] = []
    paths: list[str] = []
    keywords: list[str] = []
    matched: dict[str, list[str]] = {}
    for ng in non_goals:
        low = ng.lower()
        for cap, spec in CAPABILITY_TRIGGERS.items():
            if any(m in low for m in spec["match"]):
                packages += spec["packages"]
                paths += spec["paths"]
                keywords += spec["keywords"]
                matched.setdefault(cap, []).append(ng)
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{4,}", low):
            if word not in NON_GOAL_STOPWORDS and word not in keywords:
                keywords.append(word)
    dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
    return {"project": project, "generated": date.today().isoformat(), "source": "lumis-scope-guard skill",
            "non_goals": non_goals, "capabilities": matched, "deny_packages": dedupe(packages), "deny_paths": dedupe(paths),
            "keywords": dedupe(keywords)[:60], "drift_phrases": list(DRIFT_PHRASES), "design_non_goals": []}


def claude_settings(cfg: dict, existing: dict | None) -> dict:
    deny: list[str] = []
    for pkg in cfg.get("deny_packages", []):
        deny += [f"Bash(npm install {pkg}*)", f"Bash(npm i {pkg}*)", f"Bash(pnpm add {pkg}*)", f"Bash(yarn add {pkg}*)", f"Bash(pip install {pkg}*)", f"Bash(uv add {pkg}*)"]
    for path in cfg.get("deny_paths", []):
        deny += [f"Edit({path}**)", f"Write({path}**)"]
    pre = {"matcher": "Edit|Write|MultiEdit|Bash", "hooks": [{"type": "command", "command": "python scripts/scope_guard.py pre-tool"}]}
    prompt = {"hooks": [{"type": "command", "command": "python scripts/scope_guard.py prompt"}]}
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


def upsert_block(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if MARK_START in text and MARK_END in text:
        start, end = text.index(MARK_START), text.index(MARK_END) + len(MARK_END)
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
    cfg = guard_config(project, non_goals)
    (root / ".lumis").mkdir(parents=True, exist_ok=True)
    (root / ".lumis" / "scope_guard.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    const_path = root / "CONSTITUTION.md"
    if const_path.exists() and "LUMIS" not in const_path.read_text(encoding="utf-8"):
        const_path = root / "CONSTITUTION.lumis.md"  # never overwrite a hand-written constitution
    const_path.write_text(constitution(project, non_goals, invariants, stack), encoding="utf-8")
    upsert_block(root / ".cursorrules", cursorrules_section(project, non_goals, invariants, stack))
    print(f"LUMIS scope guard installed in {root}")
    print(f"  Non-Goals: {len(non_goals)} · invariants: {len(invariants)} · deny packages: {len(cfg['deny_packages'])} · deny paths: {len(cfg['deny_paths'])} · keywords: {len(cfg['keywords'])}")
    print("  Files: .lumis/scope_guard.json, .claude/settings.json (merged), scripts/scope_guard.py, " + const_path.name + ", .cursorrules (section)")
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
    hits: list[str] = []
    for kw in cfg.get("keywords", []):
        if kw and re.search(r"(?<![\w-])" + re.escape(kw.lower()) + r"(?![\w-])", low):
            hits.append(f"Non-Goal keyword '{kw}'")
    for pkg in cfg.get("deny_packages", []):
        if re.search(r"(^|[\s'\"/@=])" + re.escape(pkg.lower()) + r"([\s'\"@=:]|$)", low):
            hits.append(f"forbidden dependency '{pkg}'")
    for dp in cfg.get("deny_paths", []):
        if dp and dp.lower() in low:
            hits.append(f"forbidden path '{dp}'")
    drift = [p for p in cfg.get("drift_phrases", []) if p.lower() in low]
    print("Non-Goals in force:")
    for ng in cfg.get("non_goals", []):
        print(f"  - {ng}")
    if hits:
        print("\n⛔ Scope violations:")
        for h in sorted(set(hits)):
            print(f"  - {h}")
    if drift:
        print("\n⚠️ Drift phrases: " + ", ".join(f"'{p}'" for p in drift[:6]) + " — confirm the task is in scope (y/n) before changing code.")
    if not hits and not drift:
        print("\n✅ No Non-Goal triggers or drift phrases found.")
    return 1 if hits else 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    for rel in (".lumis/scope_guard.json", ".claude/settings.json", "scripts/scope_guard.py", "CONSTITUTION.md", ".cursorrules"):
        print(("✓ " if (root / rel).exists() else "✗ ") + rel)
    cfg_path = root / ".lumis" / "scope_guard.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        print(f"Non-Goals: {len(cfg.get('non_goals', []))} · deny packages: {len(cfg.get('deny_packages', []))} · keywords: {len(cfg.get('keywords', []))}")
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
