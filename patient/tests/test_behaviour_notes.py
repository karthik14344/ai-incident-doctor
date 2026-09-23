"""Small behaviour notes, written down as tests while reading the code."""


def test_long_pages_are_split_with_overlap():
    from ingestion_service.app.chunker import create_chunks

    chunks = create_chunks([{"page": 1, "text": "x" * 2000}], chunk_size=800, chunk_overlap=100)
    assert [c["chunk_index"] for c in chunks] == [1, 2, 3]
    assert all(c["page_number"] == 1 for c in chunks)


def test_empty_pages_produce_no_chunks():
    from ingestion_service.app.chunker import create_chunks

    assert create_chunks([{"page": 1, "text": ""}, {"page": 2, "text": ""}]) == []


def test_bare_model_names_get_the_latest_tag():
    from llm_service.app.main import resolve_model_tag

    assert resolve_model_tag("llama3.2") == "llama3.2:latest"
    assert resolve_model_tag("llama3.2:1b") == "llama3.2:1b"


def test_greetings_are_recognised():
    from llm_service.app.main import is_greeting_question

    assert is_greeting_question("Hello!")
    assert not is_greeting_question("What is the attendance requirement?")


def test_factual_prompts_carry_the_context():
    from llm_service.app.main import build_prompt

    prompt = build_prompt("What is the fee?", "CONTEXT-MARKER")
    assert "RETRIEVED DOCUMENT CONTEXT" in prompt and "CONTEXT-MARKER" in prompt


def test_no_chunks_gives_an_explicit_empty_context():
    from retrieval_service.app.main import assemble_context

    out = assemble_context([])
    assert out["assembled_context"] == "No relevant document chunks found."
    assert out["sources"] == []


def test_blank_questions_are_refused_before_retrieval():
    from api_gateway.app import guardrails

    assert guardrails.validate_input("   ").allowed is False


def test_unset_settings_fall_back_to_the_default():
    from common import config

    assert config.setting("KNOWLEDGEAI_SURELY_UNSET_SETTING", "fallback") == "fallback"
