# instruction-gate

A Claude Code plugin that makes the model commit to what it will deliver, then audits
the turn against that commitment before it can end.

## Why

Asking "did you do everything?" after the fact does not work. The instruction gets
re-read by the same party that just did the work, and among the plausible readings, the
one matching what was built is the one that feels right. Self-grading an exam you wrote
after seeing your own answers.

So the commitment moves to before the work. At prompt time the gate demands a restated
intent and a deliverables checklist. At the end of the turn it blocks once and demands
an item-by-item audit against that checklist, hunting three failures: an enumeration
sampled instead of exhausted, an implied deliverable skipped, an instruction quietly
narrowed.

## How

Two hooks, stdlib Python, no dependencies.

| File | Event | Behavior |
|------|-------|----------|
| `hooks/completeness_prompt.py` | `UserPromptSubmit` | Injects the intent contract, ~80 tokens. Never blocks. |
| `hooks/completeness_stop.py` | `Stop` | Exits 2 with the audit instructions on stderr, which Claude Code feeds back to the model. |

It fires once per turn (`stop_hook_active` loop guard), only on turns that edited files,
and only inside a project (`.git` or `.claude` marker). Both hooks swallow their own
exceptions: a bug in the gate must never break a session.

## Install

```
/plugin marketplace add nohe-sohbi/instruction-gate
/plugin install instruction-gate@instruction-gate-marketplace
```

The repository is its own marketplace, so that is the whole setup.

## Modes

```
/instruction-gate:mode [on|off|strict|status]
```

Persisted per project in `.claude/.instruction-gate.json`.

| Mode | Behavior |
|------|----------|
| `on` (default) | Arms only on instructions that look multi-part or exhaustive (list markers, "all"/"tout"/"chaque", conjunctions, 200+ chars), or on any turn of 5+ edits. Micro-requests cost nothing. |
| `strict` | Every file-editing turn is audited. |
| `off` | Silent. |

Cost in the default mode: roughly one extra model turn per substantial work turn, mostly
absorbed by prompt caching since the audit re-reads a cached context.

## Settings

| Variable | Default | Effect |
|----------|---------|--------|
| `INSTRUCTION_GATE=0` | unset | Disables both hooks, whatever the mode. |
| `INSTRUCTION_GATE_MIN_EDITS=N` | 1 | Only gate turns with at least N edits. |
| `INSTRUCTION_GATE_BIG_TURN=N` | 5 | Edit count that arms the gate regardless of the instruction. |
| `INSTRUCTION_GATE_MIN_TOOLS=N` | off | Also gate tool-heavy read-only turns. |

## Limits

It is a self-audit, not an oracle: no hook can verify that an instruction was fully
executed, this one only gives the check a fixed target. The heuristic knows French and
English word lists only, so smart mode under-triggers elsewhere, use `strict`. And it
has never been through real use: the thresholds are first guesses, validated by tests
and smoke runs, nothing more.

## Development

```
pip install pytest && pytest tests/ -q
```

18 tests running the hooks as real subprocesses against forged JSONL transcripts.
