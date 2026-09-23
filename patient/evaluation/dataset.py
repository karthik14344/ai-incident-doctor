"""Exercise 2 - the fixed evaluation set, with ground truth attached.

42 tasks. The same list is fed to every model, unchanged, so a comparison means
something.

The seven assessment categories
-------------------------------
Every task carries a `category` from exactly this set, and the comparison is
reported per category, not only as an overall score:

  Explanation               explain a rule, procedure or consequence in the
                            knowledge base (multi-part or ordered answers)
  Code Retrieval            read a quoted code excerpt and locate the function,
                            file or value asked for
  Dependency Understanding  reason about what imports/calls what, and what
                            breaks when a symbol changes
  Bug Analysis              find and explain the defect in a quoted snippet
  Code Generation           write code against the policies, judged by pytest
  Refactoring               restructure given code (helper extraction, band
                            table) with behaviour preserved, judged by pytest
  RAG-based Question        the assistant's core job: answer - or abstain -
                            from retrieved knowledge-base documents

Most knowledge-base questions are RAG-based on purpose: this is a document
assistant, so retrieval-grounded answering is the behaviour the set exists to
measure. The explanation/procedure/numeric shapes inside that set are recorded
separately (below) so the seven-category table stays honest without hiding the
internal mix.

The `task_type` field
---------------------
`category` answers "what is being assessed". `task_type` records the internal
shape of the task, which is what metric applicability keys on (greeting and
code tasks skip hallucination; code tasks score test-pass rate; the code
excerpts are self-contained, so retrieval quality does not apply). Keeping the
two apart means the visible categorisation can change without the metric
applicability logic drifting with it.

Ground-truth fields
-------------------
expected_facts   Each entry is a list of accepted surface forms for ONE fact.
                 The fact counts as recalled if any form appears in the answer.
                 Several spellings are listed because "75%", "75 percent" and
                 "seventy-five percent" are the same answer.
forbidden        Wrong values a confused model reaches for (usually the number
                 from the adjacent rule). Present => correctness is penalised.
topic_terms      What an on-topic answer must talk about. Used by relevance, so
                 relevance does not simply re-measure question word overlap.
gold_sources     (filename, page) pairs that genuinely contain the answer. The
                 universe for retrieval precision / recall / MRR. Empty on the
                 self-contained code questions: the evidence is quoted in the
                 question, so no chunk can be the right chunk and retrieval
                 quality is reported as not applicable rather than scored 0.
answerable       False for the three probes whose answer is NOT in the corpus.
                 The correct behaviour there is to abstain, not to answer.
code_task        Present on code-generation AND refactoring tasks; carries the
                 pytest source used for the test-pass-rate metric.
"""

from typing import Any, Dict, List

#: The seven assessment categories, in the order the comparison reports them.
CATEGORY_ORDER = [
    "Explanation",
    "Code Retrieval",
    "Dependency Understanding",
    "Bug Analysis",
    "Code Generation",
    "Refactoring",
    "RAG-based Question",
]
CATEGORY_SET = set(CATEGORY_ORDER)

#: Internal task shapes. These drive metric applicability, not the report.
TASK_TYPES = {
    "factual-lookup", "multi-fact", "procedure", "cross-document",
    "numeric-inference", "out-of-scope", "greeting", "code-generation",
    "code-snippet",
}

TEST_Q25 = """
from solution import is_exam_eligible

def test_exactly_at_threshold_is_eligible():
    assert is_exam_eligible(75)

def test_above_threshold_is_eligible():
    assert is_exam_eligible(92.5)

def test_below_threshold_is_not_eligible():
    assert not is_exam_eligible(74.9)

def test_far_below_threshold_is_not_eligible():
    assert not is_exam_eligible(10)

def test_full_attendance_is_eligible():
    assert is_exam_eligible(100)
"""

TEST_Q26 = """
from solution import final_score, has_passed

def test_all_hundred_gives_hundred():
    assert abs(final_score(100, 100, 100) - 100) < 0.01

def test_mid_sem_weight_is_thirty_percent():
    assert abs(final_score(100, 0, 0) - 30) < 0.01

def test_end_sem_weight_is_fifty_percent():
    assert abs(final_score(0, 100, 0) - 50) < 0.01

def test_internal_weight_is_twenty_percent():
    assert abs(final_score(0, 0, 100) - 20) < 0.01

def test_mixed_marks():
    assert abs(final_score(60, 40, 80) - (18 + 20 + 16)) < 0.01

def test_pass_mark_boundary():
    assert has_passed(40)
    assert not has_passed(39.9)

def test_clear_pass_and_clear_fail():
    assert has_passed(88)
    assert not has_passed(0)
"""

