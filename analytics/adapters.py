from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional


STYLE_TO_DB = {
    "visual": "Visual",
    "auditory": "Auditory",
    "textual": "Textual",
}

STYLE_TO_MODULE = {
    "visual": "visual",
    "video": "visual",
    "visual_video": "visual",
    "Visual": "visual",

    "auditory": "auditory",
    "audio": "auditory",
    "auditory_audio": "auditory",
    "Auditory": "auditory",

    "text": "textual",
    "textual": "textual",
    "article": "textual",
    "read_write": "textual",
    "Textual": "textual",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(value, high)), 4)


def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def normalize_style(value: Any, default: str = "textual") -> str:
    if value is None:
        return default

    key = str(value).strip().replace("-", "_").replace(" ", "_")

    return STYLE_TO_MODULE.get(key, STYLE_TO_MODULE.get(key.lower(), default))


def normalize_db_style(value: Any, default: str = "Textual") -> str:
    style = normalize_style(value, default="textual")
    return STYLE_TO_DB.get(style, default)


def average_score_from_attempts(rows: List[Dict[str, Any]]) -> Optional[float]:
    scores: List[float] = []

    for row in rows:
        if row.get("score") is not None:
            scores.append(safe_float(row.get("score")))

    if not scores:
        return None

    return mean(scores)


