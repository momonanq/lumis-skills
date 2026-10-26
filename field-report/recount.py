"""Recount every number the field report (FIELD_REPORT.md) takes from this folder, from the files in this folder.

    python field-report/recount.py

Standard library only, no network, no model. Prints one row per number: what the article says, what the files give,
and the file it comes from. Exits 1 if any number does not match.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAMPER_RUNS = (
    "tamper/2026-10-08-tamper_cases_77.public-94540b5.stdout.txt",  # the run the article cites
    "tamper/2026-09-29-tamper_cases_77.hook-2026-09-28.stdout.txt",
)


def _text(rel: str) -> str:
    return (HERE / rel).read_text(encoding="utf-8")


def _int(cell: str) -> int:
    """'1 025', '1,025' and '1025' are the same number."""
    return int(re.sub(r"[\s,  ]", "", cell))


def _tables(md: str) -> list[list[list[str]]]:
    """Every Markdown table in `md` as rows of stripped cells (the separator row dropped)."""
    tables, cur = [], []
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                cur.append(cells)
        elif cur:
            tables.append(cur)
            cur = []
    return tables


def _cell(md: str, header_first: str, row_first: str, column: str) -> str:
    """The cell in `column` of the row starting `row_first`, in the first table whose header starts `header_first`."""
    for table in _tables(md):
        if table[0][0] == header_first and column in table[0]:
            for row in table[1:]:
                if row[0] == row_first:
                    return row[table[0].index(column)]
    raise LookupError(f"no table {header_first!r} / row {row_first!r} / column {column!r}")


def bench_runs(series: str) -> list[dict]:
    with (HERE / "bench" / series / "runs.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def tempting_tasks() -> set[str]:
    """Tasks that pull toward a Non-Goal, read from the task tables of bench/METHOD.md: v1 'what it tempts' is not
    'nothing', v2 'Non-Goal' is not 'none'."""
    out = set()
    for table in _tables(_text("bench/METHOD.md")):
        head = table[0]
        if head[:2] == ["slug", "what it tempts"]:
            out |= {r[0].strip("`") for r in table[1:] if r[1] != "nothing"}
        if head[:2] == ["slug", "Non-Goal"]:
            out |= {r[0].strip("`") for r in table[1:] if r[1] != "none"}
    return out


def recount() -> dict:
    n: dict = {}
    # --- bench ---
    runs = {s: bench_runs(s) for s in ("v1", "v2")}
    meta = {s: json.loads(_text(f"bench/{s}/meta.json")) for s in runs}
    n["runs_v1"], n["runs_v2"] = len(runs["v1"]), len(runs["v2"])
    n["runs_total"] = n["runs_v1"] + n["runs_v2"]
    tempting = tempting_tasks()
    n["runs_tempting"] = sum(1 for s in runs for r in runs[s] if r["task"] in tempting)
    n["claude_code"] = meta["v1"]["agent_version"].split()[0]
    n["model"] = meta["v1"]["model_reported"]
    for s in runs:
        n[f"cost_{s}"] = round(meta[s]["reported_cost_usd"], 2)
        n[f"cost_{s}_runs_sum"] = round(sum(float(r["cost_usd"]) for r in runs[s]), 2)
        for arm in ("A", "B"):
            mine = [r for r in runs[s] if r["arm"] == arm]
            counted = [r for r in mine if r["counted"] == "true"]
            n[f"cost_{s}_{arm}"] = round(sum(float(r["cost_usd"]) for r in mine), 2)
            n[f"accept_{s}_{arm}"] = f"{sum(r['tests_ok'] == 'true' for r in counted)}/{len(counted)}"
            n[f"runs_{s}_{arm}"] = len(mine)
    every = [r for s in runs for r in runs[s]]
    n["crossings_hook_matcher"] = sum(int(r["crossings"]) for r in every)
    n["marker_hits_A"] = sum(int(r["marker_crossings"] or 0) for r in every if r["arm"] == "A")
    n["marker_hits_B"] = sum(int(r["marker_crossings"] or 0) for r in every if r["arm"] == "B")
    n["marker_hits_B_where"] = sorted({(r["task"], r["marker_hits"]) for r in every if r["marker_hits"]})
    v1_tot = _text("bench/v1/summary.md")
    v2_tot = _text("bench/v2/summary.md")
    n["summary_cost_v1"] = (_cell(v1_tot, "arm", "A", "reported cost"), _cell(v1_tot, "arm", "B", "reported cost"))
    n["summary_cost_v2"] = (_cell(v2_tot, "arm", "A", "reported cost"), _cell(v2_tot, "arm", "B", "reported cost"))
    # --- field log ---
    log = [json.loads(l) for l in _text("field-log/guard-log.redacted.jsonl").splitlines() if l.strip()]
    events = Counter(e["event"] for e in log)
    n["log_events"] = len(log)
    for ev in ("tamper", "warned", "asked", "blocked"):
        n[f"log_{ev}"] = events.get(ev, 0)
    n["log_tamper_false"] = sum(1 for e in log if e["event"] == "tamper"
                                and e.get("classification", "").startswith("false:"))
    # --- tamper suite ---
    verdicts = []
    for i, rel in enumerate(TAMPER_RUNS):
        text = _text(rel)
        m = re.search(r"^cases: (\d+)\s+refused: (\d+)\s+passed: (\d+)$", text, re.M)
        lines = [l for l in text.splitlines() if l.startswith(("REFUSED", "PASSED"))]
        verdicts.append(lines)
        if i == 0:
            n["tamper_cases"], n["tamper_refused"], n["tamper_passed"] = map(int, m.groups())
            n["tamper_refused_lines"] = sum(l.startswith("REFUSED") for l in lines)
            n["tamper_passed_lines"] = sum(l.startswith("PASSED") for l in lines)
            n["tamper_hook"] = re.search(r"Hook (\d{4}-\d{2}-\d{2})", text).group(1)
            n["tamper_passed_names"] = [" ".join(l.split()[1:]) for l in lines if l.startswith("PASSED")]
        if rel.endswith("hook-2026-09-28.stdout.txt"):
            n["tamper_0928_refused"] = int(m.group(2))
    n["tamper_same_verdicts"] = all(v == verdicts[0] for v in verdicts)
    first = _tables(_text("tamper/HISTORY.md"))[0]
    row = next(r for r in first[1:] if r[0] == "2026-09-11")
    n["tamper_first_cases"], n["tamper_first_refused"] = _int(row[2]), _int(row[3])
    # --- retro calibration ---
    a, b = _text("retro-calibration-A.md"), _text("retro-calibration-B.md")
    before, final = "before (2026-09-28)", "final + 1b"
    n["retro_A_block_prs"] = (_int(_cell(a, "verdict", "BLOCK", before)), _int(_cell(a, "verdict", "BLOCK", final)))
    n["retro_B_block_prs"] = (_int(_cell(b, "verdict", "BLOCK", before)), _int(_cell(b, "verdict", "BLOCK", final)))
    n["retro_B_own_findings"] = (_int(_cell(b, "", "on own files", "before")), _int(_cell(b, "", "on own files", "final + 1b")))
    weak = re.search(r"WARN possible: ([\d\s  ]+?) before and after, ([\d\s  ]+?) on final \+ 1b", b)
    n["retro_B_weak"] = (_int(weak.group(1)), _int(weak.group(2)))
    return n


# (what the article says, key in recount(), the value it says, the file the number comes from)
CLAIMS = [
    ("54 runs", "runs_total", 54, "bench/v1/runs.csv + bench/v2/runs.csv"),
    ("24 runs in series 1", "runs_v1", 24, "bench/v1/runs.csv"),
    ("30 runs in series 2", "runs_v2", 30, "bench/v2/runs.csv"),
    ("36 of them on tasks that pull toward a Non-Goal", "runs_tempting", 36, "bench/METHOD.md task tables + runs.csv"),
    ("Claude Code 2.1.281", "claude_code", "2.1.281", "bench/v1/meta.json"),
    ("claude-sonnet-5", "model", "claude-sonnet-5", "bench/v1/meta.json"),
    ("reported usage $6.11", "cost_v1", 6.11, "bench/v1/meta.json"),
    ("reported usage $7.80", "cost_v2", 7.80, "bench/v2/meta.json"),
    ("$6.11 is the sum of the 24 runs", "cost_v1_runs_sum", 6.11, "bench/v1/runs.csv"),
    ("$7.80 is the sum of the 30 runs", "cost_v2_runs_sum", 7.80, "bench/v2/runs.csv"),
    ("series 1 arm A $2.69", "cost_v1_A", 2.69, "bench/v1/runs.csv (summary.md: $2.69)"),
    ("series 1 arm B $3.42", "cost_v1_B", 3.42, "bench/v1/runs.csv (summary.md: $3.42)"),
    ("series 2 arm A $3.16", "cost_v2_A", 3.16, "bench/v2/runs.csv (summary.md: $3.16)"),
    ("series 2 arm B $4.64", "cost_v2_B", 4.64, "bench/v2/runs.csv (summary.md: $4.64)"),
    ("summary.md totals, series 1", "summary_cost_v1", ("$2.69", "$3.42"), "bench/v1/summary.md"),
    ("summary.md totals, series 2", "summary_cost_v2", ("$3.16", "$4.64"), "bench/v2/summary.md"),
    ("acceptance series 1 arm A 12/12", "accept_v1_A", "12/12", "bench/v1/runs.csv"),
    ("acceptance series 1 arm B 12/12", "accept_v1_B", "12/12", "bench/v1/runs.csv"),
    ("acceptance series 2 arm A 15/15", "accept_v2_A", "15/15", "bench/v2/runs.csv"),
    ("acceptance series 2 arm B 13/13 counted (of 15)", "accept_v2_B", "13/13", "bench/v2/runs.csv, ERRATA.md"),
    ("series 2 arm B had 15 runs", "runs_v2_B", 15, "bench/v2/runs.csv"),
    ("0 boundary crossings (hook matcher, all 54 diffs)", "crossings_hook_matcher", 0, "bench/v*/runs.csv"),
    ("0 task-marker hits in arm A", "marker_hits_A", 0, "bench/v2/runs.csv"),
    ("the only marker hits: arm-B comments on court paperwork", "marker_hits_B", 2, "bench/v2/runs.csv, ERRATA.md"),
    ("29 events", "log_events", 29, "field-log/guard-log.redacted.jsonl"),
    ("18 tamper", "log_tamper", 18, "field-log/guard-log.redacted.jsonl"),
    ("10 warned", "log_warned", 10, "field-log/guard-log.redacted.jsonl"),
    ("1 asked", "log_asked", 1, "field-log/guard-log.redacted.jsonl"),
    ("0 blocked", "log_blocked", 0, "field-log/guard-log.redacted.jsonl"),
    ("at least 6 of the 18 from our rules", "log_tamper_false", ">=6", "field-log/guard-log.redacted.jsonl (classification)"),
    ("77 attempts", "tamper_cases", 77, TAMPER_RUNS[0]),
    ("69 refused", "tamper_refused", 69, TAMPER_RUNS[0]),
    ("8 passed", "tamper_passed", 8, TAMPER_RUNS[0]),
    ("69 REFUSED lines", "tamper_refused_lines", 69, TAMPER_RUNS[0]),
    ("8 PASSED lines", "tamper_passed_lines", 8, TAMPER_RUNS[0]),
    ("current hook 2026-10-07", "tamper_hook", "2026-10-07", TAMPER_RUNS[0]),
    ("hook 2026-09-28 refused the same 69", "tamper_0928_refused", 69, TAMPER_RUNS[1]),
    ("same verdict lines in both runs", "tamper_same_verdicts", True, "tamper/*.stdout.txt"),
    ("began on 11 September with 40 cases", "tamper_first_cases", 40, "tamper/HISTORY.md"),
    ("29 refused on 11 September", "tamper_first_refused", 29, "tamper/HISTORY.md"),
    ("repository A: 5 BLOCK PRs became 1", "retro_A_block_prs", (5, 1), "retro-calibration-A.md"),
    ("repository B: 11 of 40 PRs got a BLOCK, became 2", "retro_B_block_prs", (11, 2), "retro-calibration-B.md"),
    ("repository B: 94 own-file BLOCK findings became 0", "retro_B_own_findings", (94, 0), "retro-calibration-B.md"),
    ("weak single-word warnings 207 to 1,025", "retro_B_weak", (207, 1025), "retro-calibration-B.md"),
]


def check(numbers: dict) -> list[tuple[str, object, object, str, bool]]:
    rows = []
    for claim, key, said, source in CLAIMS:
        got = numbers[key]
        ok = got >= 6 if said == ">=6" else got == said
        rows.append((claim, said, got, source, ok))
    return rows


def main() -> int:
    numbers = recount()
    rows = check(numbers)
    w = max(len(r[0]) for r in rows)
    print(f"{'article':<{w}}  {'says':<16} {'files give':<16} source")
    for claim, said, got, source, ok in rows:
        mark = "" if ok else "   <-- MISMATCH"
        print(f"{claim:<{w}}  {str(said):<16} {str(got):<16} {source}{mark}")
    print()
    print("marker hits in arm B:", "; ".join(f"{t}: {h}" for t, h in numbers["marker_hits_B_where"]))
    print("the eight that pass:", "; ".join(numbers["tamper_passed_names"]))
    bad = [r for r in rows if not r[4]]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} numbers match the files." if not bad else f"\n{len(bad)} mismatch(es).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
