# Field log, 21–22 September 2026: notes

`guard-log.redacted.jsonl` is the guard's journal (`.lumis/guard.log`) from the first real use of the scope guard:
the founder of LUMIS installed it in his own project and worked there with Claude Code for one conversation on
21–22 September 2026. The project is not named here, and nothing about it is published: not its name, paths, stack,
boundary texts or code.

## What the 29 lines are

| event | count | what it means |
|---|---|---|
| `tamper` | 18 | a call that looked like a change to the guard's own files; refused (exit 2) |
| `warned` | 10 | a warning the agent saw but was not stopped by (exit 1) |
| `asked` | 1 | the prompt hook flagged the user's prompt; it cannot block |
| `blocked` | 0 | a call crossing one of the project's Non-Goals |

Recount: `python field-report/recount.py`, or
`python -c "import json,collections;print(collections.Counter(json.loads(l)['event'] for l in open('field-report/field-log/guard-log.redacted.jsonl',encoding='utf-8')))"`.

Nothing crossed a Non-Goal. Every one of the 18 stops was the guard defending its own files.

## How the log was redacted

One line per original line, in the original order, with the original `ts`, `event`, `agent`, `tool` and `hits`
count. The raw `attempted` field (up to 160 characters of the command or the written text) is replaced by `shape`,
a hand-written form of the same command with the project removed: `<repo>` for the project folder, `<code file>`,
`<edits DECISION_LOG.md>` and similar placeholders for anything that names the project. Guard file names, document
names (`DECISION_LOG.md`, `DESIGN_CONSTITUTION.md`, `TASK_PROGRESS.md`, `README.md`, `.gitattributes`) and the
operator shape (`cat`, `python - <<'PY'`, `2>&1 | head`) are kept, because they are what made the guard stop.
Guard-file `hits` are verbatim. In line 1 the matched keyword and the NG number are kept and the boundary text is
replaced by `<the project's boundary text>`; in line 10 the two model names are replaced by `<model>`. A `…` at the
end of a shape is where the raw log itself cut the text off.

## The 18 stops, by command shape

The `classification` field on each `tamper` line is the engineering reading of the command shape only. **It has not
yet been confirmed against the session by the founder**, which is why the article claims no more than "at least 6".

| reading | lines | shapes |
|---|---|---|
| false | 10 | a read counted as a write (`cat .claude/settings.json`; a `python -c` that loads the config); the guard's own `report 2>&1 \| head`, twice; `DESIGN_CONSTITUTION.md` matched `CONSTITUTION.md` as a substring, twice; a `git status` inspection; `cd <repo> && python scripts/scope_guard.py doctor`; two notes about the guard written into the decision log |
| likely false | 5 | a README edit, two progress notes and a `.gitattributes` file that name a guard file in their text; a read-only listing of files to be committed |
| unclear | 3 | two commands the raw log cuts off before the part that matched; the user-level settings edit below |

The four shapes the article lists cover seven of the ten `false` lines (12:21:46, 12:22:04, 05:04:11, 16:36:37,
16:37:14, 16:49:34, 16:51:07). The two decision-log notes are consecutive (22.09 16:49 and 16:51); the other
decision-log writes in the log are `warned`, not stops.

**The user-level settings line (22.09 05:21:25).** The target of this Edit was the user's global Claude Code
settings file (`~/.claude/settings.json`), outside the project; the replacement text reads like a line of project
documentation, not like settings. The log cannot tell a wrong target from a real attempt to edit the user's settings,
so it is marked `unclear`.

## What was fixed, and when

- **21.09:** `cd`, `echo`, `printf` and similar are an inspection, not a write, so `cd <repo> && cat
  .claude/settings.json` is no longer a stop. Single marker words became warnings.
- **22.09:** a guard file counts as named only by its whole name or as the tail of a path, so `DESIGN_CONSTITUTION.md`
  is another file; `cd <repo> && python scripts/scope_guard.py doctor` is allowed (every part must be an inspection
  or a documented self-run); a heredoc written into a document and the text of `git commit -m` are data, so a note
  that names a guard file is not a stop; empty warnings (`warned` with no hits, nine of the ten here) are no longer
  written.
- **23.09:** the prompt hook became advisory; observe mode and the three boundary classes shipped.
- **24–25.09:** `2>&1`, `--version`/`--help` and trailing filters in a self-run (the `report 2>&1 | head` shape,
  which the log shows refused on 21.09 and again on 22.09).

Two limits of that list. The 22.09 heredoc fix covers a heredoc written into a document (`cat >> DECISION_LOG.md
<<'EOF'`); the two decision-log stops here are `python - <<'PYEOF'` scripts that edit the file, and a heredoc given
to an interpreter is still read as a command. And the bench of 24.09 met a `cat >> DECISION_LOG.md` note refused
again, which it could not reproduce offline (`../bench/v2/ERRATA.md`).

## The prompt hook and line 1

The only `asked` line is the project's first instruction ("Read MASTER_PROMPT.md, CONSTITUTION.md, ARCHITECTURE.md
… before making changes"). The prompt hook matched three single words of long Non-Goal sentences: `architecture`,
`domain` and `scope`. Since 23.09 the prompt hook reports only a forbidden package, path or multi-word phrase, and
never a lone word.

## What the log does not show

- The route-around. In answers to ten questions the founder asked about the guard after the session (22.09), the
  agent said that once, sure it was right, it tried the same change through another tool and was stopped again. The
  log does not mark which line that was.
- The agent's words "text is a promise, the hook is a mechanism" come from the same answers. Our engineering notes
  recorded them in Russian; the English wording is pending the founder's check against the session.
- Anything about other projects, other agents or other days. This is one repository and one conversation.
