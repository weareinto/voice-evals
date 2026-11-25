"""Post to Slack through an incoming webhook (env var named in voice-evals.yaml)."""
import os

import requests


def post(cfg, text):
    env = (cfg.slack or {}).get("webhook_env", "VOICE_EVALS_SLACK_WEBHOOK")
    url = os.environ.get(env)
    if not url:
        return f"not posted: ${env} is not set"
    r = requests.post(url, json={"text": text, "unfurl_links": False}, timeout=30)
    return "posted to Slack" if r.ok else f"Slack error {r.status_code}: {r.text[:120]}"
