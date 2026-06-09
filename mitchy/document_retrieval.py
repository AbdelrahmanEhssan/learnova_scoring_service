from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from services.supabase_client import supabase
from mitchy.language_utils import has_arabic, normalize_for_intent

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does", "for", "from", "how", "i", "in", "into", "is", "it", "me", "of", "on", "or", "that", "the", "this", "to", "what", "when", "where", "which", "who", "why", "with", "you", "your", "am", "was", "were", "will", "would", "should", "could", "please", "simple", "simply", "tell", "about", "explain", "define", "meaning", "mean", "difference", "between", "example", "examples", "learn", "lesson", "topic", "module", "study", "start", "plan", "today", "free", "minutes", "next", "track", "progress", "rank", "xp", "badge", "badges", "perk", "perks", "job", "jobs", "career", "work",
}

NON_RETRIEVAL_PATTERNS = [
    r"\bwho\s+are\s+you\b", r"\bwhat\s+is\s+your\s+name\b", r"\bcan\s+you\s+speak\b", r"\barabic\b",
    r"\bwhat\s+should\s+i\b", r"\bwhat\s+to\s+study\b", r"\bstart\s+with\b", r"\broadmap\b", r"\bplan\b",
    r"\bmy\s+(rank|xp|badges?|perks?|track|progress)\b", r"\bnext\s+(level|badge|milestone|topic|module)\b",
    r"\bcareer\b", r"\bjobs?\b", r"\bwhere\s+can\s+i\s+work\b", r"\bafter\s+.*track\b", r"\bcv\b", r"\bproject\b",
]

BAD_LOW_CONTEXT_PHRASES = [
    "check out", "join our", "reference page", "coding game", "follow me", "linkedin", "subscribe", "like and", "download the", "digital version", "reach out to me", "what is up everyone", "hey what is up", "love but yeah", "um the", "uh you", "sort of",
]


