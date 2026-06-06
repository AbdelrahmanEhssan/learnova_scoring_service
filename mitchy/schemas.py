from __future__ import annotations

from typing import Any, Dict


VALID_LEARNING_STATES = {
    "confused",
    "misconception",
    "frustrated",
    "anxious_overwhelmed",
    "curious_inquiry",
    "flow_mastered",
    "disengaged",
    "external_distraction",
    "burnout_fatigue",
    "human_support",
    "progressing",
    "concerned",
}

VALID_ACTIONS = {
    "none",
    "quiz_review",
    "take_break",
    "rescue_explanation",
    "recommend_resource",
    "human_support",
    "contact_admin",
    "simplify_problem",
    "shift_format",
    "answer_question",
    "seek_human_support",
    "domain_refusal",
}

# Current DB/app-supported formats only.
# student_profiles.learning_style allows only: Visual, Auditory, Textual
VALID_FORMATS = {
    "visual",
    "auditory",
    "textual",
}

try:
    from mitchy_rescue_agent_edited import normalize_style as rescue_normalize_style
except Exception:
    rescue_normalize_style = None


def clamp_float(value: Any, default: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    return round(max(low, min(number, high)), 4)


def clamp_sentiment(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    return round(max(-1.0, min(number, 1.0)), 4)


def normalize_learning_state(value: Any, default: str = "confused") -> str:
    state = str(value or "").strip().lower()

    aliases = {
        "anxious": "anxious_overwhelmed",
        "overwhelmed": "anxious_overwhelmed",
        "burnout": "burnout_fatigue",
        "tired": "burnout_fatigue",
        "mastered": "flow_mastered",
        "flow": "flow_mastered",
        "curious": "curious_inquiry",
        "support": "human_support",
        "needs_human_support": "human_support",
        "normal": "curious_inquiry",
    }

    state = aliases.get(state, state)

    return state if state in VALID_LEARNING_STATES else default


def normalize_action(value: Any, default: str = "none") -> str:
    action = str(value or "").strip().lower()

    aliases = {
        "break": "take_break",
        "review": "quiz_review",
        "rescue": "rescue_explanation",
        "resource": "recommend_resource",
        "support": "human_support",
        "needs_human_support": "human_support",
        "seek_support": "seek_human_support",
        "clarify": "rescue_explanation",
        "answer": "answer_question",
        "domain_redirect": "domain_refusal",
    }

    action = aliases.get(action, action)

    return action if action in VALID_ACTIONS else default


def normalize_format(value: Any, default: str = "textual") -> str:
    raw = str(value or "").strip()

    if rescue_normalize_style is not None:
        try:
            raw = rescue_normalize_style(raw)
        except Exception:
            pass

    fmt = raw.lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "read_write": "textual",
        "readwrite": "textual",
        "read/write": "textual",
        "text": "textual",
        "textual_article": "textual",
        "article": "textual",
        "kinesthetic": "textual",
        "kinesthetic_challenge": "textual",
        "hands_on": "textual",
        "practical": "textual",
        "video": "visual",
        "visual_video": "visual",
        "audio": "auditory",
        "auditory_audio": "auditory",
        "visual": "visual",
        "auditory": "auditory",
        "textual": "textual",
    }

    fmt = aliases.get(fmt, fmt)

    return fmt if fmt in VALID_FORMATS else default


def format_to_db_title(value: Any) -> str:
    fmt = normalize_format(value)

    return {
        "visual": "Visual",
        "auditory": "Auditory",
        "textual": "Textual",
    }.get(fmt, "Textual")


def profile_to_recommended_format(profile: Dict[str, Any] | None) -> str:
    profile = profile or {}
    raw_style = profile.get("learning_style") or "Textual"

    return normalize_format(raw_style, default="textual")


def normalize_mitchy_output(
    payload: Dict[str, Any] | None,
    local_analysis: Dict[str, Any],
    default_format: str,
) -> Dict[str, Any]:
    payload = payload or {}

    fallback_text = local_analysis.get(
        "response_text",
        "Let's slow this down and handle it one small step at a time.",
    )

    response_text = str(
        payload.get("response_text")
        or payload.get("text")
        or fallback_text
    ).strip()

    if not response_text:
        response_text = fallback_text

    local_state = normalize_learning_state(
        local_analysis.get("learning_state"),
        default="confused",
    )
    local_action = normalize_action(
        local_analysis.get("suggested_action"),
        default="none",
    )

    learning_state = normalize_learning_state(
        payload.get("learning_state"),
        default=local_state,
    )
    suggested_action = normalize_action(
        payload.get("suggested_action") or payload.get("action"),
        default=local_action,
    )

    if learning_state in {"confused", "misconception"} and suggested_action == "none":
        suggested_action = "rescue_explanation"

    recommended_format = normalize_format(
        payload.get("recommended_format") or payload.get("format_used"),
        default=default_format,
    )

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    # Keep the uploaded prompt's metadata fields if the model returned them.
    if "confidence_score" in metadata and "confidence" not in payload:
        confidence = clamp_float(metadata.get("confidence_score"), default=0.5)
    else:
        confidence = clamp_float(payload.get("confidence"), default=0.5)

    return {
        "response_text": response_text,
        "learning_state": learning_state,
        "sentiment_score": clamp_sentiment(local_analysis.get("sentiment_score", 0.0)),
        "cognitive_load": clamp_float(
            local_analysis.get("cognitive_load"),
            default=0.3,
        ),
        "suggested_action": suggested_action,
        "recommended_format": recommended_format,
        "recommended_format_db": format_to_db_title(recommended_format),
        "confidence": confidence,
        "metadata": metadata,
    }
