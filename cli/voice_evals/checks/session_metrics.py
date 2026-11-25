# LangSmith online code evaluator: LDL voice session metrics.
# Runs on each "LDL Voice Evaluation Session" root run and scores the transcript
# in run["outputs"]["messages"]. Feeds alerts B3-B12.
#
#   (B3 agent_silence_turns is computed by the "Scoring output checks" evaluator, which has
#    the timed transcript; this transcript splits learner speech into untimed fragments.)
#   user_repeat_count            (B4)  learner said nearly the same thing (80%+) as one of their
#                                      2 previous messages: they had to repeat themselves
#   false_barge_in_count         (B5)  learner said only "yeah / okay / mm-hmm..." while Eva was
#                                      mid-sentence, which cut Eva off
#   agent_repetition_loop_count  (B6)  Eva asked a question 90%+ similar to one of her 5 previous
#                                      questions, when the learner had not asked her to repeat
#   learner_repeat_request_count (B7)  learner asked Eva to repeat
#   learner_talk_share_pct       (B8)  learner words ÷ all words
#   two_questions_turn_pct       (B9)  Eva turns with 2+ questions
#   wrong_language_turns         (B10) Eva turns (5+ words) in another language than the session
#   internal_text_spoken_count   (B11) Eva turns with text that should not be read aloud
#   self_repetition_turns        (B12) Eva repeated herself within one turn
#
# Transcript format (as traced today):
#   user       "[mm:ss] text"            learner speech, with elapsed-time stamp
#   assistant  "text"                    text the model generated
#   assistant  "● text"                  what was actually played to the learner
#   assistant  "◐"                       empty marker (ignored)
#   assistant  '[{"id": ..., "name": ...' tool call (ignored)
import re
from difflib import SequenceMatcher

# voice-evals triage sets EVIDENCE to a list to collect the lines behind each score.
# It stays None when this file runs as a LangSmith online evaluator.
EVIDENCE = None


def _note(key, text):
    if EVIDENCE is not None and len(EVIDENCE) < 80:
        EVIDENCE.append((key, re.sub(r"\s+", " ", str(text)).strip()[:160]))


STAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}\]\s*")
REPEAT_REQUEST = re.compile(
    r"\b((can|could|would|will) you\b[^.?!]{0,20}\b(repeat|say (that|it) again)|"
    r"repeat (the|your|that|it|again|please)|say (that|it) again|pardon|"
    r"what did you say|i (didn'?t|did not) (hear|catch|understand)|"
    r"(speak|talk) (more )?slow(ly|er))\b|r[ée]p[ée]t",
    re.I,
)
# System instructions injected into the conversation with the learner's role.
SYSTEM_NOTE = re.compile(r"\bthe user\b|in the language of the conversation", re.I)
# Text that should never reach speech: markdown, brackets, braces, tags, URLs,
# list bullets, playback markers or time stamps inside the agent's text.
INTERNAL_TEXT = re.compile(
    r"[*#_`{}<>|\[\]]|https?://|^\s*[-•]\s|\n\s*[-•]\s|[●◐]|\b\d{1,3}:\d{2}\b"
)
BACKCHANNEL = re.compile(
    r"^(yeah|yes|yep|ok|okay|mm-?hmm|uh-?huh|mhm|right|sure|hmm|mm|oh|ah|alright|"
    r"all right|i see|good|great|cool|no)[.!?,]*$", re.I)
SENTENCE_END = re.compile(r"[.!?…\"')]\s*$")
STOPWORDS = {
    "english": set("the a an and is are was were you your i it to of in on for with what do does did "
                   "have has this that how where when why which who can".split()),
    "french": set("le la les un une et est sont était vous tu je il elle de des du en pour avec que "
                  "quoi est-ce qui comment où quand pourquoi ne pas c'est".split()),
}


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    return str(content or "")