def _enabled() -> bool:
    return os.getenv("MITCHY_DOCUMENT_RETRIEVAL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _global_enabled() -> bool:
    # Global keyword retrieval is disabled by default because the KB contains long
    # transcripts and can otherwise return unrelated snippets. Use provider/basic
    # concept logic for dashboard/global questions.
    return os.getenv("MITCHY_DOCUMENT_RETRIEVAL_GLOBAL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _limit() -> int:
    try:
        return max(1, min(int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_LIMIT", "5")), 10))
    except Exception:
        return 5


def _topic_min_score() -> int:
    try:
        return max(1, int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_TOPIC_MIN_SCORE", "1")))
    except Exception:
        return 1


def _global_min_score() -> int:
    try:
        return max(4, int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_GLOBAL_MIN_SCORE", "6")))
    except Exception:
        return 6


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _keywords(message: str) -> List[str]:
    text = normalize_for_intent(message).lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]*", text)
    keywords = [word.strip(".-_") for word in words if word not in STOPWORDS and len(word) >= 3]
    normalized: List[str] = []
    for word in keywords:
        if word and word not in normalized:
            normalized.append(word)
    return normalized[:8]


def _is_non_retrieval_message(message: str) -> bool:
    text = normalize_for_intent(message).lower()
    return any(re.search(pattern, text) for pattern in NON_RETRIEVAL_PATTERNS)


def _should_attempt_retrieval(message: str, topic_id: Optional[str], screen_context: Optional[str]) -> Tuple[bool, str, List[str]]:
    clean_message = _normalize_text(message)
    keywords = _keywords(clean_message)
    has_topic_context = bool(topic_id and _is_uuid(topic_id))

    if not _enabled():
        return False, "retrieval_disabled", keywords
    if not clean_message:
        return False, "empty_message", keywords
    if has_arabic(clean_message) and not has_topic_context:
        return False, "arabic_global_query_uses_provider_or_local_handlers", keywords
    if _is_non_retrieval_message(clean_message):
        return False, "non_retrieval_intent", keywords
    if not keywords:
        return False, "no_keywords", keywords

    if has_topic_context:
        return True, "topic_context", keywords

    if not _global_enabled():
        return False, "global_retrieval_disabled_to_prevent_noisy_transcript_matches", keywords

    if len(keywords) < 3:
        return False, "global_query_too_short", keywords

    return True, "global_retrieval_explicitly_enabled", keywords


def _fetch_candidates(keyword: str, topic_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    query = supabase.table("document_chunks").select("id, topic_id, content, metadata, inserted_at").ilike("content", f"%{keyword}%").limit(limit)
    if topic_id and _is_uuid(topic_id):
        query = query.eq("topic_id", topic_id)
    rows = query.execute().data or []
    return rows if isinstance(rows, list) else []


def _is_noisy(content: str) -> bool:
    lowered = content.lower()
    return any(phrase in lowered for phrase in BAD_LOW_CONTEXT_PHRASES)


def _score_row(row: Dict[str, Any], keywords: List[str], topic_id: Optional[str]) -> int:
    content = str(row.get("content") or "").lower()
    if _is_noisy(content):
        return -100
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    haystack = content + " " + " ".join(str(v).lower() for v in metadata.values() if v is not None)
    score = sum(1 for kw in keywords if kw in haystack)
    if topic_id and _is_uuid(topic_id) and row.get("topic_id") == topic_id:
        score += 2
    return score


def _best_rows(message: str, topic_id: Optional[str], screen_context: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    should_retrieve, reason, keywords = _should_attempt_retrieval(message, topic_id, screen_context)
    debug = {"retrieval_gate_reason": reason, "keywords": keywords}
    if not should_retrieve:
        return [], debug

    candidate_map: Dict[str, Dict[str, Any]] = {}
    limit = _limit()
    for keyword in keywords[:4]:
        for row in _fetch_candidates(keyword, topic_id=topic_id if _is_uuid(topic_id) else None, limit=limit * 4):
            candidate_map[str(row.get("id"))] = row

    min_score = _topic_min_score() if topic_id and _is_uuid(topic_id) else _global_min_score()
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for row in candidate_map.values():
        score = _score_row(row, keywords, topic_id)
        if score >= min_score:
            enriched = dict(row)
            enriched["_retrieval_score"] = score
            scored.append((score, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    debug.update({"candidate_count": len(candidate_map), "accepted_count": len(scored), "min_score": min_score})
    return [row for _, row in scored[:limit]], debug


def _select_relevant_sentences(content: str, keywords: List[str], max_sentences: int = 3) -> str:
    content = re.sub(r"\s+", " ", content).strip()
    if not content or _is_noisy(content):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", content)
    selected: List[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords) and not _is_noisy(sentence):
            selected.append(sentence.strip())
        if len(selected) >= max_sentences:
            break
    answer = " ".join(selected).strip()
    if len(answer) > 520:
        answer = answer[:517].rstrip() + "..."
    return answer


def answer_from_document_chunks(*, message: str, topic_id: Optional[str] = None, screen_context: Optional[str] = None) -> Optional[Dict[str, Any]]:
    clean_message = str(message or "").strip()
    rows, debug = _best_rows(clean_message, topic_id=topic_id, screen_context=screen_context)
    if not rows:
        return None
    keywords = _keywords(clean_message)
    answer = ""
    for row in rows[:3]:
        answer = _select_relevant_sentences(_normalize_text(row.get("content")), keywords)
        if answer:
            break
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
        "confidence": 0.74,
        "metadata": {
            "source": "document_chunks_retrieval",
            "used_gemini": False,
            "topic_id": topic_id,
            **debug,
            "matched_chunks": [
                {
                    "id": row.get("id"),
                    "topic_id": row.get("topic_id"),
                    "score": row.get("_retrieval_score"),
                    "chunk_id": (row.get("metadata") or {}).get("chunk_id") if isinstance(row.get("metadata"), dict) else None,
                    "topic_key": (row.get("metadata") or {}).get("topic_key") if isinstance(row.get("metadata"), dict) else None,
                }
                for row in rows[:3]
            ],
        },
    }
