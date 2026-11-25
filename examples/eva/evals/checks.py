"""EVA-specific release checks (rules from Eva's prompt), on top of builtin:reply_checks."""
import re

INTERNAL = re.compile(r"\bCOVERED\b|ledger|\bnotion\b", re.I)
CORRECTING = re.compile(r"\b(you should say|the correct (form|way)|instead of saying|it'?s better to say|"
                        r"small (mistake|correction)|we say)\b", re.I)


def check_reply(inputs, outputs, reference_outputs):
    t = (outputs or {}).get("text", "").strip()
    marker = t[:1] if t[:1] in "●◐○" else ""
    res = {"marker_valid": int(bool(marker))}
    ref = (reference_outputs or {}).get("production_marker")
    if ref:
        res["turn_decision_matches_production"] = int(marker == ref)
    if marker == "●":
        spoken = t[1:].strip()
        res["no_correction"] = int(not CORRECTING.search(spoken))
        if INTERNAL.search(spoken):
            res["clean_for_speech"] = 0   # overrides the generic check for EVA's internal words
    if (outputs or {}).get("thinking_tokens") is not None:
        res["thinking_tokens"] = outputs["thinking_tokens"]
    return res
