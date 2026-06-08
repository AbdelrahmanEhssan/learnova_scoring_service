from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from services.supabase_client import supabase
from mitchy.language_utils import has_arabic, normalize_for_intent


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do",
    "does", "for", "from", "how", "i", "in", "into", "is", "it", "me",
    "of", "on", "or", "that", "the", "this", "to", "what", "when",
    "where", "which", "who", "why", "with", "you", "your", "am", "was",
    "were", "will", "would", "should", "could", "please", "simple", "simply",
    "tell", "about", "explain", "define", "meaning", "mean", "difference",
    "between", "example", "examples", "learn", "lesson", "topic", "module",
    "so", "after", "finishing", "finish", "finished", "track", "job", "jobs",
    "work", "career", "role", "roles", "hired", "employment", "where", "next",
}

# Single-token concepts that are expected in LearNova's curriculum.
# A short query like "java?" is too ambiguous and should not search document_chunks.
COURSE_SINGLE_TERMS = {
    "python", "sql", "excel", "powerbi", "tableau", "pandas", "numpy",
    "scipy", "scrapy", "mongodb", "postgresql", "docker", "airflow",
    "spark", "pyspark", "dbt", "prefect", "regression", "clustering",
    "xgboost", "lightgbm", "svm", "pca", "tensorflow", "keras",
    "cnn", "rnn", "lstm", "transformers", "attention", "dax",
    "etl", "elt", "api", "apis", "sqlalchemy", "polars", "validation",
}

RETRIEVAL_TRIGGERS = [
    "what is", "what are", "explain", "define", "meaning of",
    "difference between", "how does", "how do", "why does", "why do",
    "example of", "examples of", "tell me about",
]

NON_RETRIEVAL_PATTERNS = [
    r"^hi+$", r"^hey+$", r"^hello+$", r"^ok(?:ay)?$",
    r"^thanks?$", r"^thank\s+you$",
    r"\bwhat\s+is\s+your\s+name\b", r"\bwho\s+are\s+you\b", r"\bwho\s+r\s+u\b", r"\byour\s+name\b",
    r"\bwhat\s+is\s+my\s+rank\b", r"\bmy\s+rank\b", r"\bmy\s+track\b", r"\bwhat\s+is\s+my\s+track\b",
    r"\bwhat\s+should\s+i\s+learn\b", r"\bwhat\s+should\s+i\s+study\b",
    r"\bafter\s+finishing\b", r"\bwhere\s+can\s+i\s+work\b", r"\bwhat\s+is\s+my\s+job\b",
    r"\bcareer\b", r"\bjobs?\b", r"\bemployment\b", r"\bdata\s+analytics\s+job\b",
    r"انت\s+مين", r"مين\s+انت", r"من\s+انت", r"اتكلم\s+.*عربي", r"بتفهم\s+عربي",
    r"ابدا", r"ابدأ", r"اذاكر", r"أذاكر", r"تايه", r"خطة", r"النهارده", r"انهارده",
    r"اشتغل", r"وظيف", r"كارير", r"بعد\s+.*التراك", r"نظام\s+.*xp", r"ازاي\s+.*xp", r"ازاى\s+.*xp",
]

PROMO_PATTERNS = [
    "join our", "contact us", "sales:<email>", "errors:<email>",
    "coding game", "w3schools coding game", "check out our", "discord",
    "reference page", "supported in html", "academy for educational institutions",
]

BAD_LOW_CONTEXT_PHRASES = [
    "how to apply colors to fonts",
    "apply colors to cells",
    "font color goes for both numbers and text",
]

CAREER_OR_PROGRESS_WORDS = {"job", "jobs", "career", "work", "employment", "hired", "rank", "xp", "badge", "badges", "perk", "perks", "track"}


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


