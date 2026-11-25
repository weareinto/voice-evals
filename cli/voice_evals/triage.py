"""`triage`: re-run the checks on one session locally and print only what broke, with the
exact lines that made each check fire. Never prints the whole transcript."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .config import OP_SIGN, breaches, load_module
from .report import evaluate_alert


def run_dict(r):
    extra = r.extra or {}
    return {"id": str(r.id), "name": r.name, "inputs": r.inputs or {}, "outputs": r.outputs or {},
            "extra": extra, "metadata": extra.get("metadata") or {},
            "start_time": r.start_time, "end_time": r.end_time}


def _check(cfg, ev, run):
    mod = load_module(ev["code"], cfg.dir)
    mod.EVIDENCE = []
    try:
        scores = mod.perform_eval(run_dict(run)) or {}
        evidence = list(mod.EVIDENCE)
    finally:
        mod.EVIDENCE = None
    return scores, evidence


def triage_trace(ls, cfg, trace_id, show_all=False, max_lines=3):
    run = ls.client.read_run(trace_id)
    if run.parent_run_id:
        run = ls.client.read_run(run.trace_id)
    targets = [(run, cfg.evaluator_for_root(run.name))]
    meta = (run.extra or {}).get("metadata") or {}
    link = meta.get(cfg.link_key) if cfg.link_key else None
    if link:
        for ev in cfg.evaluators:
            rn = ev.get("root_name")
            if rn and rn != run.name:
                linked = ls.linked_root(rn, cfg.link_key, link)
                if linked:
                    targets.append((linked, ev))
    sess = next((r for r, _ in targets if r.name == cfg.session_root), run)
    smeta = (sess.extra or {}).get("metadata") or {}
    mins = (sess.end_time - sess.start_time).total_seconds() / 60 if sess.end_time else None
    head = f"Session {sess.id} | {sess.start_time:%d %b %H:%M} UTC"
    if mins is not None:
        head += f" | {mins:.0f} min"
    if smeta.get("language"):
        head += f" | {smeta['language']}"
    if sess is not run:
        head += f"\n(alerted run: {run.name} {run.id})"
    out = [head]
    alerts_by_key = {a["key"]: a for a in cfg.alerts if a.get("key")}
    ok = []
    for r, ev in targets:
        if not ev:
            out.append(f"  (no evaluator configured for root run '{r.name}')")
            continue
        scores, evidence = _check(cfg, ev, r)
        ev_by_key = defaultdict(list)
        for k, text in evidence:
            ev_by_key[k].append(text)
        for key, val in scores.items():
            a = alerts_by_key.get(key)
            label = f"{a['code']} {key}" if a else key
            hit = a and breaches(val, a["operator"], a["threshold"])
            if hit:
                out.append(f"BREACH {label} = {val}  (alert {OP_SIGN[a['operator']]} {a['threshold']})")
            elif show_all:
                out.append(f"ok     {label} = {val}")
            else:
                ok.append(f"{a['code'] if a else key} {val}")
                continue
            for t in ev_by_key.get(key, [])[:max_lines]:
                out.append(f"         - {t}")
            more = len(ev_by_key.get(key, [])) - max_lines
            if more > 0:
                out.append(f"         (+{more} more)")
    if ok:
        out.append("ok: " + ", ".join(ok))
    out.append(f"Link: {ls.run_url(sess)}")
    return "\n".join(out)


def triage_alert(ls, cfg, code, days=1.0, top=5, show_all=False):
    a = cfg.alert(code)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    roots = ls.root_runs(start, now)
    sessions = [r for r in roots if not cfg.session_root or r.name == cfg.session_root]
    res = evaluate_alert(ls, cfg, a, roots, sessions, start, now)
    if res["kind"] == "skip":
        return f"{a['name']}: this alert type cannot be summarised per session."
    if not res["bad"]:
        return f"{a['name']}: no breaching session in the last {days:g} day(s) ({res['n']} checked)."
    desc = a["operator"] in ("gt", "gte") or res["kind"] == "runs"
    bad = sorted(res["bad"], key=lambda x: -x[1] if desc else x[1])
    out = [f"{a['name']}: {len(bad)}/{res['n']} breaching in the last {days:g} day(s). Worst:"]
    for r, v in bad[:top]:
        out.append(f"  {r.id}  {r.start_time:%d %b %H:%M}  value {v:g}")
    out.append("")
    out.append(triage_trace(ls, cfg, str(bad[0][0].id), show_all=show_all))
    return "\n".join(out)
