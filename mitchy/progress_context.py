from __future__ import annotations

import re
from typing import Any, Dict, Optional
from uuid import UUID

from mitchy.db import fetch_content_context, fetch_student_profile


TRACK_LABELS = {
    "DA": "Data Analytics",
    "DE": "Data Engineering",
    "DS": "Data Science",
    "Foundation": "Foundation",
    "dip_data_analytics": "Data Analytics",
    "dip_data_engineering": "Data Engineering",
    "dip_data_science": "Data Science",
}


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _output(text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "response_text": text,
        "learning_state": "progressing",
        "sentiment_score": 0.0,
        "cognitive_load": 0.2,
        "suggested_action": "none",
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": 0.9,
        "metadata": {
            "source": "db_progress_context",
            "used_gemini": False,
            **metadata,
        },
    }


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _fetch_latest_learning_position(user_id: str) -> Dict[str, Any]:
    profile = fetch_student_profile(user_id)

    return {
        "profile": profile,
        "assigned_track": profile.get("assigned_track"),
        "learning_style": profile.get("learning_style"),
        "learning_mode": profile.get("learning_mode"),
        "current_level_index": profile.get("current_level_index"),
        "xp_total": profile.get("xp_total"),
        "onboarding_complete": profile.get("onboarding_complete"),
    }


def answer_progress_status_question(
    *,
    message: str,
    user_id: str,
    topic_id: Optional[str],
    module_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Answers simple progress/status questions from Supabase DB.

    Examples:
    - what topic am I in?
    - what track am I in?
    - what module am I currently at?
    - which level am I currently at?
    """

    text = str(message or "").strip().lower()

    if not text:
        return None

    is_progress_question = _matches_any(
        text,
        [
            r"\bwhat\s+topic\b", r"\bwhich\s+topic\b", r"\btopic\s+am\s+i\b",
            r"\bwhat\s+track\b", r"\bwhich\s+track\b", r"\btrack\s+am\s+i\b",
            r"\bmy\s+track\b", r"\bwhat\s+module\b", r"\bwhich\s+module\b",
            r"\bmodule\s+am\s+i\b", r"\bwhat\s+level\b", r"\bwhich\s+level\b",
            r"\blevel\s+am\s+i\b", r"\bmy\s+progress\b", r"\bwhere\s+am\s+i\b",
        ],
    )

    if not is_progress_question:
        return None

    position = _fetch_latest_learning_position(user_id)
    context = fetch_content_context(topic_id=topic_id, module_id=module_id)

    topic = context.get("topic") or {}
    module = context.get("module") or {}
    level = context.get("level") or {}
    course = context.get("course") or {}

    metadata = {
        "topic_id": topic_id,
        "module_id": module_id,
        "profile_found": bool(position.get("profile")),
        "topic_found": bool(topic),
        "module_found": bool(module),
        "level_found": bool(level),
        "course_found": bool(course),
    }

    if "track" in text:
        assigned_track = position.get("assigned_track") or course.get("track")
        label = TRACK_LABELS.get(str(assigned_track), assigned_track)

        if label:
            return _output(
                f"You are currently assigned to the {label} track.",
                {**metadata, "answered_field": "assigned_track", "assigned_track": assigned_track},
            )

        return _output(
            "I could not find your assigned track in the database yet.",
            {**metadata, "answered_field": "assigned_track_missing"},
        )

    if "topic" in text:
        title = topic.get("title")
        order_index = topic.get("order_index")

        if title:
            extra = f" It is topic #{order_index} in this module." if order_index is not None else ""
            return _output(
                f"You are currently in the topic: {title}.{extra}",
                {**metadata, "answered_field": "topic"},
            )

        return _output(
            "I do not have the current topic context yet. Open a topic page and ask me again there.",
            {**metadata, "answered_field": "topic_missing"},
        )

    if "module" in text:
        title = module.get("title")
        order_index = module.get("order_index")

        if title:
            extra = f" It is module #{order_index} in this level." if order_index is not None else ""
            return _output(
                f"You are currently in the module: {title}.{extra}",
                {**metadata, "answered_field": "module"},
            )

        return _output(
            "I do not have the current module context yet. Open a module or topic page and ask me again.",
            {**metadata, "answered_field": "module_missing"},
        )

    if "level" in text:
        title = level.get("title")
        order_index = level.get("order_index")
        profile_level = position.get("current_level_index")

        if title:
            extra = f" It is level #{order_index}." if order_index is not None else ""
            return _output(
                f"You are currently in the level: {title}.{extra}",
                {**metadata, "answered_field": "level"},
            )

        if profile_level is not None:
            return _output(
                f"Your profile says your current level index is {profile_level}.",
                {**metadata, "answered_field": "current_level_index"},
            )

        return _output(
            "I could not find your current level in the database yet.",
            {**metadata, "answered_field": "level_missing"},
        )

    parts: list[str] = []

    if position.get("assigned_track"):
        track_label = TRACK_LABELS.get(str(position["assigned_track"]), position["assigned_track"])
        parts.append(f"Track: {track_label}")

    if level.get("title"):
        parts.append(f"Level: {level['title']}")
    elif position.get("current_level_index") is not None:
        parts.append(f"Level index: {position['current_level_index']}")

    if module.get("title"):
        parts.append(f"Module: {module['title']}")

    if topic.get("title"):
        parts.append(f"Topic: {topic['title']}")

    if position.get("xp_total") is not None:
        parts.append(f"XP: {position['xp_total']}")

    if parts:
        return _output(
            "Here is what I found about your current progress: " + " | ".join(parts),
            {**metadata, "answered_field": "progress_summary"},
        )

    return _output(
        "I could not find enough progress data yet. Try opening your current lesson page and ask me again.",
        {**metadata, "answered_field": "progress_missing"},
    )
