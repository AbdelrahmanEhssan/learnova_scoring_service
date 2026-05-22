from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from services.supabase_client import supabase


def _first_row(data: Any) -> Dict[str, Any]:
    if isinstance(data, list) and data:
        first = data[0]
        return first if isinstance(first, dict) else {}

    if isinstance(data, dict):
        return data

    return {}


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False

    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def ensure_public_user(
    *,
    user_id: str,
    user_email: Optional[str] = None,
    full_name: Optional[str] = None,
) -> None:
    """
    chat_sessions.user_id references public.users(id).

    Usually your app should already create public.users rows.
    This function makes Mitchy robust by checking the row before creating a chat session.
    """
    response = (
        supabase.table("users")
        .select("id")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    existing = _first_row(response.data)
    if existing.get("id"):
        return

    if not user_email:
        raise RuntimeError(
            "public.users row does not exist for this user_id, and user_email was not provided. "
            "Use the Supabase Edge Function so it can pass the authenticated user's email."
        )

    supabase.table("users").insert(
        {
            "id": user_id,
            "email": user_email,
            "full_name": full_name,
            "role": "student",
        }
    ).execute()


def fetch_student_profile(user_id: str) -> Dict[str, Any]:
    try:
        response = (
            supabase.table("student_profiles")
            .select(
                "id, user_id, assigned_track, learning_style, learning_mode, "
                "exploration_style, exploration_started_at, exploration_ends_at, "
                "onboarding_complete, current_level_index, xp_total, "
                "bayesian_alpha_visual, bayesian_alpha_auditory, bayesian_alpha_textual"
            )
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        return _first_row(response.data)
    except Exception:
        return {}


def fetch_content_context(
    *,
    topic_id: Optional[str],
    module_id: Optional[str],
) -> Dict[str, Any]:
    """
    Fetch topic/module names when UUIDs are supplied.

    If Flutter sends a non-UUID label, we do not query the UUID columns.
    """
    context: Dict[str, Any] = {
        "topic_id": topic_id,
        "module_id": module_id,
        "topic": None,
        "module": None,
        "level": None,
        "course": None,
        "resources": [],
    }

    try:
        if topic_id and _is_uuid(topic_id):
            topic_response = (
                supabase.table("topics")
                .select("id, module_id, title, order_index, xp_reward, is_active")
                .eq("id", topic_id)
                .limit(1)
                .execute()
            )

            topic = _first_row(topic_response.data)

            if topic:
                context["topic"] = topic

                if not module_id:
                    module_id = topic.get("module_id")
                    context["module_id"] = module_id

                resources_response = (
                    supabase.table("topic_resources")
                    .select("format_type, resource_url, order_index")
                    .eq("topic_id", topic_id)
                    .order("order_index")
                    .limit(10)
                    .execute()
                )

                resources = resources_response.data or []
                context["resources"] = resources if isinstance(resources, list) else []

        if module_id and _is_uuid(module_id):
            module_response = (
                supabase.table("modules")
                .select("id, level_id, title, order_index, xp_reward, is_active")
                .eq("id", module_id)
                .limit(1)
                .execute()
            )

            module = _first_row(module_response.data)

            if module:
                context["module"] = module

                level_id = module.get("level_id")
                if level_id:
                    level_response = (
                        supabase.table("levels")
                        .select("id, course_id, title, order_index, xp_reward, is_active")
                        .eq("id", level_id)
                        .limit(1)
                        .execute()
                    )

                    level = _first_row(level_response.data)
                    context["level"] = level or None

                    course_id = level.get("course_id") if level else None
                    if course_id:
                        course_response = (
                            supabase.table("courses")
                            .select("id, track, title, description, order_index, is_foundation, is_active")
                            .eq("id", course_id)
                            .limit(1)
                            .execute()
                        )

                        context["course"] = _first_row(course_response.data) or None

    except Exception as exc:
        context["context_error"] = str(exc)

    return context


def fetch_or_create_chat_session(
    *,
    user_id: str,
    user_email: Optional[str] = None,
    full_name: Optional[str] = None,
) -> str:
    ensure_public_user(
        user_id=user_id,
        user_email=user_email,
        full_name=full_name,
    )

    try:
        response = (
            supabase.table("chat_sessions")
            .select("id, user_id, started_at, ended_at")
            .eq("user_id", user_id)
            .is_("ended_at", "null")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )

        existing = _first_row(response.data)

        if existing.get("id"):
            return existing["id"]
    except Exception:
        pass

    response = (
        supabase.table("chat_sessions")
        .insert({"user_id": user_id})
        .execute()
    )

    created = _first_row(response.data)

    if not created.get("id"):
        raise RuntimeError("Could not create Mitchy chat session")

    return created["id"]


def fetch_latest_session_id(user_id: str) -> Optional[str]:
    try:
        open_response = (
            supabase.table("chat_sessions")
            .select("id, started_at, ended_at")
            .eq("user_id", user_id)
            .is_("ended_at", "null")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )

        open_session = _first_row(open_response.data)
        if open_session.get("id"):
            return open_session["id"]
    except Exception:
        pass

    try:
        latest_response = (
            supabase.table("chat_sessions")
            .select("id, started_at, ended_at")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )

        latest_session = _first_row(latest_response.data)
        return latest_session.get("id")
    except Exception:
        return None


def fetch_recent_chat_history(user_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    session_id = fetch_latest_session_id(user_id)

    if not session_id:
        return []

    try:
        response = (
            supabase.table("chat_messages")
            .select(
                "id, session_id, role, content, mitchy_action, "
                "detected_learning_state, sent_at"
            )
            .eq("session_id", session_id)
            .order("sent_at", desc=True)
            .limit(limit)
            .execute()
        )

        rows = response.data or []
        if not isinstance(rows, list):
            return []

        return list(reversed(rows))

    except Exception:
        return []


def fetch_recent_mitchy_turns(user_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    rows = fetch_recent_chat_history(user_id=user_id, limit=limit)

    pairs: List[Dict[str, Any]] = []
    pending_user_message: Optional[str] = None

    for row in rows:
        role = row.get("role")
        content = str(row.get("content") or "").strip()

        if role == "user":
            pending_user_message = content
            continue

        if role == "assistant" and pending_user_message:
            action = row.get("mitchy_action") or {}
            if not isinstance(action, dict):
                action = {}

            pairs.append(
                {
                    "user_message": pending_user_message,
                    "mitchy_response": content,
                    "learning_state": row.get("detected_learning_state")
                    or action.get("learning_state"),
                    "suggested_action": action.get("suggested_action"),
                    "sentiment_score": action.get("sentiment_score"),
                    "cognitive_load": action.get("cognitive_load"),
                    "recommended_format": action.get("recommended_format"),
                }
            )

            pending_user_message = None

    return pairs


def fetch_recent_sentiment_scores(user_id: str, limit: int = 8) -> List[float]:
    try:
        response = (
            supabase.table("student_sentiment_history")
            .select("sentiment_score")
            .eq("user_id", user_id)
            .order("recorded_at", desc=True)
            .limit(limit)
            .execute()
        )

        rows = response.data or []
        scores: List[float] = []

        for row in rows:
            try:
                scores.append(float(row.get("sentiment_score")))
            except (TypeError, ValueError):
                pass

        return list(reversed(scores))
    except Exception:
        return []


def save_mitchy_interaction(
    *,
    user_id: str,
    user_email: Optional[str],
    full_name: Optional[str],
    user_message: str,
    mitchy_response: str,
    sentiment_score: float,
    cognitive_load: float,
    learning_state: str,
    suggested_action: str,
    recommended_format: str,
    recommended_format_db: str,
    topic_id: Optional[str],
    module_id: Optional[str],
    screen_context: Optional[str],
    model_name: Optional[str],
    raw_model_output: Optional[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Saves one Mitchy turn using the existing schema:

    1. chat_sessions
    2. chat_messages role=user
    3. chat_messages role=assistant
    4. student_sentiment_history
    """
    try:
        session_id = fetch_or_create_chat_session(
            user_id=user_id,
            user_email=user_email,
            full_name=full_name,
        )

        base_metadata = metadata or {}

        user_action = {
            "source": "flutter",
            "topic_id": topic_id,
            "module_id": module_id,
            "screen_context": screen_context,
        }

        assistant_action = {
            "suggested_action": suggested_action,
            "recommended_format": recommended_format,
            "recommended_format_db": recommended_format_db,
            "sentiment_score": sentiment_score,
            "cognitive_load": cognitive_load,
            "learning_state": learning_state,
            "model_name": model_name,
            "topic_id": topic_id,
            "module_id": module_id,
            "screen_context": screen_context,
            "metadata": base_metadata,
            "raw_model_output": raw_model_output,
        }

        user_insert = (
            supabase.table("chat_messages")
            .insert(
                {
                    "session_id": session_id,
                    "role": "user",
                    "content": user_message,
                    "mitchy_action": user_action,
                    "detected_learning_state": None,
                }
            )
            .execute()
        )

        assistant_insert = (
            supabase.table("chat_messages")
            .insert(
                {
                    "session_id": session_id,
                    "role": "assistant",
                    "content": mitchy_response,
                    "mitchy_action": assistant_action,
                    "detected_learning_state": learning_state,
                }
            )
            .execute()
        )

        sentiment_insert = (
            supabase.table("student_sentiment_history")
            .insert(
                {
                    "user_id": user_id,
                    "sentiment_score": sentiment_score,
                    "learning_state": learning_state,
                    "session_context": screen_context or "mitchy_chat",
                }
            )
            .execute()
        )

        return {
            "ok": True,
            "session_id": session_id,
            "user_message": user_insert.data,
            "assistant_message": assistant_insert.data,
            "sentiment_history": sentiment_insert.data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