def failure_ratio(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0

    failures = 0

    for row in rows:
        score = row.get("score")

        if row.get("passed") is False:
            failures += 1
        elif row.get("completed") is False:
            failures += 1
        elif score is not None and safe_float(score) < 70:
            failures += 1

    return failures / len(rows)


def adapt_engagement_logs_for_drift(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts Supabase content_engagement_logs rows into detect_drift2.py input.

    Supabase shape:
      format_type, time_spent_seconds, engagement_score, logged_at

    detect_drift2.py expected shape:
      selected_slot, content_type, duration_seconds, completion_percentage, created_at
    """

    adapted: List[Dict[str, Any]] = []

    for row in rows:
        style = normalize_style(row.get("format_type"))

        engagement_score = row.get("engagement_score")
        completion_percentage = 100.0

        if engagement_score is not None:
            score = safe_float(engagement_score)
            completion_percentage = score * 100 if 0 <= score <= 1 else score

        adapted.append(
            {
                "user_id": row.get("user_id"),
                "topic_id": row.get("topic_id"),
                "selected_slot": style,
                "content_type": style,
                "duration_seconds": safe_int(row.get("time_spent_seconds")),
                "completion_percentage": completion_percentage,
                "created_at": row.get("logged_at"),
                "_source_table": "content_engagement_logs",
                "_source_row": row,
            }
        )

    return adapted


def adapt_student_profile_for_bayesian(profile_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Converts student_profiles row into bayesian_engine3.py expected profile shape.
    """

    profile_row = profile_row or {}

    return {
        "visual_alpha": max(1, safe_int(profile_row.get("bayesian_alpha_visual"), 1)),
        "auditory_alpha": max(1, safe_int(profile_row.get("bayesian_alpha_auditory"), 1)),
        "textual_alpha": max(1, safe_int(profile_row.get("bayesian_alpha_textual"), 1)),
        "current_primary_style": normalize_style(profile_row.get("learning_style"), default="textual"),
        "shift_threshold": safe_float(profile_row.get("bayesian_shift_threshold"), 0.65),
    }


def adapt_bayesian_profile_update_for_supabase(updated_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts bayesian_engine3.py updated profile back into student_profiles columns.
    """

    current_style = normalize_db_style(updated_profile.get("current_primary_style"))

    return {
        "bayesian_alpha_visual": max(1, safe_int(updated_profile.get("visual_alpha"), 1)),
        "bayesian_alpha_auditory": max(1, safe_int(updated_profile.get("auditory_alpha"), 1)),
        "bayesian_alpha_textual": max(1, safe_int(updated_profile.get("textual_alpha"), 1)),
        "learning_style": current_style,
    }


def _adapt_module_attempt(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": row.get("user_id"),
        "topic_id": row.get("assessment_id") or row.get("topic_id") or row.get("module_id"),
        "score": safe_float(row.get("score")),
        "created_at": row.get("submitted_at"),
        "quiz_type": "module",
        "passed": row.get("passed"),
        "_source_table": "student_module_attempts",
        "_source_row": row,
    }


def _adapt_challenge_attempt(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": row.get("user_id"),
        "topic_id": row.get("challenge_id") or row.get("topic_id"),
        "score": safe_float(row.get("score")),
        "created_at": row.get("submitted_at"),
        "quiz_type": "challenge",
        "completed": row.get("completed"),
        "_source_table": "student_challenge_attempts",
        "_source_row": row,
    }


def _adapt_level_attempt(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": row.get("user_id"),
        "topic_id": row.get("assessment_id") or row.get("level_id") or row.get("topic_id"),
        "score": safe_float(row.get("score")),
        "created_at": row.get("submitted_at"),
        "quiz_type": "level",
        "passed": row.get("passed"),
        "_source_table": "student_level_attempts",
        "_source_row": row,
    }


def adapt_attempt_rows_for_concept_decay(
    module_attempts: Iterable[Dict[str, Any]],
    challenge_attempts: Iterable[Dict[str, Any]],
    level_attempts: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Converts current Supabase attempt rows into attempt-like dictionaries
    compatible with concept decay logic.
    """

    adapted: List[Dict[str, Any]] = []

    for row in module_attempts:
        adapted.append(_adapt_module_attempt(row))

    for row in challenge_attempts:
        adapted.append(_adapt_challenge_attempt(row))

    for row in level_attempts:
        adapted.append(_adapt_level_attempt(row))

    return adapted


def adapt_rows_for_topic_struggle(
    module_attempts: Iterable[Dict[str, Any]],
    challenge_attempts: Iterable[Dict[str, Any]],
    level_attempts: Iterable[Dict[str, Any]],
    sentiment_rows: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Converts current Supabase rows into compact struggle inputs.
    """

    attempts = (
        list(module_attempts)
        + list(challenge_attempts)
        + list(level_attempts)
    )

    scores = [
        safe_float(row.get("score"))
        for row in attempts
        if row.get("score") is not None
    ]

    sentiment_scores = [
        safe_float(row.get("sentiment_score"))
        for row in sentiment_rows
        if row.get("sentiment_score") is not None
    ]

    return {
        "attempts": attempts,
        "scores": scores,
        "sentiment_scores": sentiment_scores,
        "attempt_count": len(attempts),
        "failure_ratio": failure_ratio(attempts),
        "average_score": average_score_from_attempts(attempts),
        "negative_sentiment_rate": (
            len([score for score in sentiment_scores if score < 0]) / len(sentiment_scores)
            if sentiment_scores
            else 0.0
        ),
    }


def _parse_jsonish(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    return {}


def extract_successful_rescue_signal(
    chat_rows: Iterable[Dict[str, Any]],
    sentiment_rows: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Best-effort signal for bayesian_engine3.py.

    We only update Bayesian alpha fields when there is evidence that a Mitchy
    recommendation/adaptation was followed by positive sentiment.
    If there is no reliable signal, return None so the pipeline does no profile update.
    """

    positive_sentiments = [
        row
        for row in sentiment_rows
        if safe_float(row.get("sentiment_score"), 0.0) >= 0.40
    ]

    if not positive_sentiments:
        return None

    assistant_rows = [
        row
        for row in chat_rows
        if str(row.get("role", "")).lower() == "assistant"
    ]

    # Prefer explicit recommended_format_db in mitchy_action when available.
    for row in reversed(assistant_rows):
        action = _parse_jsonish(row.get("mitchy_action"))

        metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}

        fmt = (
            action.get("recommended_format_db")
            or action.get("recommended_format")
            or metadata.get("recommended_format_db")
            or metadata.get("recommended_format")
        )

        if fmt:
            return {
                "successful_format": normalize_style(fmt),
                "sentiment_score": max(
                    safe_float(item.get("sentiment_score"), 0.0)
                    for item in positive_sentiments
                ),
            }

    # If no explicit format was found, do not update.
    return None
