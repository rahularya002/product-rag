from __future__ import annotations

import os
from typing import List, Tuple

from langchain_core.documents import Document

from .prompts import is_hindi_voice


def format_docs(docs: List[Document]) -> str:
    if not docs:
        return "No relevant context found."
    parts: List[str] = []
    for d in docs:
        src = (d.metadata or {}).get("source", "unknown")
        lang = (d.metadata or {}).get("lang", "unknown")
        parts.append(f"[{lang}] ({src})\n{d.page_content}".strip())
    return "\n\n---\n\n".join(parts)


def _dedupe_docs(docs_with_scores: List[Tuple[Document, float]]) -> List[Tuple[Document, float]]:
    seen: set[tuple[str, str, str]] = set()
    out: List[Tuple[Document, float]] = []
    for d, score in docs_with_scores:
        md = d.metadata or {}
        key = (
            str(md.get("source", "")),
            (d.page_content or "")[:80],
            str(md.get("lang", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append((d, score))
    return out


def retrieve_docs_with_scores(vector_db, question: str, voice: str) -> Tuple[List[Document], bool]:
    """
    Returns:
      - merged docs (sorted best-first)
      - context_empty flag
    """
    k = int(os.environ.get("RETRIEVAL_K", "6"))
    total_k = int(os.environ.get("RETRIEVAL_TOTAL_K", str(max(1, k * 2))))

    # Why this matters:
    # For Hindi questions, your DB contains `lang=hi` AND also `lang=en` and `lang=neutral`.
    # Previously you filtered to only hi+neutral, which can starve context.
    if is_hindi_voice(voice):
        # Prefer Hindi content and mixed-Hinglish-neutral before English to avoid mixing unrelated claims.
        lang_order = ["hi", "neutral", "en"]
        primary_lang = "hi"
    else:
        lang_order = ["en", "neutral", "hi"]
        primary_lang = "en"

    # We want primary-language context to always dominate selection.
    min_primary_k = int(os.environ.get("RETRIEVAL_MIN_PRIMARY_K", str(k)))

    bucket_hits: dict[str, List[Tuple[Document, float]]] = {}
    for lang in lang_order:
        try:
            hits = vector_db.similarity_search_with_score(
                question,
                k=k,
                filter={"lang": lang},
            )
        except Exception:
            # Fallback: no filter
            hits = vector_db.similarity_search_with_score(question, k=k)
        bucket_hits[lang] = hits

    # Dedupe keys used for both stages.
    def _key(doc: Document) -> tuple[str, str, str]:
        md = doc.metadata or {}
        return (str(md.get("source", "")), (doc.page_content or "")[:80], str(md.get("lang", "")))

    # Stage 1: take from primary bucket first (ensures grounding).
    selected: List[Tuple[Document, float]] = []
    selected_keys: set[tuple[str, str, str]] = set()

    for d, score in sorted(bucket_hits.get(primary_lang, []), key=lambda x: x[1]):
        k_ = _key(d)
        if k_ in selected_keys:
            continue
        selected_keys.add(k_)
        selected.append((d, score))
        if len(selected) >= min_primary_k or len(selected) >= total_k:
            break

    # Stage 2: fill remaining slots using best score across all buckets.
    if len(selected) < total_k:
        candidates: List[Tuple[Document, float]] = []
        for lang in lang_order:
            candidates.extend(bucket_hits.get(lang, []))

        # Sort by distance (lower is more similar)
        candidates.sort(key=lambda x: x[1])

        for d, score in candidates:
            k_ = _key(d)
            if k_ in selected_keys:
                continue
            selected_keys.add(k_)
            selected.append((d, score))
            if len(selected) >= total_k:
                break

    merged_docs = [d for d, _score in selected]
    return merged_docs, len(merged_docs) == 0


def build_context(vector_db, question: str, voice: str) -> Tuple[str, bool]:
    docs, context_empty = retrieve_docs_with_scores(vector_db, question, voice)
    return format_docs(docs), context_empty

