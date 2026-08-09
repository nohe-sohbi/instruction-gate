#!/usr/bin/env python3
"""Instruction completeness gate — Stop hook (fires when Claude finishes responding).

Field observation, repeated across every project run: completeness only
arrives after the user asks "were you complete?" — silently reduced scope,
the first N items of an enumeration, a TODO left behind. This hook asks that
question in the user's place, on EVERY instruction: on the first stop of a
turn that produced work (file edits), it blocks once and makes the model
audit its own turn against the user's instruction — finish what is missing,
or surface what was skipped as an explicit decision.

The hook cannot verify completeness itself (there is no oracle for "did you
do everything the instruction meant"). Two things keep the audit from being
a rubber stamp: the companion completeness_prompt.py hook makes the model
commit to a deliverables checklist BEFORE working (an after-the-fact
re-reading of the instruction is gameable; a written commitment is not),
and the audit demanded here is adversarial — the turn is presumed
incomplete, the three classic gaps are named (enumeration sampled, implied
deliverable skipped, instruction silently narrowed), and "everything done"
without the item-by-item list does not count.

Scope — three per-project modes, set with `--mode` (or the
/instruction-gate:mode skill), persisted in the project gate state file
(.claude/.instruction-gate.json):
- on (default, smart): the audit fires only when the instruction looks
  multi-part or exhaustive (lists, "all"/"tout"/"chaque", conjunctions,
  length) OR when the turn grew big anyway (INSTRUCTION_GATE_BIG_TURN
  edits, default 5, whatever the instruction — "continue" can hide a big
  turn). Micro-requests pass without ceremony.
- strict: every file-editing turn is audited, whatever the instruction.
- off: the pair is silent.
In every mode, conversational and read-only turns never block. Set
INSTRUCTION_GATE_MIN_EDITS=N to only gate turns with at least N edits
(default 1). Set INSTRUCTION_GATE_MIN_TOOLS=N to also gate tool-heavy
read-only turns (research tasks) at N tool calls. Set INSTRUCTION_GATE=0
to disable the gate pair regardless of mode.

Payload contract (stdin JSON): session_id, transcript_path, cwd,
stop_hook_active. Exits silently on stop_hook_active (loop guard: the audit
was already requested this turn), on missing/unparseable payload, and
outside a project (no .git/.claude marker — scratch conversations are
never gated).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import deque
from pathlib import Path

from completeness_common import (
    GATE_MODES, disabled_by_env, gate_mode, looks_multipart, project_root,
    set_gate_mode,
)

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Only the transcript tail is scanned; a window with no user prompt in it is
# necessarily inside the current turn, so the counters stay correct.
MAX_TAIL_LINES = 4000
QUOTE_CAP = 160


def _user_text(message: dict) -> str | None:
    """Plain text of a real user prompt; None for tool-result turns."""
    content = message.get("content")
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    texts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool_result":
            return None  # tool feedback riding a user event, not an instruction
        if item.get("type") == "text":
            texts.append(item.get("text", ""))
    joined = "\n".join(t for t in texts if t).strip()
    return joined or None


def turn_activity(transcript_path: str):
    """(instruction, edit_count, tool_count) since the last real user prompt."""
    instruction = None
    edits = tools = 0
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            tail = deque(f, maxlen=MAX_TAIL_LINES)
    except (OSError, UnicodeDecodeError):
        return None, 0, 0
    for line in tail:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("isSidechain") or obj.get("isMeta"):
            continue
        if obj.get("type") == "user":
            text = _user_text(obj.get("message", {}))
            if text is not None:
                instruction, edits, tools = text, 0, 0
        elif obj.get("type") == "assistant":
            content = obj.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tools += 1
                    if item.get("name") in EDIT_TOOLS:
                        edits += 1
    return instruction, edits, tools


def _quote(text: str | None) -> str | None:
    """Short, single-line quote of the instruction (command wrappers stripped)."""
    if not text:
        return None
    text = re.sub(r"<[^<>\n]{1,120}>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > QUOTE_CAP:
        text = text[: QUOTE_CAP - 3].rstrip() + "..."
    return text


def build_message(instruction: str | None) -> str:
    lines = [
        "Instruction completeness gate — this turn is presumed INCOMPLETE "
        "until audited.",
    ]
    if instruction:
        lines.append(f'Instruction under audit: "{instruction}"')
    lines += [
        "Audit against the deliverables checklist you committed to at the "
        "start of the turn. If you never posted one, that is your first "
        "finding: reconstruct it now from the instruction, under the most "
        "demanding plausible reading — the user's intent, not the literal "
        "minimum of the words.",
        "Hunt specifically for the three classic gaps:",
        '- forgotten: an enumeration sampled instead of exhausted '
        '("all"/"every"/"each" means every single one; partial execution '
        "counts as NOT DONE);",
        "- lazy: implied deliverables skipped (tests, docs, regenerated "
        "artifacts, the commit if requested);",
        "- reinterpreted: the instruction quietly narrowed into an easier "
        "task than the one given.",
        "Mark each checklist item: DONE (point to it) | NOT DONE -> do it "
        "now | SKIPPED -> state the decision and the reason to the user, "
        "never silently.",
        "Close with the item-by-item audit visible in your final message. "
        '"Everything done" without the list does not count.',
    ]
    return "\n".join(lines)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def cli_mode(args: list) -> None:
    """`completeness_stop.py --mode [on|off|strict|status]` — inspect or set
    the per-project gate mode."""
    root = project_root()
    if root is None:
        print("instruction gate: no project found (.git/.claude marker)")
        return
    if args and args[0].strip().lower() != "status":
        mode = args[0].strip().lower()
        if mode not in GATE_MODES:
            print(f"unknown mode '{mode}' — use on | off | strict | status")
            return
        set_gate_mode(root, mode)
    labels = {
        "on": "smart — audits multi-part/exhaustive instructions and big turns",
        "strict": "audits every file-editing turn",
        "off": "disabled",
    }
    mode = gate_mode(root)
    print(f"instruction gate mode: {mode} ({labels[mode]})")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mode":
        cli_mode(sys.argv[2:])
        return

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return

    if payload.get("stop_hook_active"):
        return  # loop guard: the audit was already requested this turn

    if disabled_by_env():
        return

    try:
        cwd = payload.get("cwd")
        if cwd and Path(cwd).is_dir():
            os.chdir(cwd)
        root = project_root()
        if root is None:
            return

        mode = gate_mode(root)
        if mode == "off":
            return

        transcript = payload.get("transcript_path")
        if not transcript or not Path(transcript).is_file():
            return

        instruction, edits, tools = turn_activity(transcript)

        min_edits = max(1, _env_int("INSTRUCTION_GATE_MIN_EDITS", 1))
        min_tools = _env_int("INSTRUCTION_GATE_MIN_TOOLS", 0)

        if edits < min_edits and not (min_tools > 0 and tools >= min_tools):
            return  # conversational / read-only / below-threshold turn: never block

        if mode != "strict":
            big_turn = max(1, _env_int("INSTRUCTION_GATE_BIG_TURN", 5))
            if not looks_multipart(instruction) and edits < big_turn:
                return  # micro-request, small turn: the audit costs more than it protects

        print(build_message(_quote(instruction)), file=sys.stderr)
        sys.exit(2)  # block the stop; stderr is fed back to Claude
    except SystemExit:
        raise
    except Exception:
        # Gate hook: never break a session on our own bugs
        pass


if __name__ == "__main__":
    main()
