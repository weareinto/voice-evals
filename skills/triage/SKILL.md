---
name: triage
description: Investigate a voice-agent alert or a bad session - find the failing sessions, show the exact turns that broke each check, explain the likely cause, and optionally add the session to the test dataset. Use when a Slack alert fires (B1-B16 etc.), someone shares a trace/session id, or asks why the voice agent misbehaved.
argument-hint: "<alert code | trace id> [--days N]"
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py *)
---

# Voice evals: triage

CLI: `python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py <command>` (written `ve <command>` below; always type the full form).
Token rules: the CLI already extracts the evidence; never pull full transcripts or traces into the conversation. One triage call per session.

1. Alert code (e.g. `B6`): `ve triage --alert B6 --days 1` lists the breaching sessions and triages the worst one.
   Trace id: `ve triage <trace_id>`.
2. Read the breached checks and their evidence lines. Explain the cause in plain words (3-5 sentences) and name the most likely fix (prompt rule, turn-taking setting, STT/TTS, scoring prompt). Say if it looks like a false alarm of the check itself.
3. Ask before changing anything:
   - keep the session as a test case: `ve add-case <trace_id> --note "<one line>"` (the loop: the release gate will replay it);
   - share the write-up: write it to a file and `ve post --file <path>`.
