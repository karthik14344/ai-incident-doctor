"""Week 5 - guardrails for the KnowledgeAI chat pipeline.

One module, one function per guardrail, every verdict a dataclass: each
guardrail is independently testable, the full set is visible at a glance, and
the gateway composes them at three points of the request it already controls:

    screen_input(question)                 before retrieval / DB write
    check_scope(...)                       after retrieval, before the LLM call
    screen_output(answer, context, q)      after generation, before the user sees it
    RateLimiter                            before anything expensive happens

Every guardrail here exists because a concrete failure was reproduced against
the live pipeline with mistral (see data/guardrails/before/ and the Week-5
report). Nothing is speculative: a check that no reproduced failure justifies
lives in the "considered but skipped" section of the report, not in this file.

The screens are deliberately deterministic and lexical - the same property the
Week-4 evaluation metrics chose - so a guardrail decision can always be
explained by pointing at the exact pattern or threshold that fired.
"""

import re
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# The verdict every guardrail returns
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """What one guardrail decided about one request or response."""
    guardrail: str
    allowed: bool
    reason: str
    action: str = "allow"          # allow | block | annotate
    note: Optional[str] = None     # shown/annotated when action == "annotate"

    def to_meta(self) -> dict:
        return {"guardrail": self.guardrail, "allowed": self.allowed,
                "reason": self.reason, "action": self.action, "note": self.note}


def _block(guardrail: str, reason: str) -> Verdict:
    return Verdict(guardrail=guardrail, allowed=False, reason=reason, action="block")


def _allow(guardrail: str, reason: str = "no concern detected") -> Verdict:
    return Verdict(guardrail=guardrail, allowed=True, reason=reason)


def _annotate(guardrail: str, note: str) -> Verdict:
    return Verdict(guardrail=guardrail, allowed=True, reason="answered with a caution",
                   action="annotate", note=note)


# ---------------------------------------------------------------------------
# G1 - input validation
# ---------------------------------------------------------------------------

#: A chat question past this many characters is not a question, it is a paste -
#: and the oversized-input reproduction showed a 25k-char paste reaching the
#: model and dying there, surfacing "[LLM Stream error: ]" as the answer.
MAX_QUESTION_CHARS = 2000
MIN_QUESTION_CHARS = 2          # trims "" and whitespace-only input
MAX_CONTROL_CHAR_RATIO = 0.05   # garbled binary in a text box is not a question
MAX_SINGLE_CHAR_RUN = 60        # "aaaaaa..." spam

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_input(question: str) -> Verdict:
    text = question or ""
    if len(text.strip()) < MIN_QUESTION_CHARS:
        return _block("input_validation", "question is empty or too short to answer")
    if len(text) > MAX_QUESTION_CHARS:
        return _block("input_validation",
                      f"question exceeds the {MAX_QUESTION_CHARS}-character limit "
                      f"({len(text)} characters)")
    visible = max(len(text), 1)
    if len(_CONTROL_RE.findall(text)) / visible > MAX_CONTROL_CHAR_RATIO:
        return _block("input_validation", "question contains control/binary characters")
    runs = re.findall(r"(.)\1{%d,}" % MAX_SINGLE_CHAR_RUN, text, flags=re.S)
    if runs:
        return _block("input_validation", "question is mostly one repeated character")
    return _allow("input_validation")


# ---------------------------------------------------------------------------
# G2 - prompt injection / instruction extraction
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|earlier|above|original|previous)\s+"
     r"(instructions?|prompts?|rules?|directions?)", "instruction-override"),
    (r"disregard\s+(all\s+|the\s+)?(previous|prior|above|earlier)", "instruction-override"),
    (r"(reveal|show|print|repeat|display|output|give\s+me)\s+(me\s+)?(your\s+|the\s+)?"
     r"(full\s+|exact\s+|complete\s+|entire\s+|initial\s+|original\s+|first\s+)?"
     r"(system\s+)?(prompt|instructions|system\s+message)", "prompt-extraction"),
    (r"(your\s+)?system\s+prompt\b.{0,40}(verbatim|exactly|full|text)", "prompt-extraction"),
    (r"\bsystem\s*(override|message|prompt)\s*:", "override-marker"),
    (r"from\s+now\s+on,?\s+you\s+(are|will\s+be|must)", "role-override"),
    (r"you\s+are\s+now\s+(a|an|no\s+longer)", "role-override"),
    (r"new\s+instructions?\s*:", "override-marker"),
    (r"developer\s+mode|dan\s+mode|jailbreak", "jailbreak-marker"),
]


