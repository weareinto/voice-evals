# Voice Evals

Evals for voice agents with **LangSmith** (scores, datasets, experiments, instant alerts),
**Slack** (alerts and reports) and **Claude** (setup, release decisions, triage, reviews).

Built to be cheap in Claude tokens: a small Python CLI does all the work (LangSmith REST/SDK,
checks, judge, gate, Slack) and prints a few lines. Claude only runs commands and reads those
lines. No LangSmith MCP, no traces pulled into the conversation. Scheduled jobs run in GitHub
Actions with no Claude at all.

## What is in the repo

| Path | What it is |
|---|---|
| `.claude-plugin/` | plugin manifest + marketplace entry (this repo is both) |
| `skills/setup` | onboard an agent: config, evaluators, alerts, CI jobs |
| `skills/release` | release gate: replay the dataset through a candidate, PASS/FAIL |
| `skills/triage` | why did this alert fire: worst sessions + the exact lines that broke |
| `skills/review` | weekly/daily quality review with trends |
| `cli/` | the `voice-evals` CLI (run in place with `python cli/ve.py`, or `pip install ./cli`) |
| `cli/voice_evals/checks/` | built-in checks; `session_metrics` and `scoring_checks` are uploaded to LangSmith as online evaluators |
| `cli/voice_evals/templates/` | `voice-evals.yaml`, `rubric.md`, GitHub workflows written by `init` |
| `examples/eva/` | the full EVA setup (B1-B16, release target, EVA checks and rubric) |

## Install

Claude Code (terminal or desktop):

```
/plugin marketplace add weareinto/voice-evals
/plugin install voice-evals@into-voice-evals
```

Claude Code on the web (cloud sessions): add the plugin at claude.ai/customize/plugins, start a
new session. In the cloud environment allow `api.smith.langchain.com` and `hooks.slack.com` on
the network allowlist and set `LANGSMITH_API_KEY` (and `ANTHROPIC_API_KEY` for the judge) as
secrets.

Testing a local copy: `claude --plugin-dir ./voice-evals`.

## Commands

All commands read `voice-evals.yaml` from the agent repo (searched upwards from the current folder).

| Command | Does | Writes? |
|---|---|---|
| `init --agent NAME [--with-ci]` | writes `voice-evals.yaml`, `rubric.md`, optionally `.github/workflows/` | local files |
| `setup` | compares LangSmith with the config, prints the plan | no |
| `setup --apply` | creates/updates the online evaluators and alerts; keeps alert IDs in `voice-evals.state.json` | LangSmith |
| `report --days 1 [--compare] [--slack]` | per-alert breach counts per session, worst sessions | Slack with `--slack` |
| `triage --alert B6` / `triage <trace_id>` | breaching sessions, then the checks re-run locally with evidence lines | no |
| `release --name X [--set k=v] [--limit N] [--local] [--baseline EXP] [--explain N] [--slack]` | release gate; exit code 1 on FAIL | LangSmith experiment (not with `--local`) |
| `add-case <trace_id> --note "..."` | keeps a session in the cases dataset (the triage loop) | LangSmith dataset |
| `post --file F` / `--text T` | posts to the Slack webhook | Slack |

Environment: `LANGSMITH_API_KEY` always; `VOICE_EVALS_SLACK_WEBHOOK` to post; `ANTHROPIC_API_KEY`
for the default judge (Claude Haiku), or `GOOGLE_API_KEY` with `judge.provider: gemini`; whatever
the agent's release target needs.

## How the pieces connect

- **Instant alerts**: LangSmith online evaluators score every new session; LangSmith alert rules
  post to Slack through LangSmith's Slack app. Defined in `voice-evals.yaml`, pushed by `setup`.
- **Daily digest / weekly review**: `voice-evals-scheduled.yml` runs `report` in GitHub Actions
  and posts by webhook.
- **Release gate**: `voice-evals-release.yml` runs `release` on pull requests that touch the
  prompt or config; FAIL fails the check and the verdict goes to Slack.
- **Claude**: the four skills, on demand, in a laptop or cloud session.
- **The loop**: triage finds a bad session, `add-case` keeps it, the next release replays it.

## Adding an agent

1. In the agent repo: ask Claude "set up voice evals for this agent" (setup skill), or run
   `python <plugin>/cli/ve.py init --agent NAME --with-ci` and fill the `TODO` values.
2. If the agent's traces don't use EVA's transcript format, copy
   `cli/voice_evals/checks/session_metrics.py` into the repo, adapt it, and point the evaluator's
   `code:` at it. Keep the `perform_eval(run) -> {key: score}` entry point.
3. Write `evals/target.py` (`generate(inputs, settings) -> {"text", "ttft", "total"}`) and build
   a dataset of real moments for the release gate.
4. `setup`, then `setup --apply`; commit `voice-evals.yaml` and `voice-evals.state.json`; add the
   repo secrets.

## Costs

- Online evaluators, alerts, reports, triage: no model calls.
- Release gate: one agent-model call + one judge call per case (Haiku: a fraction of a cent per case).
- LangSmith: `extend_retention: true` on an evaluator keeps scored traces 180 days, billed by LangSmith.

## Notes

- LangSmith has no API to list alert rules, so `setup` remembers the IDs it created in
  `voice-evals.state.json`. Rules created elsewhere can be adopted by adding their IDs there.
- `setup` also reports drift: an alert edited in the LangSmith UI shows as `update`.
- The `checks/` files are uploaded byte for byte; the `EVIDENCE` hook in them is inactive in LangSmith.
