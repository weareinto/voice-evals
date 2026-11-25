"""`release`: replay the test dataset through a candidate, score every reply, check the gate.

The agent repo provides the target (a function that produces the next reply for one dataset
example) and optional extra checks; the plugin provides the generic checks, the judge, the
gate logic and the report. Results are cached in .voice-evals/ so --explain needs no re-run."""
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor

from .checks.reply_checks import reply_text
from .config import ConfigError, load_module
from .judge import Judge
from .ls import UI

GATE = re.compile(r"^\s*(>=|<=|>|<)\s*([\d.]+)\s*$")


def _settings(cfg, sets):
    s = dict(cfg.release.get("settings") or {})
    for kv in sets or []:
        k, _, v = kv.partition("=")
        try:
            v = json.loads(v)
        except ValueError:
            pass
        s[k] = v
    return s


def _load(cfg):
    rel = cfg.release
    if not rel.get("dataset") or not rel.get("target"):
        raise ConfigError("release.dataset and release.target are required in voice-evals.yaml")
    path, _, fn = rel["target"].partition(":")
    target_fn = getattr(load_module(path, cfg.dir), fn or "generate")
    checks = [load_module(c, cfg.dir) for c in rel.get("checks") or ["builtin:reply_checks"]]
    judge = Judge(rel["judge"], cfg.dir) if rel.get("judge") else None
    return target_fn, checks, judge


def _score(checks, judge, inputs, outputs, ref):
    res, comment = {}, ""
    for m in checks:
        res.update(m.check_reply(inputs, outputs, ref or {}) or {})
    if judge:
        j = judge.grade(inputs, reply_text(outputs))
        res[j["key"]] = j["score"]
        comment = j["comment"]
    return res, comment


def _pick(examples, limit):
    if not limit or limit >= len(examples):
        return examples
    step = len(examples) / limit  # spread across the dataset, not the first N
    return [examples[int(i * step)] for i in range(limit)]


