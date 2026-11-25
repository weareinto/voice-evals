---
name: release
description: Run the voice-agent release gate - replay the test dataset through a candidate (new prompt, model or setting), score it with checks and an AI judge, compare to thresholds and a baseline, and post the verdict. Use before shipping a change to a voice agent or when asked whether a change is better or safe.
argument-hint: "[candidate name] [--baseline experiment]"
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py *)
---

# Voice evals: release gate

CLI: `python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py <command>` (written `ve <command>` below; always type the full form) (run from the agent repo; reads `voice-evals.yaml`).
Token rules: only read CLI output; never fetch datasets or experiments yourself.

1. Smoke test first, cheap and local: `ve release --name <candidate> --limit 3 --local`. Fix errors in the target before going on.
2. Full run: `ve release --name <candidate> [--baseline <previous experiment>]`. Candidate settings reach the target through `--set key=value` (for example `--set thinking_level=low`).
3. The last line is the verdict: `PASS` or `FAIL` plus the failed gates. Report that line, the 3-6 gate numbers, and the experiment link. Nothing more unless asked.
4. On FAIL: `ve release --name <candidate> --explain 5 --reuse` shows the 5 worst cases (short). Summarise the pattern in two or three sentences and suggest one fix.
5. Post to Slack only if the user asks: add `--slack`.

Each full run calls the agent's model once per case, and the judge once per case. Say so if the user asks for more than ~100 cases.
