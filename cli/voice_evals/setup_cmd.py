"""`setup`: make LangSmith match voice-evals.yaml (online evaluators + alerts). Plan by default,
writes only with --apply. Alert rule IDs are kept in voice-evals.state.json (LangSmith has no
list endpoint for alerts)."""
from datetime import datetime, timedelta, timezone

from .config import module_source

EVAL_FIELDS = ("filter", "trace_filter", "sampling_rate", "is_enabled", "extend_evaluator_trace_retention")
ALERT_FIELDS = ("name", "description", "type", "attribute", "aggregation", "operator", "threshold",
                "window_minutes", "filter")


def evaluator_body(cfg, e, project_id):
    flt = e.get("filter") or f'and(eq(is_root, true), eq(name, "{e["root_name"]}"))'
    return {
        "display_name": e["name"],
        "session_id": project_id,
        "sampling_rate": float(e.get("sampling_rate", 1.0)),
        "filter": flt,
        "trace_filter": e.get("trace_filter"),
        "is_enabled": bool(e.get("enabled", True)),
        "extend_evaluator_trace_retention": bool(e.get("extend_retention", False)),
        "code_evaluators": [{"code": module_source(e["code"], cfg.dir), "language": "python"}],
    }


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return (a or None) == (b or None)


def _current_code(rule):
    ce = rule.get("code_evaluators") or []
    return (ce[0] or {}).get("code") if ce else None


def setup(ls, cfg, apply=False):
    out = []
    pid = ls.project_id()
    rules = ls.rest("GET", "/api/v1/runs/rules", params={"session_id": pid}) or []
    by_name = {r.get("display_name"): r for r in rules}
    out.append(f"Evaluators ({cfg.project}):")
    for e in cfg.evaluators:
        want = evaluator_body(cfg, e, pid)
        cur = by_name.get(e["name"])
        if not cur:
            action, diffs = "create", []
        else:
            diffs = [k for k in EVAL_FIELDS if not _same(cur.get(k), want.get(k))]
            if (_current_code(cur) or "").strip() != want["code_evaluators"][0]["code"].strip():
                diffs.append("code")
            action = "update" if diffs else "unchanged"
        out.append(f"  {action:9} {e['name']}" + (f" ({', '.join(diffs)})" if diffs else ""))
        if not apply or action == "unchanged":
            continue
        if action == "create":
            if e.get("backfill_days"):
                since = datetime.now(timezone.utc) - timedelta(days=int(e["backfill_days"]))
                want["backfill_from"] = since.isoformat()
            ls.rest("POST", "/api/v1/runs/rules", json=want)
        else:
            ls.rest("PATCH", f"/api/v1/runs/rules/{cur['id']}", json=want)
        out[-1] += "  -> done"

    state = cfg.load_state()
    ids = state.setdefault("alerts", {})
    channel = (cfg.slack or {}).get("alerts_channel")
    out.append("Alerts:")
    changed = 0
    for a in cfg.alerts:
        rule = {k: a[k] for k in ALERT_FIELDS if k in a}
        rid = ids.get(a["code"])
        if rid:
            cur = ls.rest("GET", f"/api/v1/platform/alerts/{pid}/{rid}")
            cr = cur.get("rule", cur)
            diffs = [k for k in rule if not _same(cr.get(k), rule[k])]
            action = "update" if diffs else "unchanged"
        else:
            cur, diffs, action = None, [], "create"
        if action == "unchanged":
            continue
        changed += 1
        out.append(f"  {action:9} {a['name']}" + (f" ({', '.join(diffs)})" if diffs else ""))
        if not apply:
            continue
        if action == "create":
            if not channel:
                out[-1] += "  -> skipped: slack.alerts_channel missing"
                continue
            resp = ls.rest("POST", f"/api/v1/platform/alerts/{pid}",
                           json={"rule": rule, "actions": [{"target": "slack", "config": channel}]})
            ids[a["code"]] = resp["rule"]["id"]
            cfg.save_state(state)
        else:
            merged = {k: v for k, v in cr.items()
                      if k not in ("created_at", "updated_at", "session_name") and v is not None}
            merged.update(rule)
            actions = [{k: x[k] for k in ("id", "alert_rule_id", "target", "config") if k in x}
                       for x in cur.get("actions", [])]
            ls.rest("PATCH", f"/api/v1/platform/alerts/{pid}/{rid}", json={"rule": merged, "actions": actions})
        out[-1] += "  -> done"
    unchanged = len(cfg.alerts) - changed
    out.append(f"  unchanged: {unchanged} of {len(cfg.alerts)}")
    if not apply and any(w in line for line in out for w in (" create ", " update ")):
        out.append("Plan only. Run `setup --apply` to write these changes.")
    return "\n".join(out)
