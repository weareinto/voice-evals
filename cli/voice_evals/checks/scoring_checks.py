# LangSmith online code evaluator: LDL scoring output checks.
# Runs on each "skills_validation_evaluation_agent" root run (the post-call scoring
# agent) and checks its structured result. Feeds alerts B3, B13, B14 and B15.
#
#   agent_silence_turns           (B3)  in the timed transcript given to the scoring agent: Eva
#                                       started speaking 8+ seconds after the learner's last word
#
#   notion_coverage_pct           (B13) mandatory notions that got a score ÷ all mandatory
#                                       notions. A null score means N/E (not evaluated).
#   evaluation_errors_count       (B14) problems in the scoring output:
#                                       - the output could not be parsed
#                                       - a general competency has no score
#                                       - a quote in a learner-facing reasoning is not in the transcript
#                                       - learner-facing text states a level or a score
#   result_delivery_delay_minutes (B15) APPROXIMATION: minutes the scoring agent took (run start to
#                                       end). The wait before scoring and the delivery to LDL are
#                                       not traced, so they are not included.
import ast
import re
from datetime import datetime
from difflib import SequenceMatcher

# voice-evals triage sets EVIDENCE to a list to collect the lines behind each score.
# It stays None when this file runs as a LangSmith online evaluator.
EVIDENCE = None


def _note(key, text):
    if EVIDENCE is not None and len(EVIDENCE) < 80:
        EVIDENCE.append((key, re.sub(r"\s+", " ", str(text)).strip()[:160]))


QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”|«\s*([^»]+?)\s*»')
# Words just before a quote that mean it is a correction or a suggested form, not the
# learner's own words ("on dirait plutôt «...»", "should be "..."", "→ "..."").
SUGGESTION = re.compile(
    r"→|->|\b(say|dire|dira|dirait|plutôt|should|better|clearer|could|would|such as|like|comme|try|"
    r"essaie|pense|instead|au lieu|rather|correct|corrig|devient|becomes|use|utilise|for example|"
    r"description)\b", re.I)
LEVEL_OR_SCORE = re.compile(
    r"\b(niveau|level)\s*\d|\b\d\s*/\s*3\b|\bscore\b|\b(note|points?)\s*(de|:)?\s*\d", re.I)


def _norm(s):
    s = s.lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœæ' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _transcript(text):
    """Learner and agent words from the <transcript> block of the scoring prompt."""
    m = re.search(r"<transcript>(.*?)</transcript>", text or "", re.S)
    if not m:
        return None
    parts = re.findall(r"'text': (?:\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)')", m.group(1))
    return _norm(" ".join(a or b for a, b in parts)) if parts else _norm(m.group(1))


def _quote_missing(quote, transcript):
    """True if no stretch of the transcript matches the quote at 60% or more
    (tolerates speech-recognition and punctuation differences)."""
    qw, tw = _norm(quote).split(), transcript.split()
    n, best = len(qw), 0.0
    for i in range(0, max(1, len(tw) - n + 1)):
        best = max(best, SequenceMatcher(None, qw, tw[i:i + n]).ratio())
        if best >= 0.6:
            return False
    return True


def _learner_quotes(text):
    """Quotes of 3+ words that claim to be the learner's words. Skipped: grammar patterns
    ("there is/there are", "am + not") and corrections or suggested forms."""
    out = []
    for m in QUOTE.finditer(text or ""):
        q = next(g for g in m.groups() if g)
        if len(_norm(q).split()) < 3 or "/" in q or "+" in q:
            continue
        if SUGGESTION.search(text[max(0, m.start() - 45):m.start()]) or "→" in text[max(0, m.start() - 80):m.start()]:
            continue
        out.append(q)
    return out


def _clock(s):
    parts = [int(x) for x in str(s).split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def _slow_replies(prompt, gap_s=8):
    """Learner -> Eva transitions where Eva started gap_s+ seconds after the learner stopped.
    The first speaker in the transcript is Eva (the scripted opening)."""
    m = re.search(r"<transcript>(.*?)</transcript>", prompt or "", re.S)
    if not m:
        return None
    try:
        utts = ast.literal_eval(m.group(1).strip())
    except (ValueError, SyntaxError):
        return None
    if not utts:
        return None
    agent = utts[0].get("speaker")
    slow = 0
    for a, b in zip(utts, utts[1:]):
        if a.get("speaker") != agent and b.get("speaker") == agent:
            gap = _clock(b["start"]) - _clock(a["end"])
            if gap >= gap_s:
                slow += 1
                _note("agent_silence_turns", f'{gap:.0f}s silence at {b["start"]} after learner: '
                      f'"{str(a.get("text", ""))[-80:]}"')
    return slow


def _time(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return None


def perform_eval(run):
    outputs = run.get("outputs") or {}
    parsed = outputs.get("parsed") or {}
    scores = {}

    notions = parsed.get("mandatory_notions") or []
    if notions:
        scored = sum(1 for n in notions if isinstance(n, dict) and n.get("score") is not None)
        scores["notion_coverage_pct"] = round(100.0 * scored / len(notions), 1)
        for n in notions:
            if isinstance(n, dict) and n.get("score") is None:
                _note("notion_coverage_pct", f'not assessed: {n.get("name") or n.get("notion") or n.get("id") or "?"}')

    errors = 0
    if outputs.get("parsing_error") or not parsed:
        errors += 1
        _note("evaluation_errors_count", "scoring output could not be parsed")
    comps = parsed.get("general_competencies") or []
    for c in comps:
        if not isinstance(c, dict) or c.get("score") is None:
            errors += 1
            _note("evaluation_errors_count", f'competency without score: {c.get("name") if isinstance(c, dict) else c}')

    inputs = run.get("inputs") or {}
    prompt = inputs.get("input") if isinstance(inputs.get("input"), str) else str(inputs)
    transcript = _transcript(prompt)
    learner_texts = [n.get("reasoning") or "" for n in notions + comps if isinstance(n, dict)]
    learner_texts.append(parsed.get("external_feedback") or "")
    missing = []
    if transcript:
        for t in learner_texts:
            for q in _learner_quotes(t):
                if _quote_missing(q, transcript):
                    missing.append(q)
    errors += len(missing)
    for q in missing:
        _note("evaluation_errors_count", f'quote not in transcript: "{q[:100]}"')
    for t in learner_texts:
        m = LEVEL_OR_SCORE.search(t)
        if m:
            errors += 1
            _note("evaluation_errors_count", f'level/score shown to learner: "...{t[max(0, m.start() - 50):m.end() + 30]}..."')
    scores["evaluation_errors_count"] = errors

    slow = _slow_replies(prompt)
    if slow is not None:
        scores["agent_silence_turns"] = slow

    start, end = _time(run.get("start_time")), _time(run.get("end_time"))
    if start and end:
        scores["result_delivery_delay_minutes"] = round((end - start).total_seconds() / 60.0, 2)
    return scores