def _norm(s):
    s = re.sub(r"[^a-z0-9' ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _sentences(s):
    return [p for p in re.split(r"(?<=[.!?])\s+", s.strip()) if p.strip()]


def _words(s):
    return len(_norm(s).split())


def _session_language(run):
    meta = (run.get("extra") or {}).get("metadata") or run.get("metadata") or {}
    code = str(meta.get("language") or "").lower()
    if code in ("en", "english"):
        return "english"
    if code in ("fr", "french"):
        return "french"
    for m in (run.get("inputs") or {}).get("messages") or []:
        g = re.search(r"conversation in \*\*(\w+)\*\*", _text(m.get("content")))
        if g:
            return g.group(1).lower()
    return None


def _timing_and_loops(msgs, language):
    """B4, B5, B6, B10 from the ordered transcript."""
    user_repeat = barge_in = loops = wrong_lang = 0
    prev_users = []             # previous learner messages (normalized)
    last_played = None          # last line Eva actually spoke
    prev_questions = []         # Eva's previous questions (normalized)
    last_user_asked_repeat = False
    other = [k for k in STOPWORDS if k != language]
    for m in msgs:
        role = m.get("role") or m.get("type")
        t = _text(m.get("content")).strip()
        if role in ("user", "human"):
            if SYSTEM_NOTE.search(t):
                continue
            u = STAMP.sub("", t).strip()
            if BACKCHANNEL.match(u) and last_played and not SENTENCE_END.search(last_played):
                barge_in += 1
                _note("false_barge_in_count", f'learner "{u}" while Eva was at "...{last_played[-70:]}"')
            nu = _norm(u)
            if len(nu.split()) >= 3 and any(SequenceMatcher(None, nu, p).ratio() >= 0.8 for p in prev_users[-2:]):
                user_repeat += 1
                _note("user_repeat_count", f'learner said again: "{u}"')
            prev_users.append(nu)
            last_user_asked_repeat = bool(REPEAT_REQUEST.search(u))
        elif role in ("assistant", "ai"):
            if not t.startswith("●"):
                continue
            spoken = t.lstrip("● ").strip()
            last_played = spoken
            for q in [s for s in _sentences(spoken) if s.endswith("?")]:
                nq = _norm(q)
                if len(nq.split()) >= 3:
                    if not last_user_asked_repeat and any(
                            SequenceMatcher(None, nq, p).ratio() >= 0.9 for p in prev_questions[-5:]):
                        loops += 1
                        _note("agent_repetition_loop_count", f'Eva asked again: "{q}"')
                    prev_questions.append(nq)
            words = _norm(spoken).split()
            if language in STOPWORDS and len(words) >= 5:
                own = sum(w in STOPWORDS[language] for w in words)
                if any(sum(w in STOPWORDS[o] for w in words) > max(own, 1) for o in other):
                    wrong_lang += 1
                    _note("wrong_language_turns", f'Eva: "{spoken[:120]}"')
    out = {"user_repeat_count": user_repeat,
           "false_barge_in_count": barge_in, "agent_repetition_loop_count": loops}
    if language in STOPWORDS:
        out["wrong_language_turns"] = wrong_lang
    return out


def perform_eval(run):
    outputs = run.get("outputs") or {}
    msgs = outputs.get("messages") or []

    # Split into turns: a turn = the agent output that follows a learner message.
    turns = []  # list of (generated_lines, played_lines)
    gen, played = [], []
    user_texts = []
    for m in msgs:
        role = m.get("role") or m.get("type")
        t = _text(m.get("content")).strip()
        if role in ("user", "human"):
            if SYSTEM_NOTE.search(t):
                continue
            if gen or played:
                turns.append((gen, played))
            gen, played = [], []
            user_texts.append(STAMP.sub("", t))
        elif role in ("assistant", "ai"):
            if not t or t.startswith("◐") or t.startswith("[{"):
                continue
            if t.startswith("●"):
                played.append(t.lstrip("● ").strip())
            else:
                gen.append(t)
    if gen or played:
        turns.append((gen, played))

    if not turns:
        return {}

    # B12 self_repetition_turns: turns where the learner heard the same opening twice
    # (agent cut off, then restarted with nearly the same words), or a sentence of
    # 4+ words repeated within the turn.
    rep_turns = 0
    for gen_lines, played_lines in turns:
        hit = False
        for i in range(len(played_lines)):
            for j in range(i + 1, len(played_lines)):
                a, b = _norm(played_lines[i]).split(), _norm(played_lines[j]).split()
                if len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2]:
                    hit = True
        if not hit:
            sents = [_norm(s) for line in gen_lines for s in _sentences(line)]
            sents = [s for s in sents if len(s.split()) >= 4]
            for i in range(len(sents)):
                for j in range(i + 1, len(sents)):
                    if SequenceMatcher(None, sents[i], sents[j]).ratio() >= 0.85:
                        hit = True
        rep_turns += hit
        if hit:
            _note("self_repetition_turns", " | ".join(played_lines or gen_lines)[:150])

    # Agent speech per turn: what was played if traced, else what was generated.
    agent_turn_text = [" ".join(p) if p else " ".join(g) for g, p in turns]
    agent_gen_text = [" ".join(g) for g, _ in turns if g]

    # B8 learner_talk_share_pct: learner words / all words spoken.
    learner_words = sum(_words(u) for u in user_texts)
    agent_words = sum(_words(a) for a in agent_turn_text)
    total = learner_words + agent_words
    talk_share = round(100.0 * learner_words / total, 1) if total else 0.0
    _note("learner_talk_share_pct", f"learner {learner_words} words, Eva {agent_words} words")

    # B9 two_questions_turn_pct: agent turns with 2+ question marks.
    multi_q = 0
    for g in agent_gen_text:
        if g.count("?") >= 2:
            multi_q += 1
            _note("two_questions_turn_pct", f'Eva: "{g[:140]}"')
    two_q_pct = round(100.0 * multi_q / len(agent_gen_text), 1) if agent_gen_text else 0.0

    # B7 learner_repeat_request_count: learner asked the agent to repeat.
    repeat_requests = 0
    for u in user_texts:
        if REPEAT_REQUEST.search(u):
            repeat_requests += 1
            _note("learner_repeat_request_count", f'learner: "{u.strip()[:120]}"')

    # B11 internal_text_spoken_count: agent turns containing text that should not
    # be read aloud.
    internal = 0
    for g in agent_gen_text:
        m = INTERNAL_TEXT.search(g)
        if m:
            internal += 1
            _note("internal_text_spoken_count",
                  f'"{m.group(0).strip() or m.group(0)}" in: "{g[max(0, m.start() - 50):m.end() + 50]}"')

    scores = {
        "self_repetition_turns": rep_turns,
        "two_questions_turn_pct": two_q_pct,
        "learner_repeat_request_count": repeat_requests,
        "internal_text_spoken_count": internal,
    }
    if learner_words:  # no talk share for sessions where the learner never spoke
        scores["learner_talk_share_pct"] = talk_share
    scores.update(_timing_and_loops(msgs, _session_language(run)))
    return scores
