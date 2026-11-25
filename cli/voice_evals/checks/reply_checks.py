"""Release-gate checks for one voice-agent reply (no model calls, free).

check_reply(inputs, outputs, reference_outputs) -> {key: score}. The target's output must hold
the reply text in "text" (or "reply" / "output"); optional "ttft" and "total" seconds become
latency scores. Agent-specific checks live in the agent repo with the same function name."""
import re

MARKERS = "●◐○"
INTERNAL_TEXT = re.compile(r"[*#_`{}<>|\[\]]|https?://|^\s*[-•]\s|\n\s*[-•]\s|\b\d{1,3}:\d{2}\b")
FAREWELL = re.compile(
    r"\b(goodbye|bye now|take care|have a (great|nice|wonderful) day|thank you for your time|"
    r"it was a pleasure|au revoir|bonne journ[ée]e|merci pour votre temps)\b", re.I)


def reply_text(outputs):
    for k in ("text", "reply", "output"):
        v = (outputs or {}).get(k)
        if isinstance(v, str):
            return v.strip()
    return ""


def spoken(text):
    """What would be read aloud: drop a leading turn marker; a 'wait' marker means silence."""
    if text[:1] in MARKERS:
        return text[1:].strip() if text[0] == "●" else ""
    return text


def check_reply(inputs, outputs, reference_outputs):
    t = spoken(reply_text(outputs))
    res = {}
    if t:
        res["clean_for_speech"] = int(not INTERNAL_TEXT.search(t))
        res["one_question"] = int(t.count("?") <= 1)
        res["no_farewell"] = int(not FAREWELL.search(t))
        res["reply_words"] = len(t.split())
    if (outputs or {}).get("ttft") is not None:
        res["time_to_first_token_s"] = outputs["ttft"]
    if (outputs or {}).get("total") is not None:
        res["total_time_s"] = outputs["total"]
    return res
