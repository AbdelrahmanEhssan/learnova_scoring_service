from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is useful locally, but not mandatory in hosted envs.
    load_dotenv = None

try:
    import google.generativeai as genai
except ImportError:  # Allows local validation tests to run without the Gemini SDK installed.
    genai = None

if load_dotenv is not None:
    load_dotenv()

DEFAULT_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_BRIEFING = "Unable to generate briefing – please check analytics manually."

SYSTEM_PROMPT = (
    "You are a senior instructor. Based on the provided JSON analytics, write a concise "
    "3-bullet executive summary. Highlight critical issues and positive trends. Do not invent data."
)

STOPWORDS = {
    "the", "and", "or", "of", "to", "in", "on", "for", "with", "a", "an", "by",
    "topic", "module", "lesson", "foundation", "shared", "sf", "id", "intro",
}


@dataclass(frozen=True)
class TopicRisk:
    topic_id: str
    topic_name: str
    avg_score: Optional[float]
    failure_rate_pct: Optional[float] = None
    students_affected: Optional[int] = None


def fetch_dashboard_context() -> Dict[str, Any]:
    return {
        "date": "2026-05-05",
        "admin_topic_performance": [
            {
                "topic_id": "sf_sql_joins",
                "topic_name": "SQL Joins",
                "avg_score": 0.41,
                "failure_rate_pct": 64.0,
                "students_affected": 20,
            },
            {
                "topic_id": "sf_python_loops",
                "topic_name": "Python Loops & Iterative Logic",
                "avg_score": 0.58,
                "failure_rate_pct": 43.0,
                "students_affected": 12,
            },
        ],
        "admin_class_health": {
            "snapshot_date": "2026-05-05",
            "active_students": 142,
            "negative_sentiment_rate": 0.18,
            "high_risk_students": 9,
            "class_health_status": "moderate_risk",
        },
        "admin_foundation_conversion_rate": [
            {
                "projected_specialization_id": "dip_data_analysis",
                "foundation_starters": 80,
                "checkpoint_passers": 58,
                "entered_projected_diploma": 50,
                "conversion_rate_pct": 62.5,
            }
        ],
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_lowest_avg_score_topic(context_data: Dict[str, Any]) -> Optional[TopicRisk]:
    topics = context_data.get("admin_topic_performance") or context_data.get("topic_performance") or []
    if not isinstance(topics, list):
        return None

    valid_topics: List[TopicRisk] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        avg_score = _safe_float(topic.get("avg_score"))
        if avg_score is None:
            continue
        topic_id = str(topic.get("topic_id", "")).strip()
        topic_name = str(topic.get("topic_name") or topic.get("title") or topic_id).strip()
        valid_topics.append(
            TopicRisk(
                topic_id=topic_id,
                topic_name=topic_name,
                avg_score=avg_score,
                failure_rate_pct=_safe_float(topic.get("failure_rate_pct")),
                students_affected=topic.get("students_affected"),
            )
        )

    if not valid_topics:
        fallback = context_data.get("top_failing_topic")
        if isinstance(fallback, dict):
            return TopicRisk(
                topic_id=str(fallback.get("topic_id", "")).strip(),
                topic_name=str(fallback.get("topic_name") or fallback.get("topic_id") or "").strip(),
                avg_score=_safe_float(fallback.get("avg_score")),
                failure_rate_pct=_safe_float(fallback.get("failure_rate_pct")),
                students_affected=fallback.get("students_affected"),
            )
        return None

    return min(valid_topics, key=lambda item: item.avg_score if item.avg_score is not None else 1.0)


def normalize_text(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize_keywords(value: str) -> List[str]:
    normalized = normalize_text(value)
    tokens = [token for token in normalized.split() if token and token not in STOPWORDS]
    return tokens


def _ngrams(tokens: List[str], max_size: int = 5) -> Iterable[str]:
    for size in range(1, min(max_size, len(tokens)) + 1):
        for index in range(0, len(tokens) - size + 1):
            yield " ".join(tokens[index:index + size])


def build_topic_aliases(topic: TopicRisk) -> List[str]:
    aliases = set()
    if topic.topic_id:
        aliases.add(normalize_text(topic.topic_id))
        aliases.add(" ".join(tokenize_keywords(topic.topic_id)))
    if topic.topic_name:
        aliases.add(normalize_text(topic.topic_name))
        aliases.add(" ".join(tokenize_keywords(topic.topic_name)))

    # Add compact keyword aliases such as "joins", "loops", "iterative logic".
    name_tokens = tokenize_keywords(topic.topic_name)
    id_tokens = tokenize_keywords(topic.topic_id.replace("_", " "))
    for token in name_tokens + id_tokens:
        if len(token) >= 4:
            aliases.add(token)
    for token_list in (name_tokens, id_tokens):
        for phrase in _ngrams(token_list, max_size=3):
            if len(phrase) >= 4:
                aliases.add(phrase)

    return sorted(alias for alias in aliases if alias)


def fuzzy_topic_mentioned(briefing_text: str, topic: TopicRisk, threshold: float = 0.78) -> bool:
    normalized_briefing = normalize_text(briefing_text)
    if not normalized_briefing or not topic:
        return False

    aliases = build_topic_aliases(topic)
    briefing_tokens = normalized_briefing.split()
    briefing_phrases = set(_ngrams(briefing_tokens, max_size=5))

    for alias in aliases:
        if not alias:
            continue
        if alias in normalized_briefing:
            return True
        for phrase in briefing_phrases:
            if SequenceMatcher(None, alias, phrase).ratio() >= threshold:
                return True

    topic_keywords = [token for token in tokenize_keywords(topic.topic_name) if len(token) >= 4]
    if topic_keywords:
        matched_keywords = [token for token in topic_keywords if token in normalized_briefing]
        # Require either one highly specific keyword for short names, or at least half the keywords.
        if len(topic_keywords) <= 2 and matched_keywords:
            return True
        if len(matched_keywords) / len(topic_keywords) >= 0.5:
            return True

    return False


def parse_three_bullet_briefing(text: str) -> Optional[List[str]]:
    if not isinstance(text, str):
        return None

    candidate_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", line).strip()
        if line:
            candidate_lines.append(line)

    if len(candidate_lines) != 3:
        return None

    return candidate_lines


def format_bullets(bullets: List[str]) -> str:
    return "\n".join(f"- {bullet}" for bullet in bullets)


def build_prompt(context_data: Dict[str, Any]) -> str:
    lowest_topic = get_lowest_avg_score_topic(context_data)
    required_topic_note = ""
    if lowest_topic:
        required_topic_note = (
            "\n\nValidation requirement: The topic with the lowest avg_score is "
            f"'{lowest_topic.topic_name}' (topic_id: {lowest_topic.topic_id}, "
            f"avg_score: {lowest_topic.avg_score}). Mention this topic in the briefing "
            "if it is a critical issue."
        )

    return (
        f"{SYSTEM_PROMPT}"
        "\n\nOutput format rules:"
        "\n- Return exactly 3 bullets."
        "\n- Each bullet must be one sentence."
        "\n- Do not return JSON."
        "\n- Do not mention data that is not present in the JSON."
        "\n- Include both risk and positive trend coverage when available."
        f"{required_topic_note}"
        f"\n\nJSON analytics:\n{json.dumps(context_data, ensure_ascii=False, indent=2)}"
    )


def _configure_model(model_name: str):
    if genai is None:
        raise RuntimeError("google-generativeai is not installed.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing.")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def generate_daily_briefing(
    context_data: Dict[str, Any],
    model_name: str = DEFAULT_MODEL_NAME,
    timeout_seconds: int = 20,
) -> str:
    try:
        model = _configure_model(model_name)
        response = model.generate_content(
            build_prompt(context_data),
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                max_output_tokens=350,
            ),
            request_options={"timeout": timeout_seconds},
        )
        response_text = getattr(response, "text", "")
        bullets = parse_three_bullet_briefing(response_text)
        if bullets is None:
            return DEFAULT_BRIEFING
        return format_bullets(bullets)
    except Exception:
        return DEFAULT_BRIEFING


def validate_briefing_mentions_lowest_score_topic(
    context_data: Dict[str, Any],
    briefing_text: str,
) -> Tuple[bool, Optional[TopicRisk]]:
    lowest_topic = get_lowest_avg_score_topic(context_data)
    if lowest_topic is None:
        return True, None
    return fuzzy_topic_mentioned(briefing_text, lowest_topic), lowest_topic


def generate_and_validate_daily_briefing(context_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience wrapper for the backend/admin service.
    """
    briefing = generate_daily_briefing(context_data)
    validation_passed, topic_checked = validate_briefing_mentions_lowest_score_topic(
        context_data,
        briefing,
    )

    return {
        "briefing": briefing,
        "validation_passed": validation_passed,
        "validated_topic_id": topic_checked.topic_id if topic_checked else None,
        "validated_topic_name": topic_checked.topic_name if topic_checked else None,
        "model": DEFAULT_MODEL_NAME,
        "used_fallback": briefing == DEFAULT_BRIEFING,
    }


if __name__ == "__main__":
    dashboard_context = fetch_dashboard_context()
    result = generate_and_validate_daily_briefing(dashboard_context)
    print(json.dumps(result, indent=2, ensure_ascii=False))