def check_prompt_injection(question: str) -> Verdict:
    lowered = (question or "").lower()
    for pattern, kind in _INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            return _block("prompt_injection",
                          f"request matches a prompt-injection pattern ({kind})")
    return _allow("prompt_injection")


# ---------------------------------------------------------------------------
# G5 - harmful / off-domain content requests
# ---------------------------------------------------------------------------

_HARMFUL_PATTERNS = [
    r"\b(insult|roast|mock|humiliate|demean)\b.{0,40}\b(professor|teacher|student|"
    r"person|people|someone|him|her|them)\b",
    r"\b(write|generate|compose|draft)\b.{0,30}\b(insulting|abusive|hateful|offensive|"
    r"vulgar|threatening)\b",
    r"\bhate\s+speech\b|\bharass(ment|ing)?\b.{0,30}\b(write|help|draft)\b",
    r"how\s+(do|can|should)\s+(i|we|you)\s+(cheat|hack|steal|plagiarize|plagiarise)\b",
    r"\b(help|assist)\b.{0,20}\b(harass|bully|threaten|stalk|insult)\b",
    r"\b(write|generate|create)\b.{0,30}\b(malware|virus|ransomware|phishing|keylogger)\b",
    r"\b(hurt|harm|attack)\s+(myself|someone|others)\b",
]


def check_content_policy(question: str) -> Verdict:
    lowered = (question or "").lower()
    for pattern in _HARMFUL_PATTERNS:
        if re.search(pattern, lowered):
            return _block("content_policy",
                          "request asks for content outside a policy assistant's domain "
                          "or that could harm others")
    return _allow("content_policy")


# ---------------------------------------------------------------------------
# G6 - authority / impersonation
# ---------------------------------------------------------------------------

# NOTE: the non-capturing group matters - this fragment is spliced into larger
# patterns, and a bare alternation would let "warden" or "authority" match
# anywhere (the false-positive the unit tests caught immediately).
_AUTHORITY_FIGURES = (r"(?:(?:chief|university|academic|medical|hostel|placement)\s+)?"
                      r"(?:dean|warden|registrar|professor|principal|director|"
                      r"chairman|officer|cmo|medical\s+officer|authorities?|official)")
_IMPERSONATION_PATTERNS = [
    r"(pretend|act|roleplay|role-play)\s+(that\s+)?(you\s+are|to\s+be)\s+(the\s+|a\s+|an\s+)?"
    + _AUTHORITY_FIGURES,
    r"\b(act|speak|talk|respond|roleplay|role-play)\s+as\s+"
    r"(if\s+(you\s+(are|were)\s+))?(the\s+|a\s+|an\s+)?"
    + _AUTHORITY_FIGURES,
    r"\bas\s+the\s+" + _AUTHORITY_FIGURES + r",?\s+(i\s+)?(confirm|approve|authorise|"
    r"authorize|allow|exempt|grant|waive|hereby)",
    r"(you\s+are|become)\s+the\s+" + _AUTHORITY_FIGURES + r"\b.{0,60}"
    r"(confirm|approve|exempt|waive|declare|announce)",
    r"(state|say|speak|answer)\s+(confidently\s+)?as\s+an?\s+official\s+(authority|source|"
    r"representative)",
    r"\bas\s+an?\s+official\s+(university\s+)?authorit(?:y|ies)\b.{0,30}"
    r"\b(declare|announce|confirm|state|proclaim|say)\b",
]


def check_authority_request(question: str) -> Verdict:
    lowered = (question or "").lower()
    for pattern in _IMPERSONATION_PATTERNS:
        if re.search(pattern, lowered):
            return _block("authority_impersonation",
                          "request asks the assistant to impersonate a person of authority "
                          "or to speak with authority it does not have")
    return _allow("authority_impersonation")


# ---------------------------------------------------------------------------
# G8 - privacy / personal-record requests
# ---------------------------------------------------------------------------

_PRIVACY_PATTERNS = [
    r"(look\s?up|show|find|give|tell|fetch|search\s+for)\b.{0,40}"
    r"\b(record|records|attendance|marks|grades|gpa|cgpa|salary|rank)\b.{0,60}"
    r"\b(of|for)\s+[a-z]+\s+[a-z]+",
    r"\b(attendance|salary|mark|grade|record)s?\b.{0,50}\b(roll\s*(no|number)|"
    r"employee\s*id|student\s*id)\b",
    r"\b(hr|employee|salary|confidential|personal)\b.{0,20}\b(student\s+)?"
    r"(records?|files?|data)\b",
    r"[a-z]+\s[a-z]+'s\s.{0,24}\b(room|attendance|mark|grade|salary|record|percentage|"
    r"hostel)\b",
]


