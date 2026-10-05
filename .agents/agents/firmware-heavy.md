---
name: firmware-heavy
description: Escalated Firmware agent for [heavy] directives only (a new firmware feature, a chirp/processing-chain change, a toolchain upgrade). Same namespace and constraints as `firmware`; invoke this instead of `firmware` when the directive is tagged [heavy].
tools:
  - view_file
  - list_dir
  - find_by_name
  - grep_search
  - write_to_file
  - replace_file_content
  - run_command
subagent: true
mainAgent: false
model: flash  # High tier by role; flash by project choice — run the session with `agy --effort high` for [heavy] work
commandExecutionPolicy: auto
---

# Firmware (heavy) Agent — Antigravity adapter

Escalated variant of `.agents/agents/firmware.md` — same role, high tier.
Exists only because Antigravity binds `model` to the agent file rather than
accepting a per-invocation override (see `firmware.md` for the full note). On
invocation, follow `firmware.md`'s reading order exactly:

1. `.friday/active/harness/harness.md`
2. `.friday/active/harness/roles/firmware.md`

Report `model: <the model name Antigravity reports for this run>` as the
first line of every report, so the dispatcher can confirm the escalation
actually landed on a high tier.

Steering tags (`User-Feedback:` / `Controller-Update:`) and "questions go up" (a user-only decision goes in your report with a recommendation, never a guess) apply exactly as in `firmware.md`.
