"""EVA release target: produce Eva's next reply for one dataset moment with candidate settings.

Dataset "Eva next-reply turns": inputs = {"system": Eva's system prompt, "contents": the
conversation so far in production Gemini format}. Settings come from voice-evals.yaml
(release.settings) and `--set key=value`:
  model            Gemini model (default gemini-3.6-flash)
  thinking_level   minimal | low | medium | high
  system_prompt    path to a candidate system prompt file (replaces the recorded one)
Needs GOOGLE_API_KEY."""
import os
import re
import time

_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    return _client


def _retry_wait(exc, attempt):
    m = re.search(r"retry in ([\d.]+)s", str(exc))
    return float(m.group(1)) + 1 if m else min(60, 5 * 2 ** attempt)


def generate(inputs, settings):
    from google.genai import types
    system = inputs["system"]
    if settings.get("system_prompt"):
        with open(settings["system_prompt"], encoding="utf-8") as f:
            system = f.read()
    cfg = types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=4096,
        thinking_config=types.ThinkingConfig(thinking_level=settings.get("thinking_level", "low")))
    msgs = [types.Content(role=c["role"], parts=[types.Part(text=c["text"])]) for c in inputs["contents"]]
    model = settings.get("model", "gemini-3.6-flash")
    for attempt in range(6):
        try:
            t0, first, text, usage = time.perf_counter(), None, "", None
            for chunk in _gemini().models.generate_content_stream(model=model, contents=msgs, config=cfg):
                if chunk.text:
                    if first is None:
                        first = time.perf_counter() - t0
                    text += chunk.text
                if chunk.usage_metadata:
                    usage = chunk.usage_metadata
            total = time.perf_counter() - t0
            return {"text": text.strip(), "ttft": round(first if first is not None else total, 3),
                    "total": round(total, 3),
                    "thinking_tokens": getattr(usage, "thoughts_token_count", None) or 0}
        except Exception as exc:  # noqa: BLE001 - rate limits and transient errors
            if attempt == 5:
                raise
            time.sleep(_retry_wait(exc, attempt))