def check_privacy_request(question: str) -> Verdict:
    lowered = (question or "").lower()
    for pattern in _PRIVACY_PATTERNS:
        if re.search(pattern, lowered):
            return _block("privacy",
                          "request asks for an individual's personal records; the "
                          "assistant serves policy documents only")
    return _allow("privacy")


# ---------------------------------------------------------------------------
# Composed input screen
# ---------------------------------------------------------------------------

INPUT_SCREENS = (
    validate_input,
    check_prompt_injection,
    check_content_policy,
    check_authority_request,
    check_privacy_request,
)

#: Fixed refusal the pipeline serves when an input guardrail blocks. It names
#: what is refused and what the assistant is for, and asserts nothing.
INPUT_REFUSAL = (
    "I can't help with that request. I am KnowledgeAI, a document assistant - I "
    "answer questions about the uploaded policy documents only, and I don't "
    "impersonate people, handle personal records, or produce content outside "
    "those documents."
)


def screen_input(question: str) -> List[Verdict]:
    """Run every input guardrail; stops at the first block."""
    verdicts: List[Verdict] = []
    for screen in INPUT_SCREENS:
        verdict = screen(question)
        verdicts.append(verdict)
        if not verdict.allowed:
            break
    return verdicts


# ---------------------------------------------------------------------------
# G3 - scope gate (retrieval-confidence)
# ---------------------------------------------------------------------------

#: Below this top similarity, nothing in the indexed corpus is even topically
#: related to the question. Chosen from measured data, not guessed: in the
#: Week-5 effectiveness runs, clearly off-corpus questions (bitcoin, car
#: repairs, cricket scores, recipes) measured 0.41-0.52 top similarity, while
#: the lowest legitimate question measured 0.5694 ("Who is the Dean of
#: Academic Affairs?" - the corpus does mention the Dean). 0.55 sits in the
#: gap: it blocks every measured off-corpus question and none of the measured
#: legitimate ones. Deliberately conservative: adjacent-but-absent topics
#: (similarity 0.55-0.80) stay with the model's own abstention and the output
#: screen, because refusing a real question is the costlier error.
SCOPE_MIN_TOP_SIMILARITY = 0.55

SCOPE_REFUSAL = (
    "I couldn't find anything about that in the uploaded documents, so rather "
    "than guess, I'll say I don't know. I can answer questions about the "
    "university policies these documents cover - attendance, examinations, "
    "hostel rules, library, scholarships, placements, grievances and the "
    "academic calendar."
)


def check_scope(top_similarity: Optional[float], source_count: int,
                threshold: float = SCOPE_MIN_TOP_SIMILARITY) -> Verdict:
    if source_count == 0 or top_similarity is None:
        return _block("scope_control", "retrieval returned no document context at all")
    if top_similarity < threshold:
        return _block("scope_control",
                      f"top chunk similarity {top_similarity:.4f} is below the "
                      f"{threshold:.2f} corpus-relevance floor")
    return _allow("scope_control",
                  f"top similarity {top_similarity:.4f} is within the corpus")


