---
name: mode
description: Control the instruction completeness gate for this project — turn it off, back on (smart mode, the default), or strict, or show its status. Use when the user finds the completeness audit too frequent or noisy (micro-requests), wants every editing turn audited, or asks when/why the gate fires.
argument-hint: "[on|off|strict|status]"
---

# Instruction gate control

The gate is the hook pair `completeness_prompt.py` (intent restated +
deliverables checklist committed at prompt time) / `completeness_stop.py`
(item-by-item audit against that checklist before a work turn can end).

Modes, persisted per project in `.claude/.instruction-gate.json`:

| Mode | Behavior |
|------|----------|
| `on` (default) | **Smart**: the ceremony fires only for instructions that look multi-part or exhaustive (lists, "all"/"tout"/"chaque"/…, conjunctions, length ≥ 200 chars) — OR when the turn grew big anyway (5+ file edits, whatever the instruction: "continue" can hide a big turn). Micro-requests pass with zero overhead. |
| `strict` | Every file-editing turn commits and gets audited, whatever the instruction. |
| `off` | The pair is silent. |

Set or inspect with:

```
python3 <plugin-root>/hooks/completeness_stop.py --mode [on|off|strict|status]
```

(This SKILL.md lives at `<plugin-root>/skills/mode/SKILL.md` — the plugin
root is two directories up.) No argument or `status` prints the current
mode without changing it. Report the resulting mode to the user in one line.

Env overrides (they win over the mode file): `INSTRUCTION_GATE=0` disables
the pair entirely; `INSTRUCTION_GATE_MIN_EDITS=N` only gates turns with at
least N edits; `INSTRUCTION_GATE_BIG_TURN=N` moves the big-turn threshold
(default 5); `INSTRUCTION_GATE_MIN_TOOLS=N` extends the gate to tool-heavy
read-only turns.
