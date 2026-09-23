"""The Week-3 knowledge base as data, so seeding and evaluation cannot drift.

`seed_sample_docs.py` and the evaluation harness both read POLICY_CORPUS. If the
two held their own copies, a reworded policy line would silently invalidate every
ground-truth label in `dataset.py`.
"""

from typing import Any, Dict, List

POLICY_CORPUS: List[Dict[str, Any]] = [
    {
        "doc_id": "doc_attendance_policy",
        "filename": "attendance_policy.pdf",
        "pages": [
            {
                "page": 1,
                "text": "UNIVERSITY ATTENDANCE POLICY (2026-2027)\n\nStudents are required to maintain a minimum attendance of 75% in each registered course to be eligible to sit for semester examinations. Attendance will be calculated from the first day of the academic session."
            },
            {
                "page": 2,
                "text": "ATTENDANCE CONDONATION RULES\n\nStudents having attendance between 65% and 74.9% due to medical emergencies or university participation in sports/competitions may submit a condonation application supported by valid medical certificates or official sanction letters to the Dean of Academic Affairs within 7 days."
            },
            {
                "page": 3,
                "text": "LEAVE SANCTION PROCEDURE\n\nMedical leaves exceeding 3 consecutive days must be endorsed by the University Chief Medical Officer. Absence without prior approval for more than 14 consecutive days will result in automatic deregistration from the course."
            }
        ]
    },
    {
        "doc_id": "doc_exam_policy",
        "filename": "exam_policy.pdf",
        "pages": [
            {
                "page": 1,
                "text": "SEMESTER EXAMINATION GUIDELINES\n\nMid-semester examinations carry 30% weightage, end-semester examinations carry 50% weightage, and continuous internal assessment carries 20% weightage. Students must achieve a minimum of 40% aggregate marks to pass a course."
            },
            {
                "page": 2,
                "text": "MALPRACTICE & DISCIPLINARY ACTIONS\n\nCarrying mobile phones, smartwatches, or unauthorized printed materials inside the examination hall is strictly prohibited and constitutes a Category-A malpractice, resulting in cancellation of the paper."
            }
        ]
    },
    {
        "doc_id": "doc_hostel_rules",
        "filename": "hostel_rules.pdf",
        "pages": [
            {
                "page": 1,
                "text": "HOSTEL REGULATIONS & TIMINGS\n\nHostel entry gates close strictly at 10:00 PM for all residents. Night out passes must be requested via the student portal at least 24 hours in advance and approved by the Chief Warden."
            },
            {
                "page": 2,
                "text": "MESS AND DINING TIMINGS\n\nBreakfast is served from 7:30 AM to 9:00 AM, lunch from 12:30 PM to 2:00 PM, and dinner from 7:30 PM to 9:30 PM. Residents must carry their mess card to every meal. The weekly menu is decided by the Hostel Mess Committee and displayed on the hostel notice board."
            },
            {
                "page": 3,
                "text": "VISITOR AND ROOM RULES\n\nVisitors are permitted only between 4:00 PM and 7:00 PM and only in the visitors' lounge. Electrical appliances rated above 1000 watts are prohibited in rooms. Room allotment is for the full academic year, and any damage is recovered from the caution deposit."
            }
        ]
    },
    {
        "doc_id": "doc_welcome_guide",
        "filename": "welcome_guide.txt",
        "pages": [
            {
                "page": 1,
                "text": "WELCOME & GREETINGS GUIDE - KNOWLEDGEAI ASSISTANT\n\nGreeting Protocol:\nWhen a user says 'hi', 'hello', 'hey', or introduces themselves:\n1. Respond with a warm, friendly greeting: 'Hello! Welcome to KnowledgeAI RAG Document Assistant.'\n2. Offer assistance: 'I can help you analyze, search, and answer questions about all uploaded university policies, hostel regulations, and academic handbooks.'\n3. List key topics: Attendance requirements (75% rule), exam guidelines (40% pass mark), leave procedures, and hostel curfews (10:00 PM gate closing)."
            }
        ]
    },

    # ---- Documents added for Week 4 -----------------------------------
    # A 7-chunk corpus made retrieval quality unmeasurable: with top_k=4 out of
    # 7 chunks, the right page was swept in every single time and precision,
    # recall and MRR all pinned at 100 for all 27 questions. These six documents
    # take the index to 21 chunks, so selecting 4 is a real decision. Several
    # are deliberately adjacent to the out-of-scope probes - mess *timings* but
    # no menu, library *fines* but no borrowing limit, a scholarship covering a
    # percentage of tuition but no fee amount - so the probes now retrieve
    # convincing-looking context that still does not contain the answer. That is
    # exactly the case where a model either abstains or invents a number.
    {
        "doc_id": "doc_library_rules",
        "filename": "library_rules.pdf",
        "pages": [
            {
                "page": 1,
                "text": "CENTRAL LIBRARY TIMINGS AND CONDUCT\n\nThe Central Library is open from 8:00 AM to 10:00 PM on working days and from 9:00 AM to 5:00 PM on Saturdays, and remains closed on national holidays. Silence must be maintained in all reading halls, and mobile phones must be kept on silent mode."
            },
            {
                "page": 2,
                "text": "LIBRARY MEMBERSHIP AND FINES\n\nLibrary membership is automatic on enrolment and is verified using the student identity card at the circulation desk. An overdue fine of Rs. 5 per day is charged on late returns. Loss of a borrowed item is charged at twice the current replacement cost of the item."
            }
        ]
    },
    {
        "doc_id": "doc_scholarship_policy",
        "filename": "scholarship_policy.pdf",
        "pages": [
            {
                "page": 1,
                "text": "MERIT SCHOLARSHIP ELIGIBILITY\n\nStudents with a CGPA of 9.0 or above and no active backlogs are eligible for the Merit Scholarship, which covers 50% of the tuition component. Applications open in the first week of every academic year and close after fourteen days."
            },
            {
                "page": 2,
                "text": "MEANS-BASED ASSISTANCE\n\nStudents with an annual family income below Rs. 3,00,000 may apply for means-based assistance through the Student Welfare Office. Applicants must submit an income certificate issued within the last six months, along with the previous semester's grade card."
            }
        ]
    },
    {
        "doc_id": "doc_lab_safety",
        "filename": "lab_safety.pdf",
        "pages": [
            {
                "page": 1,
                "text": "LABORATORY SAFETY RULES\n\nClosed footwear and a buttoned lab coat are mandatory in all wet laboratories. Eating, drinking and leaving an experiment unattended are strictly prohibited. Every incident, however minor, must be reported to the laboratory supervisor immediately."
            },
            {
                "page": 2,
                "text": "EQUIPMENT AND BREAKAGE\n\nEquipment must be signed out in the laboratory register before use and signed back in after use. Breakages are recovered at replacement cost from the student concerned. Access to laboratories outside scheduled hours requires written permission from the Head of Department."
            }
        ]
    },
    {
        "doc_id": "doc_placement_policy",
        "filename": "placement_policy.pdf",
        "pages": [
            {
                "page": 1,
                "text": "PLACEMENT REGISTRATION AND ELIGIBILITY\n\nStudents must hold a CGPA of at least 6.0 with no active backlogs to register with the Training and Placement Cell. Registration closes two weeks before the placement season begins, and late registrations are not accepted."
            },
            {
                "page": 2,
                "text": "ONE STUDENT ONE OFFER RULE\n\nA student who accepts an offer is withdrawn from all further placement drives for that season. Withdrawal after accepting an offer requires written approval from the Training and Placement Officer and is granted only in exceptional circumstances."
            }
        ]
    },
    {
        "doc_id": "doc_grievance_redressal",
        "filename": "grievance_redressal.pdf",
        "pages": [
            {
                "page": 1,
                "text": "GRIEVANCE REDRESSAL PROCEDURE\n\nAcademic grievances must first be raised with the course faculty, then escalated to the Head of Department, and finally to the Grievance Redressal Committee. The Committee must respond within 15 working days of receiving a written complaint."
            },
            {
                "page": 2,
                "text": "ANTI-RAGGING AND CONDUCT\n\nRagging in any form attracts immediate suspension pending inquiry. Complaints may be filed anonymously through the anti-ragging portal or the 24-hour helpline maintained by the Student Welfare Office."
            }
        ]
    },
    {
        "doc_id": "doc_academic_calendar",
        "filename": "academic_calendar.pdf",
        "pages": [
            {
                "page": 1,
                "text": "ACADEMIC CALENDAR 2026-2027\n\nThe odd semester runs from July to November and the even semester from January to May. Mid-semester examinations are scheduled in the eighth week of each semester, and end-semester examinations begin one week after instruction ends."
            },
            {
                "page": 2,
                "text": "REGISTRATION AND ADD-DROP\n\nCourse registration closes at the end of the first week of each semester. A course may be dropped without penalty until the end of the third week; drops recorded after that appear as a withdrawal on the transcript."
            }
        ]
    }
]

# Collection the evaluation runs against. Deliberately not `default`: the live
# collection accumulated several re-uploads of the same PDFs, and duplicate
# chunks make retrieval precision meaningless. Same documents, one copy each.
EVAL_COLLECTION = "eval_kb"

#: Every (filename, page) pair the corpus contains - the universe retrieval
#: precision and recall are measured against.
def corpus_units() -> List[tuple]:
    return [(doc["filename"], page["page"])
            for doc in POLICY_CORPUS
            for page in doc["pages"]]