# ---------------------------------------------------------------------------
# G9 - rate / resource limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window limiter per chat session.

    The rapid-fire reproduction showed every request in a burst reaching the
    model unchecked - each one costing a full CPU generation. Sessions are
    what the frontend keeps stable across a conversation, so they are the
    natural bucket; the window and cap are constructor arguments so tests can
    shrink them. Thread-safe, because a flood arrives as concurrent requests.
    """

    def __init__(self, max_requests: int = 6, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict = {}
        self._lock = threading.Lock()

    def hit(self, session_id: str) -> Verdict:
        now = time.monotonic()
        with self._lock:
            stamps = [t for t in self._hits.get(session_id, [])
                      if now - t < self.window_seconds]
            if len(stamps) >= self.max_requests:
                self._hits[session_id] = stamps
                return _block("rate_limit",
                              f"more than {self.max_requests} requests in "
                              f"{self.window_seconds:.0f}s from this session")
            stamps.append(now)
            self._hits[session_id] = stamps
            return _allow("rate_limit")


# ---------------------------------------------------------------------------
# G4 - grounding enforcement (output side)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set:
    return set(_NUMBER_RE.findall(text or ""))


#: Sentences that concede the documents don't say something, quoted back at the
#: user, are fine. This catches the other thing the reproduction caught:
#: conclusions presented on the model's own reasoning ("it is reasonable to
#: assume books can be returned during these hours") with no source behind them.
_SPECULATION_PATTERNS = [
    r"reasonable to assume",
    r"\bwe can (assume|infer|conclude)\b",
    r"\bit (must|would) be\b.{0,30}\b(assume|safe to)\b",
    r"\bpresumably\b",
    r"\bin all likelihood\b",
]

_GROUNDING_REFUSAL = (
    "I can't answer that from the uploaded documents: the answer would require "
    "information or numbers the documents don't contain, and I won't fill gaps "
    "by guessing. What I can do is answer questions the documents do cover."
)


def enforce_grounding(answer: str, context: str, question: str) -> Verdict:
    """Check the finished answer against the context it claims to come from.

    Numbers are the strict check, because a confident wrong number is the
    failure that matters in a policy assistant (the Week-4 metric treats them
    the same way): any number in the answer that appears in neither the
    retrieved context nor the question blocks the response. Hedged speculation
    is annotated rather than blocked - the answer may still be mostly grounded.
    """
    allowed_numbers = _numbers_in(context) | _numbers_in(question)
    answer_numbers = _numbers_in(answer)

    # Percentages and quantities quoted from the question are fine; anything
    # else must exist in the context the answer cites.
    fabricated = sorted((n for n in answer_numbers if n not in allowed_numbers),
                        key=lambda x: float(x))
    if fabricated:
        return Verdict(
            guardrail="grounding", allowed=False,
            reason=f"answer states number(s) {', '.join(fabricated[:6])} that appear in "
                   "neither the retrieved context nor the question",
            action="block")

    lowered = (answer or "").lower()
    for pattern in _SPECULATION_PATTERNS:
        if re.search(pattern, lowered):
            return _annotate(
                "grounding",
                "Caution: part of this answer is the assistant's own inference, not "
                "something the uploaded documents state. Verify against the sources.")

    return _allow("grounding")


# ---------------------------------------------------------------------------
# G7 - output sanity / format control
# ---------------------------------------------------------------------------

#: Artifacts that must never reach the user as "the answer". The oversized-input
#: reproduction delivered "[LLM Stream error: ]" as the assistant's message and
#: stored it in chat history.
_ERROR_ARTIFACTS = [
    "[llm stream error",
    "traceback (most recent call last)",
    "internal server error",
    "exception:",
]

MAX_ANSWER_CHARS = 8000   # a normal 512-token answer is ~2000-3000 chars


def check_output_sanity(answer: str) -> Verdict:
    text = (answer or "").strip()
    if not text:
        return _block("output_sanity", "model returned an empty response")
    lowered = text.lower()
    for artifact in _ERROR_ARTIFACTS:
        if lowered.startswith(artifact) or lowered == artifact:
            return _block("output_sanity",
                          f"response is an internal error artifact ({artifact!r}), "
                          "not an answer")
    if len(text) > MAX_ANSWER_CHARS:
        return _block("output_sanity",
                      f"response is implausibly long for the answer channel "
                      f"({len(text)} chars)")
    return _allow("output_sanity")


#: Served to the user when the output side blocks.
OUTPUT_REFUSAL = (
    "Something went wrong while generating this answer, so I've withheld it "
    "rather than show you something unverified. Please try asking again."
)


def screen_output(answer: str, context: str, question: str) -> List[Verdict]:
    """Run the output-side guardrails; stops at the first block."""
    verdicts: List[Verdict] = []
    for check in (check_output_sanity,):
        verdict = check(answer)
        verdicts.append(verdict)
        if not verdict.allowed:
            return verdicts
    verdicts.append(enforce_grounding(answer, context, question))
    return verdicts


# ---------------------------------------------------------------------------
# The composed pipeline the gateway calls
# ---------------------------------------------------------------------------

@dataclass
class GuardrailPipeline:
    """The full set, wired the way the gateway runs it."""
    rate_limiter: RateLimiter = field(default_factory=RateLimiter)

    def screen_input(self, question: str, session_id: str) -> List[Verdict]:
        verdicts = screen_input(question)
        if all(v.allowed for v in verdicts):
            verdicts.append(self.rate_limiter.hit(session_id))
        return verdicts

    @staticmethod
    def check_scope(top_similarity: Optional[float], source_count: int) -> Verdict:
        return check_scope(top_similarity, source_count)

    @staticmethod
    def screen_output(answer: str, context: str, question: str) -> List[Verdict]:
        return screen_output(answer, context, question)


#: Fixed refusal served when the scope gate blocks.
def refusal_for(verdict: Verdict) -> str:
    if verdict.guardrail == "scope_control":
        return SCOPE_REFUSAL
    if verdict.guardrail == "grounding":
        return _GROUNDING_REFUSAL
    if verdict.guardrail == "rate_limit":
        return ("You're sending questions faster than I can answer them. "
                "Please wait a few seconds and try again.")
    if verdict.guardrail == "output_sanity":
        return OUTPUT_REFUSAL
    return INPUT_REFUSAL