TEST_Q27 = """
from solution import classify_attendance

def test_above_minimum_is_eligible():
    assert classify_attendance(90) == "eligible"

def test_exactly_at_minimum_is_eligible():
    assert classify_attendance(75) == "eligible"

def test_inside_condonation_band():
    assert classify_attendance(70) == "condonation"

def test_lower_edge_of_condonation_band():
    assert classify_attendance(65) == "condonation"

def test_below_band_is_not_eligible():
    assert classify_attendance(50) == "not_eligible"
"""

# Refactoring tasks are scored by the same machinery as code generation: the
# answer's code is extracted and run against a fixed suite, and "the refactor
# is correct" means "behaviour is unchanged". Q42 reuses TEST_Q27 verbatim -
# the whole point of that refactor is that the same behaviour passes the same
# suite from a data-driven implementation.

TEST_Q40 = """
from solution import weighted_component, final_score

def test_full_marks_gives_hundred():
    assert abs(final_score(100, 100, 100) - 100) < 0.01

def test_weights_match_the_exam_policy():
    assert abs(final_score(100, 0, 0) - 30) < 0.01
    assert abs(final_score(0, 100, 0) - 50) < 0.01
    assert abs(final_score(0, 0, 100) - 20) < 0.01

def test_helper_returns_one_weighted_share():
    assert abs(weighted_component(60, 30) - 18) < 0.01
    assert abs(weighted_component(80, 50) - 40) < 0.01
    assert abs(weighted_component(0, 50) - 0) < 0.01

def test_mixed_marks():
    assert abs(final_score(60, 40, 80) - 54) < 0.01
"""

TEST_Q41 = """
from solution import at_least, is_exam_eligible

def test_helper_is_inclusive_at_the_minimum():
    assert at_least(75, 75) is True
    assert at_least(74.9, 75) is False

def test_eligible_at_and_above_the_minimum():
    assert is_exam_eligible(75)
    assert is_exam_eligible(92.5)

def test_below_the_minimum_is_not_eligible():
    assert not is_exam_eligible(74.9)
    assert not is_exam_eligible(10)

def test_refactor_delegates_to_the_helper():
    import inspect
    import solution
    assert "at_least" in inspect.getsource(solution.is_exam_eligible)
"""


