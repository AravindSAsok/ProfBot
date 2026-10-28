from pinkydocs.document_loader import load_pasted_text
from pinkydocs.chunker import chunk_document
from pinkydocs.models import Chunk
from pinkydocs.retriever import build_retrieval_query, normalize_tokens, retrieve


def make_chunk(doc_id: str, name: str, index: int, content: str) -> Chunk:
    return Chunk(doc_id, name, "txt", index, content)


def test_exact_and_partial_matches_rank_relevant_chunk_first():
    chunks = [
        make_chunk("1", "leave.txt", 0, "Employees receive 18 annual leave days per calendar year."),
        make_chunk("2", "sick.txt", 0, "Employees receive ten sick leave days each year."),
        make_chunk("3", "travel.txt", 0, "The office travel reimbursement form is available online."),
    ]
    exact = retrieve("annual leave days", chunks)
    assert exact[0].chunk.filename == "leave.txt"
    partial = retrieve("How many annual holidays?", chunks)
    assert partial[0].chunk.filename == "leave.txt"


def test_retrieves_across_multiple_documents():
    chunks = [
        make_chunk("1", "annual.txt", 0, "Annual leave allowance is eighteen days."),
        make_chunk("2", "sick.txt", 0, "Sick leave allowance is ten days."),
    ]
    results = retrieve("leave allowance", chunks, limit=5)
    assert {result.chunk.document_id for result in results} == {"1", "2"}


def test_irrelevant_and_empty_queries_return_no_matches():
    chunks = [make_chunk("1", "policy.txt", 0, "Employees receive annual leave days.")]
    assert retrieve("quantum telescope galaxy", chunks) == []
    assert retrieve("   ", chunks) == []
    assert retrieve("a of the", chunks) == []


def test_deduplicates_near_identical_overlapping_chunks():
    words = " ".join(f"policyword{i}" for i in range(100))
    chunks = [
        make_chunk("1", "long.txt", 0, "annual leave " + words),
        make_chunk("1", "long.txt", 1, "annual leave " + words),
    ]
    results = retrieve("annual leave", chunks, limit=5)
    assert len(results) == 1


def test_normalization_and_followup_context():
    assert normalize_tokens("How MANY annual-leave days?") == ["many", "annual", "leave", "days"]
    history = [{"role": "user", "content": "How many annual leave days are available?"}]
    query = build_retrieval_query("Can they be carried forward?", history)
    assert "annual leave days" in query
    independent = build_retrieval_query("What is the probation period?", history)
    assert independent == "What is the probation period?"


def test_chunked_pasted_text_is_retrievable():
    document = load_pasted_text("Policy", "Probation\nThe probation period lasts 3 months.")
    chunks = chunk_document(document)
    result = retrieve("probation period", chunks)
    assert result
    assert result[0].chunk.section_title == "Probation"
    assert "Probation" in result[0].chunk.content
