import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"

USER = {"type": "user", "message": {"content": "Fix all the parsers and update the docs"}}
EDIT = {"type": "assistant", "message": {"content": [{
    "type": "tool_use", "name": "Edit", "input": {"file_path": "/x/parser.py"}}]}}
READ = {"type": "assistant", "message": {"content": [{
    "type": "tool_use", "name": "Read", "input": {"file_path": "/x/parser.py"}}]}}
TEXT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}
TOOL_RESULT = {"type": "user", "message": {"content": [{
    "type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def _project(tmp_path) -> Path:
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    return project


def _transcript(tmp_path, events) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


def _run_gate(project, transcript, stop_hook_active=False, extra_env=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("INSTRUCTION_GATE", None)
    env.pop("INSTRUCTION_GATE_MIN_TOOLS", None)
    env.update(extra_env or {})
    payload = {
        "session_id": "s1",
        "transcript_path": str(transcript),
        "cwd": str(project),
        "stop_hook_active": stop_hook_active,
    }
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "completeness_stop.py")],
        input=json.dumps(payload), cwd=project,
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_work_turn_blocks_with_audit(tmp_path):
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TEXT]))
    assert out.returncode == 2
    assert "completeness gate" in out.stderr
    # The audited instruction is quoted back so the audit has an anchor
    assert "Fix all the parsers" in out.stderr
    assert "SKIPPED" in out.stderr


def test_read_only_turn_never_blocks(tmp_path):
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, READ, TEXT]))
    assert out.returncode == 0
    assert out.stderr.strip() == "" and out.stdout.strip() == ""


def test_loop_guard(tmp_path):
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TEXT]),
                    stop_hook_active=True)
    assert out.returncode == 0 and out.stderr.strip() == ""


def test_disable_env(tmp_path):
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TEXT]),
                    extra_env={"INSTRUCTION_GATE": "0"})
    assert out.returncode == 0 and out.stderr.strip() == ""


def test_tool_results_do_not_reset_the_turn(tmp_path):
    """Tool feedback rides user-type events; only a real prompt starts a turn."""
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TOOL_RESULT, TEXT]))
    assert out.returncode == 2


def test_new_prompt_resets_the_turn(tmp_path):
    """Edits from a previous turn never gate the current conversational turn."""
    project = _project(tmp_path)
    thanks = {"type": "user", "message": {"content": "thanks!"}}
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, thanks, TEXT]))
    assert out.returncode == 0 and out.stderr.strip() == ""


def test_min_tools_gates_research_turns(tmp_path):
    project = _project(tmp_path)
    transcript = _transcript(tmp_path, [USER, READ, READ, TEXT])
    out = _run_gate(project, transcript,
                    extra_env={"INSTRUCTION_GATE_MIN_TOOLS": "2"})
    assert out.returncode == 2
    # Below the threshold: still silent
    out2 = _run_gate(project, transcript,
                     extra_env={"INSTRUCTION_GATE_MIN_TOOLS": "3"})
    assert out2.returncode == 0


def test_min_edits_threshold(tmp_path):
    """INSTRUCTION_GATE_MIN_EDITS spares small touch-up turns from the gate."""
    project = _project(tmp_path)
    one_edit = _transcript(tmp_path, [USER, EDIT, TEXT])
    out = _run_gate(project, one_edit,
                    extra_env={"INSTRUCTION_GATE_MIN_EDITS": "2"})
    assert out.returncode == 0
    two_edits = _transcript(tmp_path, [USER, EDIT, EDIT, TEXT])
    out2 = _run_gate(project, two_edits,
                     extra_env={"INSTRUCTION_GATE_MIN_EDITS": "2"})
    assert out2.returncode == 2


def test_audit_is_anchored_not_generic(tmp_path):
    """The audit presumes incompleteness, targets the committed checklist,
    and names the three gap families — not a generic 'did you do everything'."""
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TEXT]))
    assert out.returncode == 2
    for anchor in ("presumed INCOMPLETE", "checklist you committed",
                   "forgotten", "lazy", "reinterpreted"):
        assert anchor in out.stderr


def _run_prompt(project, prompt, extra_env=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("INSTRUCTION_GATE", None)
    env.update(extra_env or {})
    payload = {"session_id": "s1", "cwd": str(project), "prompt": prompt}
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "completeness_prompt.py")],
        input=json.dumps(payload), cwd=project,
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_prompt_anchor_injects_intent_contract(tmp_path):
    project = _project(tmp_path)
    out = _run_prompt(project, "Fix all the parsers and update the docs")
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "INTENT" in ctx and "checklist" in ctx and "ask BEFORE" in ctx


def test_prompt_anchor_skips_commands_and_empty(tmp_path):
    project = _project(tmp_path)
    assert _run_prompt(project, "/instruction-gate:mode").stdout.strip() == ""
    assert _run_prompt(project, "   ").stdout.strip() == ""


def test_prompt_anchor_shares_the_disable_switch(tmp_path):
    project = _project(tmp_path)
    out = _run_prompt(project, "Fix everything",
                      extra_env={"INSTRUCTION_GATE": "0"})
    assert out.stdout.strip() == ""


MICRO = {"type": "user", "message": {"content": "Fix the typo in README"}}


def _run_mode(project, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "completeness_stop.py"), "--mode", *args],
        cwd=project, capture_output=True, text=True, env=env, timeout=30,
    )


def test_micro_request_not_gated_by_default(tmp_path):
    """Smart mode: a micro-request with a small turn pays no audit."""
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [MICRO, EDIT, TEXT]))
    assert out.returncode == 0 and out.stderr.strip() == ""


def test_big_turn_gated_even_from_micro_prompt(tmp_path):
    """5+ edits means real work happened, whatever the instruction said."""
    project = _project(tmp_path)
    out = _run_gate(project, _transcript(tmp_path, [MICRO] + [EDIT] * 5 + [TEXT]))
    assert out.returncode == 2


def test_strict_mode_gates_micro_requests(tmp_path):
    project = _project(tmp_path)
    assert "strict" in _run_mode(project, "strict").stdout
    out = _run_gate(project, _transcript(tmp_path, [MICRO, EDIT, TEXT]))
    assert out.returncode == 2


def test_off_mode_silences_the_pair(tmp_path):
    project = _project(tmp_path)
    assert "off" in _run_mode(project, "off").stdout
    out = _run_gate(project, _transcript(tmp_path, [USER, EDIT, TEXT]))
    assert out.returncode == 0 and out.stderr.strip() == ""
    assert _run_prompt(project, "Fix all the parsers").stdout.strip() == ""


def test_mode_cli_status_and_validation(tmp_path):
    project = _project(tmp_path)
    assert "mode: on" in _run_mode(project, "status").stdout
    assert "mode: strict" in _run_mode(project, "strict").stdout
    assert "mode: strict" in _run_mode(project, "status").stdout
    assert "unknown mode" in _run_mode(project, "sometimes").stdout
    assert "mode: on" in _run_mode(project, "on").stdout


def test_prompt_anchor_skips_micro_prompts(tmp_path):
    """Smart mode spares micro-prompts the ceremony at both ends."""
    project = _project(tmp_path)
    assert _run_prompt(project, "Fix the typo in README").stdout.strip() == ""
