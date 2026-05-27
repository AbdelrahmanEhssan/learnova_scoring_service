from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from services.supabase_client import supabase


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do",
    "does", "for", "from", "how", "i", "in", "into", "is", "it", "me",
    "of", "on", "or", "that", "the", "this", "to", "what", "when",
    "where", "which", "who", "why", "with", "you", "your", "am",
    "explain", "tell", "about", "please", "simple", "simply",
}

RETRIEVAL_TRIGGERS = [
    "what is", "what are", "explain", "define", "meaning of",
    "difference between", "how does", "how do", "why does", "why do",
    "example of",
]


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _enabled() -> bool:
    return os.getenv("MITCHY_DOCUMENT_RETRIEVAL_ENABLED", "true").lower() not in {"0", "false", "no"}


def _limit() -> int:
    try:
        return max(1, min(int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_LIMIT", "5")), 10))
    except Exception:
        return 5


def _min_score() -> int:
    try:
        return max(1, int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_MIN_SCORE", "1")))
    except Exception:
        return 1


def _keywords(message: str) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", message.lower())
    keywords = [word for word in words if word not in STOPWORDS and len(word) >= 2]

    seen = set()
    result = []
    for word in keywords:
        if word not in seen:
            seen.add(word)
            result.append(word)

    return result[:8]


def _looks_like_course_question(message: str) -> bool:
    text = message.lower().strip()

    if "?" in text:
        return True

    return any(trigger in text for trigger in RETRIEVAL_TRIGGERS)


def _fetch_candidates(keyword: str, topic_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    query = (
        supabase.table("document_chunks")
        .select("id, topic_id, content, metadata, inserted_at")
        .ilike("content", f"%{keyword}%")
        .limit(limit)
    )

    if topic_id and _is_uuid(topic_id):
        query = query.eq("topic_id", topic_id)

    response = query.execute()
    rows = response.data or []

    return rows if isinstance(rows, list) else []


def _score_row(row: Dict[str, Any], keywords: List[str]) -> int:
    content = str(row.get("content") or "").lower()
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    haystack = content + " " + " ".join(str(v).lower() for v in metadata.values() if v is not None)

    return sum(1 for keyword in keywords if keyword in haystack)


def _best_rows(message: str, topic_id: Optional[str]) -> List[Dict[str, Any]]:
    keywords = _keywords(message)

    if not keywords:
        return []

    limit = _limit()
    candidate_map: Dict[str, Dict[str, Any]] = {}

    if topic_id and _is_uuid(topic_id):
        for keyword in keywords[:3]:
            for row in _fetch_candidates(keyword, topic_id=topic_id, limit=limit * 2):
                candidate_map[str(row.get("id"))] = row

    if not candidate_map:
        for keyword in keywords[:4]:
            for row in _fetch_candidates(keyword, topic_id=None, limit=limit * 2):
                candidate_map[str(row.get("id"))] = row

    scored = []
    for row in candidate_map.values():
        score = _score_row(row, keywords)
        if score >= _min_score():
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)

    return [row for _, row in scored[:limit]]


def _summarize(rows: List[Dict[str, Any]], message: str) -> str:
    snippets: List[str] = []

    for row in rows[:3]:
        content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
        if not content:
            continue

        sentences = re.split(r"(?<=[.!?])\s+", content)
        selected = " ".join(sentences[:3]).strip()

        if len(selected) > 550:
            selected = selected[:547].rstrip() + "..."

        if selected:
            snippets.append(selected)

    if not snippets:
        return ""

    answer = snippets[0]

    if len(snippets) > 1:
        answer += "\n\nRelated note: " + snippets[1]

    return answer


def answer_from_document_chunks(
    *,
    message: str,
    topic_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Answers simple educational questions from document_chunks before Gemini.

    This is intentionally simple and DB-first. It does not require embeddings/RPC.
    """

    if not _enabled():
        return None

    clean_message = str(message or "").strip()

    if not clean_message or not _looks_like_course_question(clean_message):
        return None

    try:
        rows = _best_rows(clean_message, topic_id=topic_id)
    except Exception as exc:
        return {
            "response_text": (
                "I tried to check the course material, but I could not read it right now. "
                "Let’s still break the question down simply."
            ),
            "learning_state": "confused",
            "sentiment_score": 0.0,
            "cognitive_load": 0.3,
            "suggested_action": "rescue_explanation",
            "recommended_format": "textual",
            "recommended_format_db": "Textual",
            "confidence": 0.35,
            "metadata": {
                "source": "document_chunks_retrieval_error",
                "used_gemini": False,
                "retrieval_error": str(exc),
            },
        }

    if not rows:
        return None

    answer = _summarize(rows, clean_message)

    if not answer:
        return None

    return {
        "response_text": answer,
        "learning_state": "curious_inquiry",
        "sentiment_score": 0.0,
        "cognitive_load": 0.25,
        "suggested_action": "answer_question",
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": 0.72,
        "metadata": {
            "source": "document_chunks_retrieval",
            "used_gemini": False,
            "topic_id": topic_id,
            "matched_chunks": [
                {
                    "id": row.get("id"),
                    "topic_id": row.get("topic_id"),
                    "chunk_id": (row.get("metadata") or {}).get("chunk_id")
                    if isinstance(row.get("metadata"), dict)
                    else None,
                    "topic_key": (row.get("metadata") or {}).get("topic_key")
                    if isinstance(row.get("metadata"), dict)
                    else None,
                }
                for row in rows[:3]
            ],
        },
    }
