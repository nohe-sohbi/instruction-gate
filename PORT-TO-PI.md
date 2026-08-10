# Port instruction-gate to pi

**If you use [pi](https://pi.dev) instead of Claude Code**, paste this single line into pi:

```
Fetch https://raw.githubusercontent.com/nohe-sohbi/instruction-gate/main/PORT-TO-PI.md and follow it.
```

(Or, from a clone of this repo: `Read PORT-TO-PI.md and follow it.`)

Everything below is addressed to the pi agent. It is a build spec, not an
invitation: where it says verbatim, copy verbatim; where it says never, there
is no judgment call. This is pi's own philosophy — the harness ports the tool
into itself — but the behavior being ported was tuned against real failure
modes, so the contract is fixed even though the implementation is yours.

---

## What you are building

One TypeScript extension implementing the **instruction completeness gate**:

1. **Prompt time** — when the user sends a work instruction, inject a contract
   demanding that the model restate the instruction's intent and commit to a
   deliverables checklist *before* working.
2. **Turn end** — when a file-editing turn ends, trigger exactly one follow-up
   audit turn: the model must grade itself item-by-item against the checklist
   it committed to, finish what is missing, or surface what was skipped.

The countermeasure logic: an after-the-fact "did you do everything?" is
gameable (the model re-reads the instruction to match what it did); a written
commitment made *before* the work is not.

## Step 0 — read before writing

1. Your own extension documentation (events, `pi.sendMessage`,
   `pi.registerCommand`, `pi.appendEntry`).
2. Clone the source: `git clone https://github.com/nohe-sohbi/instruction-gate`
   into a temp directory. Read all three hook files — their module docstrings
   are the authoritative behavior contract:
   - `hooks/completeness_prompt.py` — prompt-time contract injection
   - `hooks/completeness_stop.py` — end-of-turn audit gate
   - `hooks/completeness_common.py` — modes, heuristics, env switches

## Behavior contract

### A. Prompt-time injection (Claude Code `UserPromptSubmit` → pi `before_agent_start`)

On each real user prompt, decide whether to inject the intent contract:

- Skip if: the env kill switch is set (see D); the prompt is empty; the input
  is a pi command or template invocation (they carry their own contracts);
  there is no project (`.git` marker walking up from cwd); mode is `off`.
- In mode `on` (default): inject only if `looksMultipart(prompt)` (see C).
- In mode `strict`: inject for every non-empty prompt.

Injection = **append** a context message alongside the user prompt (use
`before_agent_start`; never rewrite the user's text, never touch the rest of
the system prompt). The injected text is the `CONTRACT` constant in
`hooks/completeness_prompt.py` — copy it **verbatim**.

### B. End-of-turn audit (Claude Code `Stop` → pi `agent_end`)

Track live during the turn, via tool events (do **not** parse session files):

- `edits` = number of tool calls whose tool modifies files (`edit`, `write`,
  and any override of them). Reset on each real user prompt.
- `tools` = total tool calls since the last real user prompt.
- `instruction` = text of the last real user prompt.

On `agent_end`, fire the audit iff **all** of:

1. Not disabled (env kill switch, mode `off`, outside a project).
2. This turn was started by a **real user prompt** — never by an injected
   message (yours or any other extension's). This is the loop guard.
3. Not already audited this user turn (max ONE audit per user turn — persist
   the flag via `pi.appendEntry` so a mid-turn reload cannot re-fire it).
4. `edits >= INSTRUCTION_GATE_MIN_EDITS` (default 1), **or**
   `INSTRUCTION_GATE_MIN_TOOLS` is set and `tools >=` it.
5. In mode `on` only: `looksMultipart(instruction)` **or**
   `edits >= INSTRUCTION_GATE_BIG_TURN` (default 5). (`strict` skips this.)

Firing the audit =

```ts
pi.sendMessage(
  { customType: "instruction-gate", content: AUDIT_TEXT, display: true },
  { triggerTurn: true },
);
```

`AUDIT_TEXT` is the output of `build_message()` in
`hooks/completeness_stop.py` — port that function **verbatim**, including the
quoted instruction truncated to 160 chars (`_quote()`).

### C. The `looksMultipart` heuristic

Port the four signals from `hooks/completeness_common.py` exactly (regexes
included — they carry English and French word lists): length ≥ 200 chars, or
markdown list markers, or exhaustive words ("all", "every", "tout",
"chaque", …), or conjunctions ("and", "then", "et", "puis", …).

### D. Modes, state, switches

- Register **one** command: `/ig-mode [on|off|strict|status]` (namespaced —
  never register a generic name like `/mode`). It replaces the
  `skills/mode` skill, which you do not port.
- Persist the mode in `<project>/.pi/instruction-gate.json` as
  `{"mode": "on"|"off"|"strict"}`; default `on`; unknown values fall back to
  `on`. Re-read it on `session_start`.
- Env switches, same names and defaults as the source:
  `INSTRUCTION_GATE` (`0`/`off`/`false` disables everything),
  `INSTRUCTION_GATE_MIN_EDITS` (1), `INSTRUCTION_GATE_BIG_TURN` (5),
  `INSTRUCTION_GATE_MIN_TOOLS` (unset = off).

## Non-negotiable guards

Other extensions may be installed. You must co-exist:

- Tag **every** message you inject with `customType: "instruction-gate"`.
- Never audit a turn triggered by an injected message — yours or another
  extension's. Only real user prompts arm the gate.
- Never rewrite the system prompt or other messages; injection is append-only.
- All state lives in `.pi/instruction-gate.json` and your own `appendEntry`
  custom entries — never write anywhere else.
- Wrap every handler: an exception in the gate must **never** break a session.
  Fail silent, like the source hooks do.

## Install

Ask the user (do not decide for them): project-local
(`.pi/extensions/instruction-gate.ts`) or global
(`~/.pi/agent/extensions/instruction-gate.ts`)? Default suggestion:
project-local, so the gate travels with the repo that wants it.

## Verify before you call it done

Run through each of these — in order, for real:

- (a) A short prompt ("fix this typo" + one edit) produces zero ceremony in
  default mode: no contract, no audit.
- (b) A multi-part prompt (e.g. a 3-item list) that edits files gets the
  contract injected AND exactly one end-of-turn audit.
- (c) The audit turn itself ends without triggering a second audit.
- (d) `/ig-mode off` silences both ends; `/ig-mode status` reports it;
  `/ig-mode on` restores it.
- (e) `/ig-mode strict` audits even a single-edit micro-prompt.
- (f) The mode survives a session reload.
- (g) `INSTRUCTION_GATE=0` in the environment disables everything regardless
  of mode.
- (h) A read-only / conversational turn never fires the audit.

## Report to the user

When done, state: where the extension was installed; the surfaces it touches
(events subscribed: `before_agent_start`, `agent_end`, `session_start`, tool
events; command registered: `/ig-mode`; state file:
`.pi/instruction-gate.json`; messages tagged `instruction-gate`); the kill
switches; and how to uninstall (delete the extension file and the state file).
