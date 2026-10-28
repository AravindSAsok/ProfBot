"""Deterministic BM25-style lexical retrieval for local document chunks."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from .models import Chunk, RetrievedChunk


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do",
    "does", "for", "from", "how", "i", "in", "is", "it", "of", "on", "or",
    "about", "please", "should", "the", "their", "this", "to", "was", "what", "when",
    "where", "which", "who", "with", "would", "you", "your",
}


def normalize_tokens(text: str) -> list[str]:
    """Normalize words and remove common query noise."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def retrieve(
    query: str,
    chunks: Iterable[Chunk],
    *,
    limit: int = 6,
    min_score: float = 0.12,
) -> list[RetrievedChunk]:
    """Rank chunks with BM25, phrase boosts, overlap suppression, and a floor."""
    if not query.strip() or limit <= 0:
        return []
    docs = list(chunks)
    query_tokens = normalize_tokens(query)
    if not query_tokens or not docs:
        return []
    tokenized = [normalize_tokens(chunk.content) for chunk in docs]
    lengths = [len(tokens) for tokens in tokenized]
    average_length = sum(lengths) / max(1, len(lengths))
    query_frequency = Counter(query_tokens)
    document_frequency = Counter(token for tokens in tokenized for token in set(tokens))
    query_phrase = " ".join(query_tokens)
    scored: list[RetrievedChunk] = []
    for chunk, tokens, length in zip(docs, tokenized, lengths):
        frequencies = Counter(tokens)
        score = 0.0
        matched: set[str] = set()
        for term, qf in query_frequency.items():
            frequency = frequencies[term]
            if frequency:
                matched.add(term)
                idf = math.log(1 + (len(docs) - document_frequency[term] + 0.5) /
                               (document_frequency[term] + 0.5))
                denominator = frequency + 1.2 * (0.25 + 0.75 * length / max(1, average_length))
                score += idf * frequency * 2.2 / denominator * min(qf, 2)
        if not matched:
            continue
        normalized = score / max(1.0, len(query_frequency) ** 0.55)
        if len(query_tokens) > 1 and query_phrase in " ".join(tokens):
            normalized *= 1.35
        normalized *= 0.65 + 0.35 * len(matched) / len(query_frequency)
        if normalized < min_score:
            continue
        scored.append(RetrievedChunk(chunk=chunk, score=normalized))

    scored.sort(key=lambda result: (-result.score, result.chunk.document_id, result.chunk.chunk_index))
    selected: list[RetrievedChunk] = []
    for result in scored:
        candidate_terms = set(normalize_tokens(result.chunk.content))
        redundant = False
        for prior in selected:
            if result.chunk.document_id != prior.chunk.document_id:
                continue
            prior_terms = set(normalize_tokens(prior.chunk.content))
            union = candidate_terms | prior_terms
            if union and len(candidate_terms & prior_terms) / len(union) >= 0.82:
                redundant = True
                break
        if not redundant:
            selected.append(result)
        if len(selected) >= limit:
            break
    return selected


def build_retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    """Use one recent user question to resolve short follow-ups without a model call."""
    q_tokens = normalize_tokens(question)
    followup_markers = {"they", "them", "it", "that", "those", "second", "also"}
    starts_as_direct_question = bool(
        re.match(r"^(what is|how many|when is|where is|who is|how long)\b", question.strip().casefold())
    )
    is_followup = (
        bool(set(q_tokens) & followup_markers)
        or question.strip().casefold().startswith("what about ")
        or (len(q_tokens) <= 2 and not starts_as_direct_question)
    )
    if not is_followup:
        return question
    for message in reversed(history):
        if message.get("role") == "user" and message.get("content", "").strip():
            return f"{question} {message['content']}"
    return question
