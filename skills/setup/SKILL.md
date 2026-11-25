---
name: setup
description: Set up or update voice evals for a voice agent repo - create voice-evals.yaml, push online evaluators and Slack alerts to LangSmith, add the GitHub Actions jobs. Use when someone asks to add evals/monitoring/alerts to a voice agent, change an alert threshold, or onboard a new agent.
argument-hint: "[agent name]"
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py *) Bash(pip install -q -r ${CLAUDE_PLUGIN_ROOT}/cli/requirements.txt)
---

# Voice evals: setup

All work goes through the CLI: `python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py <command>` (written `ve <command>` below; always type the full form).
Token rules: never open traces, the LangSmith UI or the LangSmith MCP; only read CLI output. Don't print API keys.

1. If `ve --version` fails with an import error: `pip install -q -r ${CLAUDE_PLUGIN_ROOT}/cli/requirements.txt`.
2. Needs `LANGSMITH_API_KEY` in the environment. If missing, ask the user to set it (secrets store, never in chat).
3. No `voice-evals.yaml` in the repo root yet: `ve init --agent <name>` writes it plus `rubric.md`. Ask the user only for what the file marks `TODO` (LangSmith workspace/project IDs, session root run name, Slack team/channel IDs). Keep the default alerts unless told otherwise.
4. `ve setup` prints the plan (create / update / unchanged per evaluator and alert). Show it to the user in a few lines and ask before applying.
5. On yes: `ve setup --apply`. It saves new alert IDs in `voice-evals.state.json`; tell the user to commit both files.
6. Scheduled digests and the release gate: `ve init --ci` copies the GitHub workflows into `.github/workflows/`. Tell the user which repo secrets to add: `LANGSMITH_API_KEY`, `VOICE_EVALS_SLACK_WEBHOOK`, plus the judge key (`ANTHROPIC_API_KEY`) and any key the release target needs.

Changing a threshold = edit the alert in `voice-evals.yaml`, then steps 4-5.
