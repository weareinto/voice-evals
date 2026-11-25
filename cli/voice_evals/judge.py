"""AI judge: grades one reply 1-5 against the agent's rubric. Default: Claude Haiku (cheap, fast)."""
import json
import os
import time

SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}

TEMPLATE = """{rubric}

Recent conversation:
{history}

Reply to grade:
{reply}

Grade the reply from 1 (bad) to 5 (excellent) using the rubric, with a one-sentence reason."""


def history_text(inputs, n=8):
    turns = inputs.get("contents") or inputs.get("messages") or []
    lines = []
    for t in turns[-n:]:
        text = t.get("text") or t.get("content") or ""
        if isinstance(text, list):
            text = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in text)
        who = "User" if t.get("role") in ("user", "human") else "Agent"
        lines.append(f"{who}: {str(text)[:400]}")
    return "\n".join(lines) or "(none)"


class Judge:
    def __init__(self, cfg_judge, base_dir):
        self.provider = cfg_judge.get("provider", "anthropic")
        default = "claude-haiku-5-5" if self.provider == "anthropic" else "gemini-3.6-flash"
        self.model = cfg_judge.get("model", default)
        rubric = cfg_judge.get("rubric", "rubric.md")
        path = rubric if os.path.isabs(rubric) else os.path.join(base_dir, rubric)
        with open(path, encoding="utf-8") as f:
            self.rubric = f.read().strip()
        self._client = None

    def _call(self, prompt):
        if self.provider == "anthropic":
            import anthropic
            if self._client is None:
                self._client = anthropic.Anthropic(max_retries=5)
            resp = self._client.messages.create(
                model=self.model, max_tokens=1024,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": prompt}])
            if resp.stop_reason == "refusal":
                raise RuntimeError("judge refused")
            return json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
        if self.provider == "gemini":
            from google import genai
            from google.genai import types
            if self._client is None:
                key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
                self._client = genai.Client(api_key=key)
            r = self._client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            return json.loads(r.text)
        raise ValueError(f"unknown judge provider {self.provider}")

    def grade(self, inputs, reply):
        prompt = TEMPLATE.format(rubric=self.rubric, history=history_text(inputs), reply=reply or "(empty)")
        err = None
        for attempt in range(4):
            try:
                d = self._call(prompt)
                return {"key": "judge_quality_1_5", "score": max(1, min(5, int(d["score"]))),
                        "comment": str(d.get("reason", ""))[:300]}
            except Exception as exc:  # noqa: BLE001 - a judge failure must not stop the run
                err = exc
                time.sleep(2 * 2 ** attempt)
        return {"key": "judge_quality_1_5", "score": None, "comment": f"judge failed: {str(err)[:120]}"}
