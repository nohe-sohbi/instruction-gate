"""Shared plumbing for the instruction-gate hook pair (stdlib-only, never raises).

The pair: completeness_prompt.py (intent + checklist committed at prompt
time) and completeness_stop.py (item-by-item audit before a work turn can
end). Both read the same per-project mode and the same "does this
instruction deserve the ceremony?" heuristic, so a prompt that was spared
the contract is also spared the audit — unless the turn itself grew big.

This module is self-contained: project detection and mode persistence live
here, so the two hooks import nothing outside the standard library.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

GATE_MODES = {"on", "off", "strict"}

STATE_FILE = ".claude/.instruction-gate.json"

# Signals that an instruction is multi-part or exhaustive. Tuned generous on
# purpose: a false positive costs one audit turn, a false negative is a
# silent gap — but micro-requests ("fix this typo") stay under every signal.
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+\S")
_EXHAUSTIVE = re.compile(
    r"\b(all|every|each|entire|whole|everything|everywhere|"
    r"tout|toute|tous|toutes|chaque|partout|"
    r"complet|complète|exhaustif|exhaustive|intégral|intégrale)\b",
    re.IGNORECASE,
)
_CONJUNCTION = re.compile(
    r"\b(and|then|also|as well as|et|puis|ensuite|aussi|également|ainsi que)\b",
    re.IGNORECASE,
)
_MIN_CHARS = 200


def project_root() -> Path | None:
    """$CLAUDE_PROJECT_DIR (set by Claude Code for hooks), else walk up from
    cwd to a .git/.claude marker. None if no marker is found."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists() or (candidate / ".claude").is_dir():
            return candidate
    return None


def load_state(root: Path) -> dict:
    try:
        return json.loads((root / STATE_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(root: Path, state: dict) -> None:
    try:
        path = root / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, path)  # atomic: concurrent sessions may race
    except OSError:
        pass


def looks_multipart(text: str | None) -> bool:
    """Does the instruction look multi-part or exhaustive?"""
    if not text:
        return False
    return (
        len(text) >= _MIN_CHARS
        or _LIST_MARKER.search(text) is not None
        or _EXHAUSTIVE.search(text) is not None
        or _CONJUNCTION.search(text) is not None
    )


def disabled_by_env() -> bool:
    """INSTRUCTION_GATE=0 kills the whole pair, whatever the mode file says."""
    return os.environ.get("INSTRUCTION_GATE", "").strip().lower() in {
        "0",
        "off",
        "false",
    }


def gate_mode(root) -> str:
    """'on' (smart, default) | 'strict' | 'off' — persisted per project in
    the gate state file, set via `completeness_stop.py --mode`."""
    mode = str(load_state(root).get("mode", "on")).strip().lower()
    return mode if mode in GATE_MODES else "on"


def set_gate_mode(root, mode: str) -> None:
    state = load_state(root)
    state["mode"] = mode
    save_state(root, state)