def _global_min_score() -> int:
    try:
        return max(4, int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_GLOBAL_MIN_SCORE", "4")))
    except Exception:
        return 4


def _topic_min_score() -> int:
    try:
        return max(1, int(os.getenv("MITCHY_DOCUMENT_RETRIEVAL_TOPIC_MIN_SCORE", "1")))
    except Exception:
        return 1


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _keywords(message: str) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", message.lower())
    keywords = [word for word in words if word not in STOPWORDS and len(word) >= 2]

    normalized: List[str] = []
    for word in keywords:
        if word.endswith("?"):
            word = word[:-1]
        if word and word not in normalized:
            normalized.append(word)

    return normalized[:8]


def _is_non_retrieval_message(message: str) -> bool:
    text = message.lower().strip()
    return any(re.search(pattern, text) for pattern in NON_RETRIEVAL_PATTERNS)


def _has_retrieval_trigger(message: str) -> bool:
    text = message.lower().strip()
    return any(trigger in text for trigger in RETRIEVAL_TRIGGERS)


def _should_attempt_retrieval(message: str, topic_id: Optional[str], screen_context: Optional[str]) -> Tuple[bool, str, List[str]]:
    clean_message = _normalize_text(message)
    normalized_intent = normalize_for_intent(clean_message)
    text = normalized_intent.lower()
    keywords = _keywords(normalized_intent)

    if not clean_message:
        return False, "empty_message", keywords

    # Arabic questions should go to local Arabic handlers/provider unless topic context is explicitly available.
    # The current document_chunks keyword retriever is English-only and otherwise returns random English chunks.
    if has_arabic(clean_message) and not (topic_id and _is_uuid(topic_id)):
        return False, "arabic_global_query_skips_keyword_retrieval", keywords

    if _is_non_retrieval_message(clean_message) or _is_non_retrieval_message(normalized_intent):
        return False, "non_retrieval_identity_progress_or_career", keywords

    if any(word in CAREER_OR_PROGRESS_WORDS for word in keywords) and not (topic_id and _is_uuid(topic_id)):
        return False, "career_or_progress_query_should_use_db_or_provider", keywords

    if len(clean_message) < 8:
        return False, "message_too_short", keywords

    if not keywords:
        return False, "no_keywords", keywords

    has_topic_context = bool(topic_id and _is_uuid(topic_id))
    has_trigger = _has_retrieval_trigger(text)
    is_dashboard = str(screen_context or "").lower() in {"dashboard", "home", "profile", ""}

    # If the user is inside a specific topic, allow focused retrieval with one keyword.
    if has_topic_context:
        return True, "topic_context", keywords

    # On dashboard/global context, be strict. A single random token like "java?"
    # should NOT search the whole knowledge base.
    if len(keywords) == 1:
        keyword = keywords[0]
        if has_trigger and keyword in COURSE_SINGLE_TERMS:
            return True, "global_single_known_course_term", keywords
        return False, "single_keyword_global_query_too_ambiguous", keywords

    if is_dashboard and not has_trigger:
        return False, "dashboard_without_conceptual_trigger", keywords

    return True, "global_concept_question", keywords


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


def _is_promotional_or_noisy(content: str, keywords: List[str]) -> bool:
    lowered = content.lower()

    # If the user is actually asking about fonts/colors/Excel, do not over-filter those chunks.
    user_asks_about_excel_ui = any(k in keywords for k in {"font", "fonts", "color", "colors", "excel", "cell", "cells"})

    if not user_asks_about_excel_ui and any(phrase in lowered for phrase in BAD_LOW_CONTEXT_PHRASES):
        return True

    promo_hits = sum(1 for phrase in PROMO_PATTERNS if phrase in lowered)
    return promo_hits >= 2


def _score_row(row: Dict[str, Any], keywords: List[str], topic_id: Optional[str]) -> int:
    content = str(row.get("content") or "").lower()
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if _is_promotional_or_noisy(content, keywords):
        return -100

    haystack = content + " " + " ".join(str(v).lower() for v in metadata.values() if v is not None)
    score = 0

    for keyword in keywords:
        if keyword in haystack:
            score += 1
        # small support for singular/plural variants
        if keyword.endswith("s") and keyword[:-1] in haystack:
            score += 1

    if topic_id and _is_uuid(topic_id) and row.get("topic_id") == topic_id:
        score += 1

    return score


def _best_rows(message: str, topic_id: Optional[str], screen_context: Optional[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    should_retrieve, reason, keywords = _should_attempt_retrieval(message, topic_id, screen_context)

    debug = {
        "retrieval_gate_reason": reason,
        "keywords": keywords,
    }

    if not should_retrieve:
        return [], debug

    limit = _limit()
    candidate_map: Dict[str, Dict[str, Any]] = {}

    if topic_id and _is_uuid(topic_id):
        for keyword in keywords[:4]:
            for row in _fetch_candidates(keyword, topic_id=topic_id, limit=limit * 3):
                candidate_map[str(row.get("id"))] = row

    # Global fallback only when the gate allowed it.
    if not candidate_map:
        for keyword in keywords[:4]:
            for row in _fetch_candidates(keyword, topic_id=None, limit=limit * 3):
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
    debug["candidate_count"] = len(candidate_map)
    debug["accepted_count"] = len(scored)
    debug["min_score"] = min_score

    return [row for _, row in scored[:limit]], debug


def _select_relevant_sentences(content: str, keywords: List[str], max_sentences: int = 3) -> str:
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", content)
    selected: List[str] = []

    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            if not _is_promotional_or_noisy(sentence, keywords):
                selected.append(sentence.strip())
        if len(selected) >= max_sentences:
            break

    if not selected:
        # Avoid returning the first random transcript sentence for weak global matches.
        return ""

    answer = " ".join(selected).strip()
    if len(answer) > 650:
        answer = answer[:647].rstrip() + "..."
    return answer


def _summarize(rows: List[Dict[str, Any]], message: str) -> str:
    keywords = _keywords(message)
    snippets: List[str] = []

    for row in rows[:3]:
        content = _normalize_text(row.get("content"))
        selected = _select_relevant_sentences(content, keywords=keywords, max_sentences=3)
        if selected:
            snippets.append(selected)

    if not snippets:
        return ""

    # Do not glue unrelated chunks together. One good answer is better than
    # multiple noisy "related notes".
    return snippets[0]


def answer_from_document_chunks(
    *,
    message: str,
    topic_id: Optional[str] = None,
    screen_context: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Answers simple educational questions from document_chunks before Gemini.

    Safety rules:
    - Does not answer greetings or identity questions.
    - Does not globally retrieve for one-word ambiguous queries like "java?".
    - Requires stronger matching on dashboard/global context.
    - Filters promotional/noisy chunks.
    - Returns None when evidence is weak so Gemini/provider can answer instead.
    """

    if not _enabled():
        return None

    clean_message = str(message or "").strip()

    try:
        rows, debug = _best_rows(clean_message, topic_id=topic_id, screen_context=screen_context)
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
