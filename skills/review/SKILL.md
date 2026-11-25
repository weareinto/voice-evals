---
name: review
description: Weekly (or daily) quality review of a voice agent - per-check breach rates vs the previous period, worst sessions, and what to do next. Use when asked how the voice agent did this week, for a quality report, or to post the weekly review to Slack.
argument-hint: "[--days 7]"
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py *)
---

# Voice evals: review

CLI: `python ${CLAUDE_PLUGIN_ROOT}/cli/ve.py <command>` (written `ve <command>` below; always type the full form).
Token rules: one report call; don't open sessions unless the user asks (then use the triage skill).

1. `ve report --days 7 --compare` (use `--days 1` for a daily check).
2. Give the user: sessions count, the checks that got worse (with numbers), the checks still breaching, and the 3 worst sessions. Then 2-3 concrete next steps (e.g. triage B6's worst session, tune a threshold that fires on every session, add cases to the dataset).
3. Post only if asked: same command with `--slack`. GitHub Actions already posts the daily digest and Monday review on its own.
