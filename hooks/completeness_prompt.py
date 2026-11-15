#!/usr/bin/env python3
"""Intent anchor — UserPromptSubmit hook (fires when the user sends a prompt).

The instruction gate (completeness_stop.py) audits a work turn against the
user's instruction. A generic end-of-turn "did you do everything?" is
gameable: the model re-reads the instruction AFTER working and grades
itself against the reading that matches what it did — scope quietly
narrowed, enumerations sampled, intent flattened to the literal words.

The countermeasure is a commitment made BEFORE the work. This hook injects,
alongside each user prompt, the demand to (1) restate the instruction's
INTENT — what the user will have at the end, under the most demanding
plausible reading — asking first if that is ambiguous, and (2) post the
deliverables checklist the turn commits to. The Stop gate then audits
against that posted checklist: the delta between a written commitment and
the delivery is much harder to paper over than a fresh self-assessment.

Context-only (never blocks, costs ~80 tokens per prompt). Follows the
per-project gate mode (`completeness_stop.py --mode` or the
/instruction-gate:mode skill): in the default smart mode the contract is
injected only for prompts that look multi-part or exhaustive — a
micro-request gets no ceremony at either end of the turn; `strict` injects
for every prompt; `off` never. Also skipped for slash commands (they carry
their own contracts), empty prompts, outside a project, and when
INSTRUCTION_GATE=0 — one env switch for the whole gate pair.

Payload contract (stdin JSON): session_id, cwd, prompt.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from completeness_common import (
    disabled_by_env,
    gate_mode,
    looks_multipart,
    project_root,
)

CONTRACT = """Intent contract (the instruction completeness gate is armed for this turn).
If this message requests work — changes, artifacts, a multi-step task:
1. Restate the INTENT in one line: what the user will have when the turn ends, under the most demanding plausible reading — not the literal minimum of the words. If scope or intent is ambiguous, ask BEFORE executing; never self-answer a question only the user can arbitrate.
2. Post the deliverables checklist you commit to — explicit AND implied items (each element of an enumeration, tests, docs, regenerated artifacts). The completeness gate will audit this turn against that exact checklist before it can end.
A pure question or conversation needs none of this — just answer."""


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return

    if disabled_by_env():
        return

    try:
        prompt = payload.get("prompt") or ""
        if not prompt.strip() or prompt.lstrip().startswith("/"):
            return

        cwd = payload.get("cwd")
        if cwd and Path(cwd).is_dir():
            os.chdir(cwd)
        root = project_root()
        if root is None:
            return

        mode = gate_mode(root)
        if mode == "off":
            return
        if mode != "strict" and not looks_multipart(prompt):
            return  # micro-request: no ceremony at either end of the turn

        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": CONTRACT,
                    }
                }
            )
        )
    except Exception:
        # Context-only hook: never break a prompt on our own bugs
        pass


if __name__ == "__main__":
    main()
