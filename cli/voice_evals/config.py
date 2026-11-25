"""voice-evals.yaml loading. Every key is documented in templates/voice-evals.yaml."""
import importlib
import importlib.util
import json
import os
import re

import yaml

CONFIG_NAME = "voice-evals.yaml"
STATE_NAME = "voice-evals.state.json"
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKS_DIR = os.path.join(PKG_DIR, "checks")
TEMPLATES_DIR = os.path.join(PKG_DIR, "templates")

OP_SIGN = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        with open(self.path, encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}
        todo = [k for k, v in _walk(self.data) if isinstance(v, str) and v.startswith("TODO")]
        if todo:
            raise ConfigError(f"{CONFIG_NAME}: fill the TODO values first: {', '.join(todo)}")
        ls = self.data.get("langsmith") or {}
        for k in ("workspace_id", "project"):
            if not ls.get(k):
                raise ConfigError(f"{CONFIG_NAME}: langsmith.{k} is required")
        self.agent = self.data.get("agent", "agent")
        self.workspace_id = ls["workspace_id"]
        self.project = ls["project"]
        self.project_id = ls.get("project_id")
        self.sessions = self.data.get("sessions") or {}
        self.session_root = self.sessions.get("root_name")
        self.link_key = self.sessions.get("link_key")
        self.slack = self.data.get("slack") or {}
        self.evaluators = self.data.get("evaluators") or []
        self.alerts = [normalise_alert(a) for a in self.data.get("alerts") or []]
        self.release = self.data.get("release") or {}
        self.cases_dataset = (self.data.get("datasets") or {}).get("cases")
        self.state_path = os.path.join(self.dir, STATE_NAME)

    def rel(self, p):
        return p if os.path.isabs(p) else os.path.join(self.dir, p)

    def alert(self, code):
        for a in self.alerts:
            if a["code"].lower() == code.lower():
                return a
        raise ConfigError(f"no alert {code} in {CONFIG_NAME}")

    def evaluator_for_root(self, root_name):
        for e in self.evaluators:
            if e.get("root_name") == root_name:
                return e
        return None

    def load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        return {"alerts": {}}

    def save_state(self, state):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")


def _walk(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _walk(v, f"{prefix}{k}.")
    elif isinstance(d, list):
        for i, v in enumerate(d):
            yield from _walk(v, f"{prefix}{i}.")
    else:
        yield prefix.rstrip("."), d


def normalise_alert(a):
    """Shortcut: `key: x` means 'average of feedback key x' (each session writes one score)."""
    a = dict(a)
    if a.get("key"):
        a.setdefault("attribute", "feedback_score")
        a.setdefault("aggregation", "avg")
        a.setdefault("filter", f'eq(feedback_key, "{a["key"]}")')
    a.setdefault("window_minutes", 60)
    a.setdefault("type", "threshold")
    a.setdefault("filter", "")
    a.setdefault("description", a.get("name", ""))
    if not a.get("code"):
        m = re.match(r"^(\S+)\s", a.get("name", ""))
        a["code"] = m.group(1) if m else a.get("name", "?")
    if a.get("attribute") == "feedback_score" and not a.get("key"):
        m = re.search(r'feedback_key,\s*"([^"]+)"', a["filter"])
        a["key"] = m.group(1) if m else None
    return a


def breaches(value, op, threshold):
    if value is None:
        return False
    return {"gt": value > threshold, "gte": value >= threshold,
            "lt": value < threshold, "lte": value <= threshold}[op]


def _check_path(spec, base_dir):
    if spec.startswith("builtin:"):
        return os.path.join(CHECKS_DIR, spec.split(":", 1)[1] + ".py")
    return spec if os.path.isabs(spec) else os.path.join(base_dir, spec)


def load_module(spec, base_dir):
    """'builtin:session_metrics' -> voice_evals.checks.session_metrics; 'x.py' -> that file."""
    if spec.startswith("builtin:"):
        return importlib.import_module(f"voice_evals.checks.{spec.split(':', 1)[1]}")
    path = _check_path(spec, base_dir)
    name = "ve_user_" + re.sub(r"\W", "_", os.path.splitext(os.path.basename(path))[0])
    s = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod


def module_source(spec, base_dir):
    with open(_check_path(spec, base_dir), encoding="utf-8") as f:
        return f.read()


def find_config(path=None):
    if path:
        return Config(path)
    d = os.getcwd()
    while True:
        p = os.path.join(d, CONFIG_NAME)
        if os.path.exists(p):
            return Config(p)
        parent = os.path.dirname(d)
        if parent == d:
            raise ConfigError(f"no {CONFIG_NAME} here or in a parent folder (run `init` first)")
        d = parent
