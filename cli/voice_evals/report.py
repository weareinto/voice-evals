"""`report`: per-alert breach counts over a window (daily digest, weekly review).

Every alert in voice-evals.yaml is summarised per session, so the report says how many sessions
broke each threshold, not just whether a 60-minute average crossed it."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from .config import OP_SIGN, breaches


def evaluate_alert(ls, cfg, a, roots, sessions, start, end):
    """-> dict(code, name, kind, n, bad=[(run, value)], extra)"""
    res = {"code": a["code"], "name": a["name"], "kind": "skip", "n": 0, "bad": []}
    attr = a.get("attribute")
    if attr == "feedback_score" and a.get("key"):
        vals = []
        for r in roots:
            s = (r.feedback_stats or {}).get(a["key"]) or {}
            if s.get("avg") is not None:
                vals.append((r, float(s["avg"])))
        res.update(kind="sessions", n=len(vals),
                   bad=[(r, v) for r, v in vals if breaches(v, a["operator"], a["threshold"])])
    elif attr == "total_cost":
        vals = [(r, float(r.total_cost)) for r in sessions if r.total_cost is not None]
        res.update(kind="sessions", n=len(vals),
                   bad=[(r, v) for r, v in vals if breaches(v, a["operator"], a["threshold"])])
    elif attr == "run_count" and a.get("filter"):
        runs = ls.matching_runs(a["filter"], start, end)
        per_trace = Counter(str(r.trace_id) for r in runs)
        by_id = {str(r.id): r for r in sessions}
        res.update(kind="runs", n=len(sessions), count=len(runs),
                   bad=sorted(((by_id[t], c) for t, c in per_trace.items() if t in by_id),
                              key=lambda x: -x[1]))
    return res


def collect(ls, cfg, start, end):
    roots = ls.root_runs(start, end)
    sessions = [r for r in roots if not cfg.session_root or r.name == cfg.session_root]
    return sessions, [evaluate_alert(ls, cfg, a, roots, sessions, start, end) for a in cfg.alerts]


def _fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _line(a_cfg, r, prev=None):
    sign = f"{OP_SIGN[a_cfg['operator']]}{_fmt(a_cfg['threshold'])}"
    if r["kind"] == "runs":
        txt = (f"{r['count']} matching runs in {len(r['bad'])}/{r['n']} sessions")
    else:
        worst = max((v for _, v in r["bad"]), default=None) if a_cfg["operator"] in ("gt", "gte") \
            else min((v for _, v in r["bad"]), default=None)
        txt = f"{len(r['bad'])}/{r['n']} sessions {sign}" + (f" (worst {_fmt(worst)})" if worst is not None else "")
    if prev is not None and prev["kind"] != "skip":
        txt += f"  [prev {len(prev['bad'])}/{prev['n']}]"
    return f"{r['name']}: {txt}"


def build(ls, cfg, days=1.0, compare=False, links=False):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    sessions, results = collect(ls, cfg, start, now)
    prev = None
    if compare:
        _, prev = collect(ls, cfg, start - timedelta(days=days), start)
    span = f"last {int(days)} days" if days >= 2 else f"last {int(days * 24)}h"
    lines = [f"*{cfg.agent} voice evals* - {span} - {len(sessions)} sessions"]
    ok, nodata, hits = [], [], Counter()
    rows = []
    for i, (a, r) in enumerate(zip(cfg.alerts, results)):
        if r["kind"] == "skip":
            continue
        if r["n"] == 0 or (r["kind"] == "runs" and not sessions):
            nodata.append(a["code"])
            continue
        for run, _ in r["bad"]:
            hits[str(run.id)] += 1
        p = prev[i] if prev else None
        worse = p is not None and p["n"] and r["n"] and \
            len(r["bad"]) / r["n"] > len(p["bad"]) / p["n"] + 0.05
        if r["bad"]:
            share = len(r["bad"]) / max(r["n"], 1)
            mark = ":red_circle:" if share >= 0.25 else ":large_orange_circle:"
            rows.append((share, f"{mark} {_line(a, r, p)}" + ("  :arrow_up:" if worse else "")))
        else:
            ok.append(a["code"])
    lines += [t for _, t in sorted(rows, key=lambda x: -x[0])]
    if ok:
        lines.append(f":large_green_circle: OK: {', '.join(ok)}")
    if nodata:
        lines.append(f":white_circle: No data: {', '.join(nodata)}")
    if hits:
        by_id = {str(r.id): r for r in sessions}
        worst = [by_id[k] for k, _ in hits.most_common(3) if k in by_id]
        if worst:
            lines.append("Worst sessions:")
            for s in worst:
                codes = [r["code"] for r in results if any(str(x.id) == str(s.id) for x, _ in r["bad"])]
                ref = f"<{ls.run_url(s)}|{s.start_time:%d %b %H:%M}>" if links else f"{s.id} ({s.start_time:%d %b %H:%M})"
                lines.append(f"  {ref}: {', '.join(codes)}")
    return "\n".join(lines)