def _agg(rows):
    keys = sorted({k for r in rows for k in r["scores"]})
    out = {}
    for k in keys:
        vals = sorted(v for r in rows if (v := r["scores"].get(k)) is not None)
        if not vals:
            continue
        out[k] = {"mean": sum(vals) / len(vals), "n": len(vals),
                  "p50": vals[len(vals) // 2], "p95": vals[min(len(vals) - 1, math.ceil(0.95 * len(vals)) - 1)]}
    return out


def _gate(agg, gate, baseline, tol):
    lines, failed = [], []
    for spec_key, rule in (gate or {}).items():
        m = GATE.match(str(rule))
        if not m:
            continue
        op, thr = m.group(1), float(m.group(2))
        key, stat = spec_key, "mean"
        for suf in ("_p95", "_p50", "_mean"):
            if spec_key.endswith(suf):
                key, stat = spec_key[: -len(suf)], suf[1:]
        if key not in agg:
            lines.append(f"  {spec_key:32} n/a   (gate {op} {thr:g})  no data")
            failed.append(spec_key)
            continue
        v = agg[key][stat]
        ok = {">=": v >= thr, "<=": v <= thr, ">": v > thr, "<": v < thr}[op]
        note = ""
        b = (baseline or {}).get(key)
        if b is not None and stat == "mean":
            note = f"  baseline {b:.2f}"
            higher_better = op in (">=", ">")
            if (higher_better and v < b - abs(b) * tol) or (not higher_better and v > b + abs(b) * tol):
                ok, note = False, note + " (regression)"
        lines.append(f"  {spec_key:32} {v:6.2f} (gate {op} {thr:g}){note}  {'ok' if ok else 'FAIL'}")
        if not ok:
            failed.append(spec_key)
    return lines, failed


def _baseline_stats(ls, name):
    if not name:
        return None
    proj = ls.client.read_project(project_name=name, include_stats=True)
    return {k: v.get("avg") for k, v in (proj.feedback_stats or {}).items() if isinstance(v, dict)}


def _cache_path(cfg, name):
    d = os.path.join(cfg.dir, ".voice-evals")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"release-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json")


def run(ls, cfg, name, limit=None, local=False, baseline=None, sets=None, concurrency=None):
    rel = cfg.release
    target_fn, checks, judge = _load(cfg)
    settings = _settings(cfg, sets)
    examples = _pick(list(ls.client.list_examples(dataset_name=rel["dataset"])), limit)
    if not examples:
        raise ConfigError(f"dataset '{rel['dataset']}' is empty or missing")
    workers = concurrency or int(rel.get("max_concurrency", 2))
    rows, url = [], None

    if local:
        def one(e):
            try:
                o = target_fn(e.inputs, settings)
            except Exception as exc:  # noqa: BLE001
                return {"id": str(e.id), "scores": {}, "reply": f"(target error: {exc})", "comment": ""}
            s, c = _score(checks, judge, e.inputs, o, e.outputs)
            return {"id": str(e.id), "scores": s, "reply": reply_text(o), "comment": c}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, examples))
    else:
        os.environ.setdefault("TQDM_DISABLE", "1")  # no progress bar in the output Claude reads
        from langsmith import evaluate

        def target(inputs):
            return target_fn(inputs, settings)

        def checks_eval(inputs, outputs, reference_outputs):
            res = {}
            for m in checks:
                res.update(m.check_reply(inputs, outputs, reference_outputs or {}) or {})
            return {"results": [{"key": k, "score": v} for k, v in res.items() if v is not None]}

        evaluators = [checks_eval]
        if judge:
            evaluators.append(lambda inputs, outputs, reference_outputs: judge.grade(inputs, reply_text(outputs)))
        res = evaluate(target, data=examples, evaluators=evaluators, experiment_prefix=f"{cfg.agent}-{name}",
                       description=f"voice-evals release gate: {name}",
                       metadata={"candidate": name, "settings": settings,
                                 "judge": getattr(judge, "model", None)},
                       max_concurrency=workers)
        for r in res:
            scores, comment = {}, ""
            for er in (r.get("evaluation_results") or {}).get("results", []):
                scores[er.key] = er.score
                if er.key == "judge_quality_1_5" and er.comment:
                    comment = er.comment
            run_ = r.get("run")
            rows.append({"id": str(r["example"].id), "scores": scores,
                         "reply": reply_text(getattr(run_, "outputs", None) or {}), "comment": comment})
        try:
            exp = ls.client.read_project(project_name=res.experiment_name)
            url = (f"{UI}/o/{cfg.workspace_id}/datasets/{exp.reference_dataset_id}/compare"
                   f"?selectedSessions={exp.id}")
        except Exception:  # noqa: BLE001
            url = res.experiment_name

    with open(_cache_path(cfg, name), "w", encoding="utf-8") as f:
        json.dump({"name": name, "settings": settings, "url": url, "rows": rows}, f, ensure_ascii=False)

    agg = _agg(rows)
    gate_lines, failed = _gate(agg, rel.get("gate"), _baseline_stats(ls, baseline),
                               float(rel.get("regression_tolerance", 0.05)))
    judge_note = f", judge {judge.model}" if judge else ""
    out = [f"Release gate: {name} ({len(rows)} cases{judge_note}{', local run' if local else ''})"]
    out += gate_lines
    if url:
        out.append(f"Experiment: {url}")
    verdict = "FAIL: " + ", ".join(failed) if failed else "PASS"
    out.append(verdict)
    return "\n".join(out), not failed


def explain(cfg, name, n=5):
    path = _cache_path(cfg, name)
    if not os.path.exists(path):
        raise ConfigError(f"no cached run for '{name}': run `release --name {name}` first")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    gate = cfg.release.get("gate") or {}
    binary = [k for k in gate if not k.endswith(("_p95", "_p50")) and k != "judge_quality_1_5"]

    def badness(r):
        s = r["scores"]
        fails = sum(1 for k in binary if s.get(k) == 0)
        return (-fails, s.get("judge_quality_1_5") or 9)

    out = [f"Worst {n} of {len(data['rows'])} cases ({name}):"]
    for r in sorted(data["rows"], key=badness)[:n]:
        s = r["scores"]
        fails = [k for k in binary if s.get(k) == 0]
        j = s.get("judge_quality_1_5")
        out.append(f"- {r['id'][:8]} judge {j if j is not None else '-'}"
                   + (f" | failed: {', '.join(fails)}" if fails else "")
                   + (f" | {r['comment'][:140]}" if r.get("comment") else ""))
        out.append(f"    reply: {r['reply'][:180]!r}")
    return "\n".join(out)
