from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from mitchy.db import fetch_content_context, fetch_student_profile
from services.supabase_client import supabase


TRACK_LABELS = {
    "DA": "Data Analytics",
    "DE": "Data Engineering",
    "DS": "Data Science",
    "Foundation": "Foundation",
    "dip_data_analytics": "Data Analytics",
    "dip_data_engineering": "Data Engineering",
    "dip_data_science": "Data Science",
}

TRACK_TO_COURSE_TITLES = {
    "DA": ["Data Analytics", "Analytics"],
    "DE": ["Data Engineering", "Engineering"],
    "DS": ["Data Science", "Science"],
}

TRACK_TO_COURSE_KEYS = {
    "DA": ["DA", "Data Analytics", "dip_data_analytics"],
    "DE": ["DE", "Data Engineering", "dip_data_engineering"],
    "DS": ["DS", "Data Science", "dip_data_science"],
}


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _first_row(data: Any) -> Dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return {}


def _safe_rows(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


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


def _normalize_track(track: Any) -> Optional[str]:
    raw = str(track or "").strip()
    lowered = raw.lower()

    if raw in {"DA", "DE", "DS"}:
        return raw

    if "analytics" in lowered:
        return "DA"
    if "engineering" in lowered:
        return "DE"
    if "science" in lowered:
        return "DS"

    return None


def _fetch_course_for_track(track_code: Optional[str]) -> Dict[str, Any]:
    if not track_code:
        return {}

    candidates = TRACK_TO_COURSE_KEYS.get(track_code, [track_code])

    # Fast path: exact track/key matching.
    for candidate in candidates:
        try:
            response = (
                supabase.table("courses")
                .select("id, track, title, description, order_index, is_foundation, is_active")
                .eq("track", candidate)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            row = _first_row(response.data)
            if row.get("id"):
                return row
        except Exception:
            pass

    # Fallback: title search.
    for title_part in TRACK_TO_COURSE_TITLES.get(track_code, []):
        try:
            response = (
                supabase.table("courses")
                .select("id, track, title, description, order_index, is_foundation, is_active")
                .ilike("title", f"%{title_part}%")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            row = _first_row(response.data)
            if row.get("id"):
                return row
        except Exception:
            pass

    return {}


def _fetch_rows(table: str, select: str, column: str, value: str) -> List[Dict[str, Any]]:
    try:
        response = (
            supabase.table(table)
            .select(select)
            .eq(column, value)
            .eq("is_active", True)
            .order("order_index")
            .execute()
        )
        return _safe_rows(response.data)
    except Exception:
        return []


def _fetch_learning_path(track_code: Optional[str]) -> Dict[str, Any]:
    course = _fetch_course_for_track(track_code)
    if not course.get("id"):
        return {"course": course, "levels": [], "modules": [], "topics": []}

    levels = _fetch_rows(
        "levels",
        "id, course_id, title, order_index, xp_reward, is_active",
        "course_id",
        course["id"],
    )

    modules: List[Dict[str, Any]] = []
    topics: List[Dict[str, Any]] = []

    for level in levels:
        level_modules = _fetch_rows(
            "modules",
            "id, level_id, title, order_index, xp_reward, is_active",
            "level_id",
            level.get("id"),
        )
        for module in level_modules:
            module["level_title"] = level.get("title")
            module["level_order_index"] = level.get("order_index")
            modules.append(module)

            module_topics = _fetch_rows(
                "topics",
                "id, module_id, title, order_index, xp_reward, is_active",
                "module_id",
                module.get("id"),
            )
            for topic in module_topics:
                topic["module_title"] = module.get("title")
                topic["module_order_index"] = module.get("order_index")
                topic["level_title"] = level.get("title")
                topic["level_order_index"] = level.get("order_index")
                topics.append(topic)

    return {
        "course": course,
        "levels": levels,
        "modules": modules,
        "topics": topics,
    }


def _format_topic_list(topics: List[Dict[str, Any]], limit: int = 8) -> str:
    if not topics:
        return ""

    lines: List[str] = []
    for index, topic in enumerate(topics[:limit], start=1):
        module_title = topic.get("module_title") or "module"
        topic_title = topic.get("title") or "Untitled topic"
        lines.append(f"{index}. {topic_title} ({module_title})")

    return "\n".join(lines)


def _answer_learning_path_question(
    *,
    text: str,
    user_id: str,
    topic_id: Optional[str],
    module_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    is_learning_path_question = _matches_any(
        text,
        [
            r"\bwhat\s+should\s+i\s+learn\b",
            r"\bwhat\s+should\s+i\s+study\b",
            r"\bwhat\s+to\s+learn\b",
            r"\bwhat\s+to\s+study\b",
            r"\bwhat\s+is\s+next\b",
            r"\bwhat\s+comes\s+next\b",
            r"\bnext\s+topic\b",
            r"\bnext\s+module\b",
            r"\btopics\s+should\s+i\b",
            r"\bdata\s+analytics\s+track\b",
            r"\bdata\s+engineering\s+track\b",
            r"\bdata\s+science\s+track\b",
            r"\bmy\s+learning\s+path\b",
            r"\bmy\s+roadmap\b",
        ],
    )

    if not is_learning_path_question:
        return None

    position = _fetch_latest_learning_position(user_id)
    context = fetch_content_context(topic_id=topic_id, module_id=module_id)
    track_code = _normalize_track(position.get("assigned_track"))

    # If the user explicitly asks about a track by name, use that track.
    if "data analytics" in text:
        track_code = "DA"
    elif "data engineering" in text:
        track_code = "DE"
    elif "data science" in text:
        track_code = "DS"

    track_label = TRACK_LABELS.get(track_code or "", track_code or "your assigned track")
    path = _fetch_learning_path(track_code)
    topics = path.get("topics") or []

    metadata = {
        "answered_field": "learning_path",
        "assigned_track": position.get("assigned_track"),
        "resolved_track": track_code,
        "course_found": bool((path.get("course") or {}).get("id")),
        "levels_count": len(path.get("levels") or []),
        "modules_count": len(path.get("modules") or []),
        "topics_count": len(topics),
    }

    if not topics:
        return _output(
            "I found your track, but I could not load its topic list yet. Please open your track map and ask me again.",
            metadata,
        )

    topic_list = _format_topic_list(topics, limit=8)
    total = len(topics)

    response = (
        f"For your {track_label} track, start with these topics:\n"
        f"{topic_list}"
    )

    if total > 8:
        response += f"\nThere are {total} topics in this path, so we can continue step by step."

    current_topic = (context.get("topic") or {}).get("title")
    if current_topic:
        response += f"\nYour current topic is {current_topic}, so continue from there first."

    return _output(response, metadata)


def answer_progress_status_question(
    *,
    message: str,
    user_id: str,
    topic_id: Optional[str],
    module_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Answers progress, roadmap, and status questions from Supabase DB.
    """

    text = str(message or "").strip().lower()

    if not text:
        return None

    learning_path_answer = _answer_learning_path_question(
        text=text,
        user_id=user_id,
        topic_id=topic_id,
        module_id=module_id,
    )
    if learning_path_answer:
        return learning_path_answer

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
