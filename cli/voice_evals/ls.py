"""Thin LangSmith access: the SDK for runs and datasets, REST (with retries) for rules and alerts."""
import os
import time

import requests

API = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/")
UI = os.environ.get("LANGSMITH_UI_URL", "https://smith.langchain.com").rstrip("/")


class LangSmithError(Exception):
    pass


class LS:
    def __init__(self, cfg):
        key = os.environ.get("LANGSMITH_API_KEY")
        if not key:
            raise LangSmithError("LANGSMITH_API_KEY is not set")
        self.cfg = cfg
        os.environ["LANGSMITH_WORKSPACE_ID"] = cfg.workspace_id
        self.h = {"x-api-key": key, "X-Tenant-Id": cfg.workspace_id}
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import warnings

            from langsmith import Client
            warnings.filterwarnings("ignore", message=r".*is deprecated")  # keep CLI output short
            self._client = Client(api_key=self.h["x-api-key"])
        return self._client

    def rest(self, method, path, **kw):
        for attempt in range(7):
            r = requests.request(method, API + path, headers=self.h, timeout=60, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 6:
                time.sleep(min(60, 3 * 2 ** attempt))
                continue
            if not r.ok:
                raise LangSmithError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.text else None

    def project_id(self):
        if not self.cfg.project_id:
            self.cfg.project_id = str(self.client.read_project(project_name=self.cfg.project).id)
        return self.cfg.project_id

    def run_url(self, run):
        trace = getattr(run, "trace_id", None) or run.id
        return f"{UI}/o/{self.cfg.workspace_id}/projects/p/{self.project_id()}/r/{run.id}?trace_id={trace}"

    def _runs(self, start, end, **kw):
        for attempt in range(6):
            try:
                runs = list(self.client.list_runs(project_name=self.cfg.project, start_time=start, **kw))
                break
            except Exception as exc:  # noqa: BLE001 - LangSmith rate limits surface as generic errors
                if attempt == 5 or "429" not in str(exc) and "Too Many" not in str(exc):
                    raise
                time.sleep(min(60, 5 * 2 ** attempt))
        if end is not None:
            runs = [r for r in runs if _aware(r.start_time) < end]
        return runs

    def root_runs(self, start, end=None, name=None):
        flt = f'eq(name, "{name}")' if name else None
        return self._runs(start, end, is_root=True, filter=flt)

    def matching_runs(self, flt, start, end=None):
        return self._runs(start, end, filter=flt or None, select=["id", "trace_id", "start_time"])

    def linked_root(self, root_name, key, value):
        flt = (f'and(eq(name, "{root_name}"), eq(metadata_key, "{key}"), '
               f'eq(metadata_value, "{value}"))')
        runs = list(self.client.list_runs(project_name=self.cfg.project, is_root=True, filter=flt, limit=1))
        return runs[0] if runs else None


def _aware(dt):
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
