"""voice-evals: evals for voice agents on LangSmith, alerts and reports in Slack.

Every command prints a short plain-text summary (built to be read by Claude cheaply)."""
import argparse
import glob
import os
import shutil
import sys

from . import __version__
from .config import CONFIG_NAME, TEMPLATES_DIR, ConfigError, find_config


def cmd_init(args):
    out = []
    cwd = os.getcwd()
    cfg_path = os.path.join(cwd, CONFIG_NAME)
    if not args.ci:
        if os.path.exists(cfg_path) and not args.force:
            return f"{CONFIG_NAME} already exists (use --force to overwrite)."
        with open(os.path.join(TEMPLATES_DIR, "voice-evals.yaml"), encoding="utf-8") as f:
            text = f.read().replace("__AGENT__", args.agent or "my-agent")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(text)
        out.append(f"wrote {CONFIG_NAME} (fill the TODO values)")
        rubric = os.path.join(cwd, "rubric.md")
        if not os.path.exists(rubric):
            shutil.copy(os.path.join(TEMPLATES_DIR, "rubric.md"), rubric)
            out.append("wrote rubric.md (judge instructions; adapt to the agent)")
    if args.ci or args.with_ci:
        wf = os.path.join(cwd, ".github", "workflows")
        os.makedirs(wf, exist_ok=True)
        for src in glob.glob(os.path.join(TEMPLATES_DIR, "github", "*.yml")):
            dst = os.path.join(wf, os.path.basename(src))
            if os.path.exists(dst) and not args.force:
                out.append(f"kept existing .github/workflows/{os.path.basename(src)}")
                continue
            shutil.copy(src, dst)
            out.append(f"wrote .github/workflows/{os.path.basename(src)}")
        out.append("repo secrets needed: LANGSMITH_API_KEY, VOICE_EVALS_SLACK_WEBHOOK, ANTHROPIC_API_KEY "
                   "(+ keys the release target uses)")
    return "\n".join(out)


def _ls(cfg):
    from .ls import LS
    return LS(cfg)


def cmd_setup(args):
    from .setup_cmd import setup
    cfg = find_config(args.config)
    return setup(_ls(cfg), cfg, apply=args.apply)


def cmd_report(args):
    from . import report, slack
    cfg = find_config(args.config)
    ls = _ls(cfg)
    text = report.build(ls, cfg, days=args.days, compare=args.compare)
    if args.slack:
        status = slack.post(cfg, report.build(ls, cfg, days=args.days, compare=args.compare, links=True))
        text += f"\n({status})"
    return text


def cmd_triage(args):
    from . import triage
    cfg = find_config(args.config)
    ls = _ls(cfg)
    if args.alert:
        return triage.triage_alert(ls, cfg, args.alert, days=args.days, show_all=args.all)
    if not args.trace_id:
        raise ConfigError("give a trace id or --alert CODE")
    return triage.triage_trace(ls, cfg, args.trace_id, show_all=args.all)


def cmd_release(args):
    from . import release, slack
    cfg = find_config(args.config)
    if args.explain and args.reuse:
        return release.explain(cfg, args.name, args.explain)
    text, passed = release.run(_ls(cfg), cfg, args.name, limit=args.limit, local=args.local,
                               baseline=args.baseline, sets=args.set, concurrency=args.concurrency)
    if args.explain:
        text += "\n\n" + release.explain(cfg, args.name, args.explain)
    if args.slack:
        text += f"\n({slack.post(cfg, text)})"
    args._exit = 0 if passed else 1
    return text


def cmd_add_case(args):
    cfg = find_config(args.config)
    ls = _ls(cfg)
    name = args.dataset or cfg.cases_dataset
    if not name:
        raise ConfigError("set datasets.cases in voice-evals.yaml or pass --dataset")
    run = ls.client.read_run(args.trace_id)
    if run.parent_run_id:
        run = ls.client.read_run(run.trace_id)
    if not ls.client.has_dataset(dataset_name=name):
        ls.client.create_dataset(name, description=f"{cfg.agent}: sessions kept from triage (voice-evals)")
    ex = ls.client.create_example(
        inputs=run.inputs or {}, outputs=run.outputs or {}, dataset_name=name, source_run_id=run.id,
        split=args.split,
        metadata={"note": args.note, "added_by": "voice-evals", "trace_id": str(run.trace_id),
                  "session_start": run.start_time.isoformat()})
    return f"added session {run.id} to '{name}' (example {ex.id}, split '{args.split}')"


def cmd_post(args):
    from . import slack
    cfg = find_config(args.config)
    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    if not text:
        raise ConfigError("nothing to post: give --text or --file")
    return slack.post(cfg, text)


def build_parser():
    p = argparse.ArgumentParser(prog="voice-evals", description=__doc__)
    p.add_argument("--version", action="version", version=f"voice-evals {__version__}")
    p.add_argument("--config", help=f"path to {CONFIG_NAME} (default: search upwards)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write voice-evals.yaml + rubric.md, or the GitHub workflows (--ci)")
    s.add_argument("--agent")
    s.add_argument("--ci", action="store_true", help="only copy the GitHub workflows")
    s.add_argument("--with-ci", action="store_true", help="config and workflows")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("setup", help="sync evaluators and alerts to LangSmith (plan unless --apply)")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("report", help="breach counts per alert (daily digest / weekly review)")
    s.add_argument("--days", type=float, default=1.0)
    s.add_argument("--compare", action="store_true", help="compare with the previous period")
    s.add_argument("--slack", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("triage", help="what broke in one session, with evidence lines")
    s.add_argument("trace_id", nargs="?")
    s.add_argument("--alert", help="alert code, e.g. B6: list breaching sessions, triage the worst")
    s.add_argument("--days", type=float, default=1.0)
    s.add_argument("--all", action="store_true", help="show passing checks and their evidence too")
    s.set_defaults(fn=cmd_triage)

    s = sub.add_parser("release", help="release gate on the test dataset")
    s.add_argument("--name", required=True, help="candidate name (used in the experiment name)")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="candidate setting passed to the target")
    s.add_argument("--limit", type=int)
    s.add_argument("--local", action="store_true", help="run here without creating an experiment")
    s.add_argument("--baseline", help="experiment name to compare with")
    s.add_argument("--concurrency", type=int)
    s.add_argument("--explain", type=int, nargs="?", const=5, help="show the N worst cases")
    s.add_argument("--reuse", action="store_true", help="with --explain: read the last run, do not re-run")
    s.add_argument("--slack", action="store_true")
    s.set_defaults(fn=cmd_release)

    s = sub.add_parser("add-case", help="keep a session in the test dataset (the triage loop)")
    s.add_argument("trace_id")
    s.add_argument("--note", required=True)
    s.add_argument("--dataset")
    s.add_argument("--split", default="from-triage")
    s.set_defaults(fn=cmd_add_case)

    s = sub.add_parser("post", help="post text or a file to the Slack webhook")
    s.add_argument("--text")
    s.add_argument("--file")
    s.set_defaults(fn=cmd_post)
    return p


def main(argv=None):
    import warnings
    warnings.filterwarnings("ignore", message=".*deprecated.*")  # keep output short
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        text = args.fn(args)
    except Exception as exc:  # noqa: BLE001 - one short line instead of a traceback
        from .ls import LangSmithError
        if isinstance(exc, (ConfigError, LangSmithError, FileNotFoundError)) or os.environ.get("VE_DEBUG") is None:
            print(f"error: {type(exc).__name__}: {str(exc)[:400]}", file=sys.stderr)
            return 2
        raise
    if text:
        print(text)
    return getattr(args, "_exit", 0)
