from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def _safe_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _first_row(data: Any) -> Dict[str, Any]:
    rows = _safe_rows(data)
    return rows[0] if rows else {}


def _safe_select_one(table: str, user_id: str) -> Dict[str, Any]:
    try:
        response = supabase.table(table).select("*").eq("user_id", user_id).limit(1).execute()
        return _first_row(response.data)
    except Exception:
        return {}


def _safe_select_many(table: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        response = supabase.table(table).select("*").eq("user_id", user_id).limit(limit).execute()
        return _safe_rows(response.data)
    except Exception:
        return []


def _safe_user_row(user_id: str) -> Dict[str, Any]:
    for table in ("users", "profiles"):
        try:
            response = supabase.table(table).select("*").eq("id", user_id).limit(1).execute()
            row = _first_row(response.data)
            if row:
                return row
        except Exception:
            pass
    return {}


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


def _public_row_subset(row: Dict[str, Any], max_keys: int = 30) -> Dict[str, Any]:
    blocked_fragments = {"password", "token", "secret", "key", "provider", "auth"}
    clean: Dict[str, Any] = {}
    for key, value in row.items():
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in blocked_fragments):
            continue
        if value is None:
            continue
        clean[key] = value
        if len(clean) >= max_keys:
            break
    return clean


def _fetch_gamification(user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort gamification context. This intentionally supports multiple possible
    table names so the code does not break if some tables do not exist yet.
    """

    xp_total = (
        profile.get("xp_total")
        or profile.get("xp_points")
        or profile.get("total_xp")
        or profile.get("xp")
    )

    rank_rows: List[Dict[str, Any]] = []
    for table in (
        "leaderboard",
        "leaderboards",
        "student_leaderboard",
        "student_leaderboard_entries",
        "user_rankings",
        "student_rankings",
    ):
        row = _safe_select_one(table, user_id)
        if row:
            row["_source_table"] = table
            rank_rows.append(_public_row_subset(row))
            break

    badges: List[Dict[str, Any]] = []
    for table in ("student_badges", "user_badges", "earned_badges", "profile_badges"):
        rows = _safe_select_many(table, user_id, limit=20)
        if rows:
            badges = [_public_row_subset({**row, "_source_table": table}) for row in rows]
            break

    perks: List[Dict[str, Any]] = []
    for table in ("student_perks", "user_perks", "perks_inventory", "user_perks_inventory", "profile_perks"):
        rows = _safe_select_many(table, user_id, limit=20)
        if rows:
            perks = [_public_row_subset({**row, "_source_table": table}) for row in rows]
            break

    next_level = None
    for table in ("levels", "xp_levels", "gamification_levels"):
        if xp_total is None:
            break
        try:
            response = supabase.table(table).select("*").gte("xp_required", xp_total).order("xp_required").limit(1).execute()
            row = _first_row(response.data)
            if row:
                next_level = _public_row_subset({**row, "_source_table": table})
                break
        except Exception:
            pass

    xp_to_next_level = None
    if isinstance(next_level, dict) and xp_total is not None:
        for key in ("xp_required", "required_xp", "min_xp"):
            if key in next_level:
                try:
                    xp_to_next_level = max(0, int(float(next_level[key])) - int(float(xp_total)))
                    break
                except Exception:
                    pass

    return {
        "xp_total": xp_total,
        "rank": rank_rows[0] if rank_rows else None,
        "badges": badges,
        "perks": perks,
        "next_level": next_level,
        "xp_to_next_level": xp_to_next_level,
        "notes": "Some fields may be null if the relevant gamification table is not present or has no rows for this user.",
    }


def build_user_context(
    *,
    user_id: str,
    user_email: Optional[str] = None,
    full_name: Optional[str] = None,
    topic_id: Optional[str] = None,
    module_id: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    profile = profile or fetch_student_profile(user_id)
    user_row = _safe_user_row(user_id)
    content_context = fetch_content_context(topic_id=topic_id, module_id=module_id)

    assigned_track = profile.get("assigned_track") or user_row.get("assigned_track")
    track_code = _normalize_track(assigned_track)
    track_label = TRACK_LABELS.get(track_code or str(assigned_track), assigned_track)

    display_name = (
        full_name
        or profile.get("full_name")
        or user_row.get("full_name")
        or user_row.get("name")
        or user_row.get("display_name")
        or user_email
        or user_row.get("email")
    )

    return {
        "user": {
            "id": user_id,
            "email": user_email or user_row.get("email"),
            "display_name": display_name,
        },
        "profile": _public_row_subset(profile, max_keys=60),
        "track": {
            "assigned_track": assigned_track,
            "track_code": track_code,
            "track_label": track_label,
        },
        "learning_preferences": {
            "learning_style": profile.get("learning_style"),
            "learning_mode": profile.get("learning_mode"),
            "exploration_style": profile.get("exploration_style"),
            "onboarding_complete": profile.get("onboarding_complete"),
        },
        "gamification": _fetch_gamification(user_id, profile),
        "current_context": {
            "topic_id": topic_id,
            "module_id": module_id,
            "topic": content_context.get("topic"),
            "module": content_context.get("module"),
            "level": content_context.get("level"),
            "course": content_context.get("course"),
        },
    }


def compact_user_context_for_prompt(context: Dict[str, Any]) -> Dict[str, Any]:
    return context