EVAL_DATASET: List[Dict[str, Any]] = [

    # ---------- RAG-based Question --------------------------------------
    # Direct lookup, cross-document reasoning, numeric inference, the
    # abstention probes and the greeting: every task whose answer lives in -
    # or is deliberately absent from - the retrieved knowledge base.
    {
        "id": "Q01",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "What is the minimum attendance percentage required to be eligible to sit for semester examinations?",
        "answerable": True,
        "expected_facts": [["75%", "75 percent", "seventy-five percent", "75 per cent"]],
        "forbidden": [["65%"], ["40%"]],
        "topic_terms": ["attendance", "minimum", "examination", "eligible"],
        "gold_sources": [("attendance_policy.pdf", 1)],
    },
    # A deliberate stress test of retrieval, not of any model: the answer is
    # spread over six pages in five different documents, and top_k is 4. Recall
    # is capped at 66.7% by construction, so this is the question where the
    # pipeline provably cannot hand any model everything it needs. It exists to
    # make Exercise 5's "important information was missed" case measurable
    # rather than anecdotal.
    {
        "id": "Q02",
        "category": "RAG-based Question",
        "task_type": "cross-document",
        "question": "List every approval authority named across the university policies and state what each one approves.",
        "answerable": True,
        "expected_facts": [
            ["dean of academic affairs", "dean"],
            ["chief medical officer"],
            ["chief warden"],
            ["head of department"],
            ["training and placement officer"],
        ],
        "forbidden": [],
        "topic_terms": ["approval", "authority", "approves", "policy"],
        "gold_sources": [
            ("attendance_policy.pdf", 2),
            ("attendance_policy.pdf", 3),
            ("hostel_rules.pdf", 1),
            ("lab_safety.pdf", 2),
            ("placement_policy.pdf", 2),
            ("grievance_redressal.pdf", 1),
        ],
    },
    {
        "id": "Q03",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "What weightage does the end-semester examination carry?",
        "answerable": True,
        "expected_facts": [["50%", "50 percent", "fifty percent"]],
        "forbidden": [["30%"], ["20%"]],
        "topic_terms": ["end-semester", "weightage", "examination"],
        "gold_sources": [("exam_policy.pdf", 1)],
    },
    {
        "id": "Q04",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "What is the minimum aggregate mark a student needs to pass a course?",
        "answerable": True,
        "expected_facts": [["40%", "40 percent", "forty percent"]],
        "forbidden": [["75%"], ["50%"]],
        "topic_terms": ["aggregate", "pass", "minimum", "marks"],
        "gold_sources": [("exam_policy.pdf", 1)],
    },
    {
        "id": "Q05",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "At what time do the hostel entry gates close?",
        "answerable": True,
        "expected_facts": [["10:00 pm", "10 pm", "10:00 p.m.", "22:00", "ten pm"]],
        "forbidden": [["11:00 pm"], ["9:00 pm"]],
        "topic_terms": ["hostel", "gate", "close", "time"],
        "gold_sources": [("hostel_rules.pdf", 1)],
    },
    {
        "id": "Q06",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "How far in advance must a night out pass be requested?",
        "answerable": True,
        "expected_facts": [["24 hours", "twenty-four hours", "24 hrs", "one day in advance"]],
        "forbidden": [["48 hours"], ["7 days"]],
        "topic_terms": ["night out", "pass", "advance", "request"],
        "gold_sources": [("hostel_rules.pdf", 1)],
    },
    {
        "id": "Q07",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "Who approves a night out pass for a hostel resident?",
        "answerable": True,
        "expected_facts": [["chief warden", "warden"]],
        "forbidden": [["dean of academic affairs"], ["chief medical officer"]],
        "topic_terms": ["night out", "pass", "approve", "warden"],
        "gold_sources": [("hostel_rules.pdf", 1)],
    },
    {
        "id": "Q08",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "Who must endorse a medical leave that runs longer than three consecutive days?",
        "answerable": True,
        "expected_facts": [["chief medical officer", "university chief medical officer", "cmo"]],
        "forbidden": [["chief warden"], ["dean of academic affairs"]],
        "topic_terms": ["medical leave", "endorse", "consecutive days"],
        "gold_sources": [("attendance_policy.pdf", 3)],
    },
    {
        "id": "Q09",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "Within how many days must an attendance condonation application be submitted?",
        "answerable": True,
        "expected_facts": [["7 days", "seven days", "within 7"]],
        "forbidden": [["14 days"], ["3 days"], ["24 hours"]],
        "topic_terms": ["condonation", "application", "days", "submit"],
        "gold_sources": [("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q10",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "To whom is an attendance condonation application submitted?",
        "answerable": True,
        "expected_facts": [["dean of academic affairs", "dean"]],
        "forbidden": [["chief warden"], ["chief medical officer"]],
        "topic_terms": ["condonation", "application", "submitted", "dean"],
        "gold_sources": [("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q17",
        "category": "RAG-based Question",
        "task_type": "cross-document",
        "question": "A student has 68% attendance and an aggregate of 45%. Are they eligible to sit the examination, and would that aggregate be a pass?",
        "answerable": True,
        "expected_facts": [
            ["75%", "75 percent"],
            ["condonation"],
            ["40%", "40 percent"],
            ["pass", "passes", "passing"],
        ],
        "forbidden": [],
        "topic_terms": ["attendance", "eligible", "aggregate", "pass"],
        "gold_sources": [("attendance_policy.pdf", 1), ("attendance_policy.pdf", 2), ("exam_policy.pdf", 1)],
    },
    {
        "id": "Q18",
        "category": "RAG-based Question",
        "task_type": "cross-document",
        "question": "Compare the approval authority for a night out pass with the approval authority for an attendance condonation application.",
        "answerable": True,
        "expected_facts": [
            ["chief warden", "warden"],
            ["dean of academic affairs", "dean"],
        ],
        "forbidden": [],
        "topic_terms": ["approval", "authority", "night out", "condonation"],
        "gold_sources": [("hostel_rules.pdf", 1), ("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q19",
        "category": "RAG-based Question",
        "task_type": "numeric-inference",
        "question": "Is 74% attendance enough to sit the semester examination without submitting any application?",
        "answerable": True,
        "expected_facts": [
            ["no", "not enough", "not eligible", "cannot", "is not sufficient"],
            ["75%", "75 percent"],
            ["condonation"],
        ],
        "forbidden": [],
        "topic_terms": ["attendance", "eligible", "examination", "condonation"],
        "gold_sources": [("attendance_policy.pdf", 1), ("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q20",
        "category": "RAG-based Question",
        "task_type": "numeric-inference",
        "question": "A student scored an aggregate of 38%. Have they passed the course?",
        "answerable": True,
        "expected_facts": [
            ["no", "not passed", "fail", "failed", "does not pass"],
            ["40%", "40 percent"],
        ],
        "forbidden": [],
        "topic_terms": ["aggregate", "pass", "course", "marks"],
        "gold_sources": [("exam_policy.pdf", 1)],
    },
    # Out-of-scope probes (hallucination controls): the corpus cannot answer
    # these, so abstaining is the only correct behaviour.
    {
        "id": "Q21",
        "category": "RAG-based Question",
        "task_type": "out-of-scope",
        "question": "What is the annual tuition fee for the B.Tech programme?",
        "answerable": False,
        "expected_facts": [],
        "forbidden": [],
        "topic_terms": ["tuition", "fee"],
        "gold_sources": [],
    },
    {
        "id": "Q22",
        "category": "RAG-based Question",
        "task_type": "out-of-scope",
        "question": "What is the hostel mess menu for Wednesday dinner?",
        "answerable": False,
        "expected_facts": [],
        "forbidden": [],
        "topic_terms": ["mess", "menu"],
        "gold_sources": [],
    },
    {
        "id": "Q23",
        "category": "RAG-based Question",
        "task_type": "out-of-scope",
        "question": "How many books can a student borrow from the central library at one time?",
        "answerable": False,
        "expected_facts": [],
        "forbidden": [],
        "topic_terms": ["library", "books", "borrow"],
        "gold_sources": [],
    },
    {
        "id": "Q24",
        "category": "RAG-based Question",
        "task_type": "greeting",
        "question": "Hello",
        "answerable": True,
        "expected_facts": [
            ["hello", "hi ", "welcome", "greetings"],
            ["question", "questions", "help", "assist"],
        ],
        "forbidden": [],
        "topic_terms": ["welcome", "assist", "documents"],
        "gold_sources": [("welcome_guide.txt", 1)],
    },
    # Deeper-corpus lookups. These sit in the documents added in Week 4, far
    # enough from the attendance/exam cluster that retrieval has to actually
    # choose rather than sweep the whole index.
    {
        "id": "Q28",
        "category": "RAG-based Question",
        "task_type": "factual-lookup",
        "question": "Within how many working days must the Grievance Redressal Committee respond to a written complaint?",
        "answerable": True,
        "expected_facts": [["15 working days", "15 days", "fifteen working days", "fifteen days"]],
        "forbidden": [["7 days"], ["14 days"]],
        "topic_terms": ["grievance", "committee", "respond", "working days"],
        "gold_sources": [("grievance_redressal.pdf", 1)],
    },
    {
        "id": "Q29",
        "category": "RAG-based Question",
        "task_type": "cross-document",
        "question": "What CGPA is required to register with the Training and Placement Cell, and what happens once a student accepts an offer?",
        "answerable": True,
        "expected_facts": [
            ["6.0", "6.0 cgpa", "cgpa of 6"],
            ["withdrawn", "withdraw", "removed from further", "no further placement"],
        ],
        "forbidden": [["9.0"]],
        "topic_terms": ["cgpa", "placement", "register", "offer"],
        "gold_sources": [("placement_policy.pdf", 1), ("placement_policy.pdf", 2)],
    },

    # ---------- Explanation ---------------------------------------------
    # The answer is a multi-part explanation of a rule, a procedure or a
    # consequence - completeness and order matter, not just one fact.
    {
        "id": "Q11",
        "category": "Explanation",
        "task_type": "multi-fact",
        "question": "List the weightage of all three assessment components in the semester examination scheme.",
        "answerable": True,
        "expected_facts": [
            ["30%", "30 percent", "thirty percent"],
            ["50%", "50 percent", "fifty percent"],
            ["20%", "20 percent", "twenty percent"],
            ["mid-semester", "mid semester", "midsem"],
            ["end-semester", "end semester", "endsem"],
            ["continuous internal assessment", "internal assessment", "cia"],
        ],
        "forbidden": [["75%"]],
        "topic_terms": ["weightage", "assessment", "semester", "examination"],
        "gold_sources": [("exam_policy.pdf", 1)],
    },
    {
        "id": "Q12",
        "category": "Explanation",
        "task_type": "multi-fact",
        "question": "What attendance range qualifies for condonation, and what supporting evidence is required?",
        "answerable": True,
        "expected_facts": [
            ["65%", "65 percent"],
            ["74.9%", "74.9 percent", "74.9"],
            ["medical certificate", "medical certificates"],
            ["sanction letter", "sanction letters", "official sanction"],
        ],
        "forbidden": [],
        "topic_terms": ["condonation", "attendance", "range", "evidence", "certificate"],
        "gold_sources": [("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q13",
        "category": "Explanation",
        "task_type": "multi-fact",
        "question": "Which items are prohibited inside the examination hall, and what is the penalty for carrying them?",
        "answerable": True,
        "expected_facts": [
            ["mobile phone", "mobile phones"],
            ["smartwatch", "smartwatches"],
            ["printed material", "printed materials"],
            ["category-a", "category a"],
            ["cancellation of the paper", "cancellation of paper", "paper is cancelled", "paper cancelled"],
        ],
        "forbidden": [["deregistration"]],
        "topic_terms": ["examination hall", "prohibited", "malpractice", "penalty"],
        "gold_sources": [("exam_policy.pdf", 2)],
    },
    {
        "id": "Q14",
        "category": "Explanation",
        "task_type": "procedure",
        "question": "What happens if a student is absent without prior approval for more than 14 consecutive days?",
        "answerable": True,
        "expected_facts": [
            ["deregistration", "deregistered", "de-registration", "removed from the course"],
            ["14 consecutive days", "14 days", "fourteen days"],
        ],
        "forbidden": [["condonation"], ["cancellation of the paper"]],
        "topic_terms": ["absent", "approval", "consecutive days", "course"],
        "gold_sources": [("attendance_policy.pdf", 3)],
    },
    {
        "id": "Q15",
        "category": "Explanation",
        "task_type": "procedure",
        "question": "Describe the complete procedure a hostel resident must follow to obtain a night out pass.",
        "answerable": True,
        "expected_facts": [
            ["student portal", "portal"],
            ["24 hours", "twenty-four hours"],
            ["chief warden", "warden"],
        ],
        "forbidden": [["dean of academic affairs"]],
        "topic_terms": ["night out", "pass", "procedure", "portal", "approval"],
        "gold_sources": [("hostel_rules.pdf", 1)],
    },
    {
        "id": "Q16",
        "category": "Explanation",
        "task_type": "procedure",
        "question": "A student's attendance dropped to 70% because of a hospital admission. What steps should the student take?",
        "answerable": True,
        "expected_facts": [
            ["condonation"],
            ["medical certificate", "medical certificates"],
            ["dean of academic affairs", "dean"],
            ["7 days", "seven days"],
        ],
        "forbidden": [["chief warden"]],
        "topic_terms": ["condonation", "medical", "application", "attendance"],
        "gold_sources": [("attendance_policy.pdf", 2)],
    },
    {
        "id": "Q30",
        "category": "Explanation",
        "task_type": "procedure",
        "question": "Until which week of the semester can a course be dropped without penalty, and how are later drops recorded?",
        "answerable": True,
        "expected_facts": [
            ["third week", "week 3", "3rd week"],
            ["withdrawal", "withdrawn"],
            ["transcript"],
        ],
        "forbidden": [["first week"]],
        "topic_terms": ["course", "drop", "week", "transcript"],
        "gold_sources": [("academic_calendar.pdf", 2)],
    },

    # ---------- Code Generation (test-pass rate) -------------------------
    {
        "id": "Q25",
        "category": "Code Generation",
        "task_type": "code-generation",
        "question": (
            "Write a Python function named is_exam_eligible(attendance_percent) that returns True only "
            "when a student meets the minimum attendance the attendance policy requires to sit semester "
            "examinations, and False otherwise. Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def is_exam_eligible"], ["75"]],
        "forbidden": [],
        "topic_terms": ["function", "attendance", "eligible"],
        "gold_sources": [("attendance_policy.pdf", 1)],
        "code_task": {"entry_points": ["is_exam_eligible"], "tests": TEST_Q25},
    },
    {
        "id": "Q26",
        "category": "Code Generation",
        "task_type": "code-generation",
        "question": (
            "Write two Python functions: final_score(mid_sem, end_sem, internal) which returns the weighted "
            "aggregate using the exam policy weightages, and has_passed(aggregate) which returns whether that "
            "aggregate clears the pass mark. All three inputs are percentages out of 100. "
            "Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def final_score"], ["def has_passed"], ["0.3", "30"], ["0.5", "50"], ["0.2", "20"]],
        "forbidden": [],
        "topic_terms": ["function", "weightage", "aggregate", "pass"],
        "gold_sources": [("exam_policy.pdf", 1)],
        "code_task": {"entry_points": ["final_score", "has_passed"], "tests": TEST_Q26},
    },
    {
        "id": "Q27",
        "category": "Code Generation",
        "task_type": "code-generation",
        "question": (
            "Write a Python function classify_attendance(attendance_percent) that returns the string "
            "'eligible' when the student meets the attendance policy minimum, 'condonation' when the student "
            "falls in the condonation band, and 'not_eligible' below that band. "
            "Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def classify_attendance"], ["75"], ["65"], ["condonation"]],
        "forbidden": [],
        "topic_terms": ["function", "attendance", "condonation", "eligible"],
        "gold_sources": [("attendance_policy.pdf", 1), ("attendance_policy.pdf", 2)],
        "code_task": {"entry_points": ["classify_attendance"], "tests": TEST_Q27},
    },

    # ---------- Code Retrieval -------------------------------------------
    # Self-contained: the excerpt is quoted in the question, so a model is
    # scored on reading the code it was given, not on retrieving it. That is
    # why these carry no gold_sources - retrieval quality is not applicable
    # here, and is reported as n/a rather than forced to a number.
    {
        "id": "Q31",
        "category": "Code Retrieval",
        "task_type": "code-snippet",
        "question": (
            "The excerpt below is from this project's repository indexer.\n\n"
            "EXCLUDE_DIRS = {\".git\", \".venv\", \"venv\", \"node_modules\", \"__pycache__\", "
            "\".pytest_cache\", \"chroma_data\", \"dist\", \"build\", \".vite\", \"storage\", \"data\"}\n\n"
            "def iter_source_files(root):\n"
            "    found = []\n"
            "    for dirpath, dirnames, filenames in os.walk(root):\n"
            "        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]\n"
            "        for name in sorted(filenames):\n"
            "            if name in EXCLUDE_FILES or not name.endswith(INCLUDE_SUFFIXES):\n"
            "                continue\n"
            "            found.append(os.path.join(dirpath, name))\n"
            "    return sorted(found)\n\n"
            "Which function in this excerpt decides which files the code index walks into, and name any "
            "one directory it is written never to descend into? Answer with the function name and the directory."
        ),
        "answerable": True,
        "expected_facts": [
            ["iter_source_files"],
            ["node_modules", ".git", "__pycache__", "chroma_data", "venv", ".venv", "storage", "data", "dist", "build"],
        ],
        "forbidden": [["chunk_source"]],
        "topic_terms": ["iter_source_files", "exclude", "directory", "index"],
        "gold_sources": [],
    },
    {
        "id": "Q32",
        "category": "Code Retrieval",
        "task_type": "code-snippet",
        "question": (
            "This is the code-block extractor from this project's evaluation harness.\n\n"
            "def extract_code(answer):\n"
            "    blocks = _FENCED_PY.findall(answer) or _FENCED_ANY.findall(answer)\n"
            "    if blocks:\n"
            "        joined = \"\\n\\n\".join(b.strip() for b in blocks if \"def \" in b or \"=\" in b)\n"
            "        if \"def \" in joined:\n"
            "            return joined\n"
            "        return blocks[0].strip()\n"
            "    if \"def \" in answer:\n"
            "        lines = answer.splitlines()\n"
            "        for index, line in enumerate(lines):\n"
            "            if line.lstrip().startswith((\"def \", \"import \", \"from \")):\n"
            "                return \"\\n\".join(lines[index:]).strip()\n"
            "    return None\n\n"
            "Which function pulls the Python out of a model's answer, and what does it look for when the "
            "answer arrives without a fenced code block?"
        ),
        "answerable": True,
        "expected_facts": [
            ["extract_code"],
            ["def", "function definition", "bare code", "import", "first code line"],
        ],
        "forbidden": [["pytest"]],
        "topic_terms": ["extract_code", "fence", "code block", "def"],
        "gold_sources": [],
    },
    {
        "id": "Q33",
        "category": "Code Retrieval",
        "task_type": "code-snippet",
        "question": (
            "This function decides whether a model's answer named the files a repository-level question "
            "needed.\n\n"
            "def score_answer(answer, expected_files):\n"
            "    lowered = (answer or \"\").lower()\n"
            "    named = [f for f in expected_files\n"
            "             if f.lower() in lowered or os.path.basename(f).lower() in lowered]\n"
            "    return {\n"
            "        \"files_named\": len(named),\n"
            "        \"expected_files\": len(expected_files),\n"
            "        \"coverage_pct\": round(100.0 * len(named) / len(expected_files), 1),\n"
            "        \"named\": named,\n"
            "        \"not_named\": [f for f in expected_files if f not in named],\n"
            "    }\n\n"
            "Which function is it, and how does it match a file when the answer gives only the file's name "
            "without the directory?"
        ),
        "answerable": True,
        "expected_facts": [
            ["score_answer"],
            ["basename", "base name", "file name", "filename", "name only", "without the directory"],
        ],
        "forbidden": [["score_retrieval"]],
        "topic_terms": ["score_answer", "basename", "expected_files", "match"],
        "gold_sources": [],
    },

    # ---------- Dependency Understanding ---------------------------------
    # Real import edges from this repository, quoted so the dependency facts
    # are checkable rather than recalled from memory. Renaming a symbol or
    # deleting a module propagates along exactly these edges.
    {
        "id": "Q34",
        "category": "Dependency Understanding",
        "task_type": "code-snippet",
        "question": (
            "Below are all the places in this project that import the embedding helper:\n\n"
            "from ingestion_service.app.embedder import get_embedding   # ingestion_service/app/main.py\n"
            "from ingestion_service.app.embedder import get_embedding   # retrieval_service/app/main.py\n"
            "from ingestion_service.app.embedder import get_embedding   # evaluation/pipeline.py\n"
            "from ingestion_service.app.embedder import get_embedding   # evaluation/prepare_kb.py\n"
            "from ingestion_service.app.embedder import get_embedding   # evaluation/repo_index.py\n"
            "from ingestion_service.app.embedder import get_embedding   # seed_sample_docs.py\n\n"
            "If the signature of get_embedding() changes, which files break? Name every file that imports it."
        ),
        "answerable": True,
        "expected_facts": [
            ["ingestion_service/app/main.py", "ingestion_service main", "ingestion_service"],
            ["retrieval_service/app/main.py", "retrieval_service main", "retrieval_service"],
            ["evaluation/pipeline.py", "pipeline.py"],
            ["evaluation/prepare_kb.py", "prepare_kb.py"],
            ["evaluation/repo_index.py", "repo_index.py"],
            ["seed_sample_docs.py", "seed_sample_docs"],
        ],
        "forbidden": [["api_gateway"], ["llm_service"], ["frontend"]],
        "topic_terms": ["get_embedding", "import", "embedder", "signature"],
        "gold_sources": [],
    },
    {
        "id": "Q35",
        "category": "Dependency Understanding",
        "task_type": "code-snippet",
        "question": (
            "These are the evaluation runner's imports from its own package:\n\n"
            "from evaluation import metrics as M\n"
            "from evaluation.analysis import analyse\n"
            "from evaluation.code_eval import run_code_task\n"
            "from evaluation.corpus import EVAL_COLLECTION\n"
            "from evaluation.dataset import EVAL_DATASET, dataset_by_id\n"
            "from evaluation.pipeline import OLLAMA_DEFAULT_URL, generate, retrieve, unload, warm_up\n"
            "from evaluation.rag_analysis import build_traces\n\n"
            "If evaluation/analysis.py were deleted, which function call in the runner breaks, and what "
            "is that function used for?"
        ),
        "answerable": True,
        "expected_facts": [
            ["analyse"],
            ["analysis", "exercise 4", "trade-off", "tradeoff", "interpret", "comparison of results"],
        ],
        "forbidden": [["build_traces"]],
        "topic_terms": ["analyse", "analysis", "runner", "import"],
        "gold_sources": [],
    },
    {
        "id": "Q36",
        "category": "Dependency Understanding",
        "task_type": "code-snippet",
        "question": (
            "The Model Comparison page's scoring module imports exactly these three things from the "
            "evaluation package:\n\n"
            "from evaluation import metrics as M\n"
            "from evaluation.code_eval import run_code_task\n"
            "from evaluation.dataset import dataset_by_id\n\n"
            "Name what each of the three imports gives the comparison page."
        ),
        "answerable": True,
        "expected_facts": [
            ["metrics"],
            ["run_code_task", "code_eval", "pytest", "test-pass", "test pass"],
            ["dataset_by_id", "dataset", "ground truth", "ground-truth"],
        ],
        "forbidden": [],
        "topic_terms": ["metrics", "run_code_task", "dataset_by_id", "import"],
        "gold_sources": [],
    },

    # ---------- Bug Analysis ----------------------------------------------
    # Each snippet carries a real defect: two are boundary bugs against the
    # attendance policy's own numbers, one is the memory-sampling bug this
    # project actually hit (matching only "ollama" reported the ~40 MB API
    # stub and missed the llama-server runner holding the weights).
    {
        "id": "Q37",
        "category": "Bug Analysis",
        "task_type": "code-snippet",
        "question": (
            "A teammate wrote this function to encode the university attendance rule for sitting "
            "semester examinations:\n\n"
            "def is_exam_eligible(attendance_percent):\n"
            "    return attendance_percent > 75\n\n"
            "The attendance policy states the minimum attendance required to sit the examinations. "
            "Find the bug: which students does this function misclassify, and what should the comparison be?"
        ),
        "answerable": True,
        "expected_facts": [
            ["exactly 75", "75% exactly", "exactly at 75", "exactly at the threshold",
             "exactly-at-threshold", "boundary", "on the threshold", "borderline"],
            [">=", "greater than or equal", "at least", ">= 75", "inclusive"],
        ],
        "forbidden": [["< 75"], ["65%"], ["90%"]],
        "topic_terms": ["is_exam_eligible", "75", "threshold", "bug"],
        "gold_sources": [],
    },
    {
        "id": "Q38",
        "category": "Bug Analysis",
        "task_type": "code-snippet",
        "question": (
            "An earlier version of the evaluation's memory sampler read:\n\n"
            "def _ollama_processes():\n"
            "    found = []\n"
            "    for proc in psutil.process_iter([\"name\"]):\n"
            "        if \"ollama\" in proc.info[\"name\"].lower():\n"
            "            found.append(proc)\n"
            "    return found\n\n"
            "With this version the evaluation reported the model's memory footprint as about 40 MB, "
            "roughly fifty times too small. Identify the bug: which process does the filter miss, and "
            "why does that matter?"
        ),
        "answerable": True,
        "expected_facts": [
            ["llama-server", "llama_server", "ollama_llama_server", "llama server", "runner"],
            ["weights", "the model", "model weights", "loaded model", "the actual model"],
        ],
        "forbidden": [["nvidia"], ["gpu driver"]],
        "topic_terms": ["ollama", "process", "memory", "llama-server"],
        "gold_sources": [],
    },
    {
        "id": "Q39",
        "category": "Bug Analysis",
        "task_type": "code-snippet",
        "question": (
            "The attendance policy's condonation band runs from 65% up to 74.9%. A teammate wrote:\n\n"
            "def needs_condonation(attendance_percent):\n"
            "    return 65 <= attendance_percent < 74\n\n"
            "Find the bug: which students inside the condonation band does this function wrongly exclude?"
        ),
        "answerable": True,
        "expected_facts": [
            ["74", "74.9", "between 74 and 74.9", "74.0 to 74.9"],
            ["74.9", "upper bound", "boundary", "off by", "wrong upper", "<= 74.9", "< 74.9"],
        ],
        "forbidden": [["65"], ["< 65"]],
        "topic_terms": ["condonation", "band", "74.9", "bug"],
        "gold_sources": [],
    },

    # ---------- Refactoring (test-pass rate) -------------------------------
    # "The refactor is correct" means "behaviour is unchanged", so these are
    # scored exactly like code generation: extract the code, run the suite.
    {
        "id": "Q40",
        "category": "Refactoring",
        "task_type": "code-generation",
        "question": (
            "The exam policy weights mid-semester examinations at 30%, end-semester examinations at 50% "
            "and continuous internal assessment at 20%. A teammate's final_score repeats the same "
            "arithmetic three times inline. Refactor it: write weighted_component(score, weight_percent) "
            "that returns one weighted share, then write final_score(mid_sem, end_sem, internal) so it "
            "computes each component through weighted_component and returns the aggregate percentage. "
            "Behaviour must stay identical. Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def weighted_component"], ["def final_score"], ["30"], ["50"], ["20"]],
        "forbidden": [],
        "topic_terms": ["weighted", "refactor", "component", "final_score"],
        "gold_sources": [("exam_policy.pdf", 1)],
        "code_task": {"entry_points": ["weighted_component", "final_score"], "tests": TEST_Q40},
    },
    {
        "id": "Q41",
        "category": "Refactoring",
        "task_type": "code-generation",
        "question": (
            "Two functions in a codebase each carry their own copy of the same attendance comparison, "
            "one written as `attendance_percent >= 75` and another as `not attendance_percent < 75`. "
            "Refactor: write a single helper at_least(value, minimum) that returns True when value meets "
            "the minimum, then reimplement is_exam_eligible(attendance_percent) on top of it so a student "
            "is eligible exactly when their attendance meets the policy minimum of 75%. The helper must "
            "be inclusive at the minimum, and is_exam_eligible must call the helper rather than repeat "
            "the comparison. Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def at_least"], ["def is_exam_eligible"], ["75"]],
        "forbidden": [],
        "topic_terms": ["refactor", "helper", "at_least", "threshold"],
        "gold_sources": [("attendance_policy.pdf", 1)],
        "code_task": {"entry_points": ["at_least", "is_exam_eligible"], "tests": TEST_Q41},
    },
    {
        "id": "Q42",
        "category": "Refactoring",
        "task_type": "code-generation",
        "question": (
            "A teammate's classify_attendance is a chain of three if/elif blocks that each restate the "
            "attendance thresholds inline: eligible at 75% or above, condonation between 65% and 74.9%, "
            "and not_eligible below that. Refactor it: define a BANDS list of (lower_bound, label) pairs "
            "and derive the returned string 'eligible', 'condonation' or 'not_eligible' from a single "
            "loop over BANDS. classify_attendance(attendance_percent) must return exactly the same "
            "strings for the same inputs as before. Reply with a single python code block and no prose."
        ),
        "answerable": True,
        "expected_facts": [["def classify_attendance"], ["bands"], ["75"], ["65"], ["condonation"]],
        "forbidden": [],
        "topic_terms": ["refactor", "band", "classify_attendance", "threshold"],
        "gold_sources": [("attendance_policy.pdf", 1), ("attendance_policy.pdf", 2)],
        "code_task": {"entry_points": ["classify_attendance"], "tests": TEST_Q27},
    },
]


def dataset_by_id() -> Dict[str, Dict[str, Any]]:
    return {item["id"]: item for item in EVAL_DATASET}


def category_counts() -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in EVAL_DATASET:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


def public_dataset() -> List[Dict[str, Any]]:
    """Dataset shaped for the UI - ground truth summarised, not dumped."""
    return [{
        "id": i["id"],
        "category": i["category"],
        "task_type": i["task_type"],
        "question": i["question"],
        "answerable": i["answerable"],
        "expected_fact_count": len(i["expected_facts"]),
        "gold_sources": [f"{f} p{p}" for f, p in i["gold_sources"]],
        "has_code_task": "code_task" in i,
        "test_count": i["code_task"]["tests"].count("def test_") if "code_task" in i else 0,
    } for i in EVAL_DATASET]
