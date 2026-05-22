New-Item -ItemType Directory -Force -Path "Edits" | Out-Null

Set-Content -Path "Edits/mitchy_rescue_agent_edited.py" -Encoding UTF8 -Value @'
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


"""
Schema-aligned Mitchy rescue/adaptation helper.

Current LearNova DB-supported styles:
- Visual
- Auditory
- Textual

Important:
- No kinesthetic output.
- Legacy read_write/readwrite/text labels are normalized to textual.
- Legacy kinesthetic input is safely mapped to textual, but never returned.
- student_profiles.learning_mode supports only: structured, exploration.
"""

SUPPORTED_STYLES = ("visual", "auditory", "textual")

STYLE_TO_DB = {
    "visual": "Visual",
    "auditory": "Auditory",
    "textual": "Textual",
}

DB_TO_STYLE = {
    "Visual": "visual",
    "Auditory": "auditory",
    "Textual": "textual",
}

STYLE_ALIASES = {
    "visual": "visual",
    "video": "visual",
    "visual_video": "visual",
    "diagram": "visual",
    "image": "visual",

    "auditory": "auditory",
    "audio": "auditory",
    "auditory_audio": "auditory",
    "spoken": "auditory",
    "conversation": "auditory",

    "textual": "textual",
    "text": "textual",
    "article": "textual",
    "textual_article": "textual",
    "read_write": "textual",
    "readwrite": "textual",
    "read/write": "textual",
    "reading": "textual",
    "writing": "textual",

    # Backward compatibility only.
    # Do not return kinesthetic. Map it to textual because current DB does not support it.
    "kinesthetic": "textual",
    "kinesthetic_challenge": "textual",
    "hands_on": "textual",
    "practical": "textual",
}

DEFAULT_EXPLORATION_DAYS = 7
DEFAULT_NUDGE_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_MIN_CANDIDATE_STYLE_PCT = 0.60
DEFAULT_MAX_CURRENT_STYLE_PCT = 0.20


def normalize_style(style: Optional[str], default: str = "textual") -> str:
    if not style:
        return default

    normalized = str(style).strip().replace("-", "_").replace(" ", "_")

    if normalized in DB_TO_STYLE:
        return DB_TO_STYLE[normalized]

    normalized = normalized.lower()
    mapped = STYLE_ALIASES.get(normalized, normalized)

    if mapped not in SUPPORTED_STYLES:
        return default

    return mapped


def style_to_db(style: Optional[str]) -> str:
    return STYLE_TO_DB[normalize_style(style)]


def call_llm_api(system_prompt: str, user_query: str) -> str:
    """
    Placeholder LLM call.

    This file should stay lightweight and not import Gemini directly.
    The real Mitchy Gemini call lives in mitchy/gemini_client.py.
    """
    return json.dumps(
        {
            "response_text": (
                "Let's reframe it in a simpler way. First, identify the main idea. "
                "Then follow one step at a time. Which step feels unclear?"
            ),
            "format_used": "textual",
        }
    )


def _alpha_keys_for_style(style: str) -> List[str]:
    """
    Support both current DB names and older in-memory names.
    Current schema:
    - bayesian_alpha_visual
    - bayesian_alpha_auditory
    - bayesian_alpha_textual
    """
    return [
        f"bayesian_alpha_{style}",
        f"{style}_alpha",
    ]


def get_style_alphas(user_profile: Dict[str, Any]) -> Dict[str, float]:
    alphas: Dict[str, float] = {}

    for style in SUPPORTED_STYLES:
        value = None

        for key in _alpha_keys_for_style(style):
            if user_profile.get(key) is not None:
                value = user_profile.get(key)
                break

        try:
            alphas[style] = max(float(value), 1.0) if value is not None else 1.0
        except (TypeError, ValueError):
            alphas[style] = 1.0

    return alphas


def calculate_style_probabilities(user_profile: Dict[str, Any]) -> Dict[str, float]:
    alphas = get_style_alphas(user_profile)
    total = sum(alphas.values()) or float(len(SUPPORTED_STYLES))
    return {style: round(alpha / total, 4) for style, alpha in alphas.items()}


def determine_fallback_format(failed_format: str, user_profile: Dict[str, Any]) -> str:
    failed = normalize_style(failed_format)
    probabilities = calculate_style_probabilities(user_profile)

    candidates = {style: prob for style, prob in probabilities.items() if style != failed}

    if not candidates:
        return "textual" if failed != "textual" else "visual"

    return max(candidates, key=candidates.get)


def _build_format_instruction(target_format: str) -> str:
    target_format = normalize_style(target_format)

    if target_format == "textual":
        return "Use clear short steps, simple definitions, and compact examples."

    if target_format == "visual":
        return "Use spatial language, mental images, small diagrams, or layout-based explanations."

    if target_format == "auditory":
        return "Write conversationally, like a tutor explaining aloud with rhythm and examples."

    return "Use a simple, supportive explanation."


def generate_mitchy_intervention(
    user_query: str,
    topic_name: str,
    failed_format: str,
    user_profile: Dict[str, Any],
) -> Dict[str, Any]:
    failed_format_normalized = normalize_style(failed_format)
    target_format = determine_fallback_format(failed_format_normalized, user_profile)

    system_prompt = f"""
You are Mitchy, the empathetic AI mentor for LearNova.

The learner is struggling with this topic: {topic_name}.
The failed format was: {failed_format_normalized}.

Your mission:
Explain the same concept using the target format: {target_format}.

Format instruction:
{_build_format_instruction(target_format)}

Return strict JSON only with this schema:
{{
  "response_text": "Your empathetic explanation here...",
  "format_used": "{target_format}"
}}

Allowed format_used values:
visual, auditory, textual

Do not use kinesthetic.
""".strip()

    try:
        llm_response_string = call_llm_api(system_prompt, user_query)
        response_data = json.loads(llm_response_string)

        response_text = str(response_data.get("response_text", "")).strip()
        format_used = normalize_style(str(response_data.get("format_used", target_format)))

        if not response_text:
            raise ValueError("LLM returned empty response_text.")

        if format_used not in SUPPORTED_STYLES:
            format_used = target_format

        return {
            "status": "success",
            "mitchy_message": response_text,
            "format_attempted": format_used,
            "format_attempted_db": style_to_db(format_used),
            "failed_format": failed_format_normalized,
            "failed_format_db": style_to_db(failed_format_normalized),
            "bayesian_evidence_pending": True,
        }

    except Exception as exc:
        return {
            "status": "fallback_response_used",
            "mitchy_message": (
                "I know this topic can feel tricky. Let's slow it down. "
                "Tell me the exact step that confused you, and I'll explain it another way."
            ),
            "format_attempted": "textual",
            "format_attempted_db": "Textual",
            "failed_format": failed_format_normalized,
            "failed_format_db": style_to_db(failed_format_normalized),
            "bayesian_evidence_pending": False,
            "error": str(exc),
        }


def should_offer_exploration_nudge(
    drift_signal: Dict[str, Any],
    current_style: str = "visual",
    candidate_style: str = "textual",
    confidence_threshold: float = DEFAULT_NUDGE_CONFIDENCE_THRESHOLD,
    min_candidate_style_pct: float = DEFAULT_MIN_CANDIDATE_STYLE_PCT,
    max_current_style_pct: float = DEFAULT_MAX_CURRENT_STYLE_PCT,
) -> bool:
    current_style = normalize_style(current_style)
    candidate_style = normalize_style(candidate_style)

    current_pct = float(drift_signal.get(f"{current_style}_time_pct", 0.0))
    candidate_pct = float(drift_signal.get(f"{candidate_style}_time_pct", 0.0))

    confidence = float(
        drift_signal.get("confidence_score", drift_signal.get("normalized_confidence", 0.0))
    )

    return (
        current_style != candidate_style
        and current_pct < max_current_style_pct
        and candidate_pct > min_candidate_style_pct
        and confidence > confidence_threshold
    )


def build_exploration_nudge(
    candidate_style: str,
    badge_name: str = "Learning Explorer",
    trial_days: int = DEFAULT_EXPLORATION_DAYS,
) -> Dict[str, Any]:
    candidate_style = normalize_style(candidate_style)
    friendly_style = f"{style_to_db(candidate_style)} Mode"

    return {
        "type": "exploration_nudge",
        "candidate_style": candidate_style,
        "candidate_style_db": style_to_db(candidate_style),
        "trial_days": trial_days,
        "badge_awarded_on_accept": badge_name,
        "message": (
            f"You're engaging a lot with {friendly_style}. "
            f"Want to try {friendly_style} for {trial_days} days?"
        ),
        "primary_action": "Start 7-Day Trial",
        "secondary_action": "Not Now",
    }


def accept_exploration_trial(
    user_profile: Dict[str, Any],
    candidate_style: str,
    now: Optional[datetime] = None,
    trial_days: int = DEFAULT_EXPLORATION_DAYS,
    badge_name: str = "Learning Explorer",
) -> Dict[str, Any]:
    candidate_style = normalize_style(candidate_style)
    now = now or datetime.now(timezone.utc)
    exploration_ends_at = now + timedelta(days=trial_days)

    updated_profile = deepcopy(user_profile)
    updated_profile["exploration_style"] = style_to_db(candidate_style)
    updated_profile["exploration_started_at"] = now.isoformat()
    updated_profile["exploration_ends_at"] = exploration_ends_at.isoformat()

    # Current DB check constraint allows only structured/exploration.
    updated_profile["learning_mode"] = "exploration"

    badges: List[str] = list(updated_profile.get("badges", []))
    if badge_name not in badges:
        badges.append(badge_name)

    updated_profile["badges"] = badges

    return {
        "status": "exploration_started",
        "updated_profile": updated_profile,
        "db_update": {
            "learning_mode": "exploration",
            "exploration_style": style_to_db(candidate_style),
            "exploration_started_at": updated_profile["exploration_started_at"],
            "exploration_ends_at": updated_profile["exploration_ends_at"],
        },
        "badge_awarded": badge_name,
        "confirmation_required_at": updated_profile["exploration_ends_at"],
    }


def build_exploration_confirmation(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    exploration_style = normalize_style(user_profile.get("exploration_style", "textual"))
    friendly_style = f"{style_to_db(exploration_style)} Mode"

    return {
        "type": "exploration_confirmation",
        "candidate_style": exploration_style,
        "candidate_style_db": style_to_db(exploration_style),
        "message": f"Your 7-day {friendly_style} trial is complete. Keep {friendly_style}?",
        "primary_action": f"Keep {friendly_style}",
        "secondary_action": "Return to Previous Mode",
    }


def confirm_exploration_decision(
    user_profile: Dict[str, Any],
    keep_new_style: bool,
) -> Dict[str, Any]:
    updated_profile = deepcopy(user_profile)

    exploration_style = normalize_style(updated_profile.get("exploration_style", "textual"))
    previous_style = normalize_style(
        updated_profile.get("previous_primary_style")
        or updated_profile.get("learning_style")
        or "textual"
    )

    final_style = exploration_style if keep_new_style else previous_style
    status = "exploration_kept_permanent" if keep_new_style else "exploration_reverted"

    updated_profile["learning_style"] = style_to_db(final_style)
    updated_profile["learning_mode"] = "structured"
    updated_profile["exploration_style"] = None
    updated_profile["exploration_started_at"] = None
    updated_profile["exploration_ends_at"] = None

    return {
        "status": status,
        "updated_profile": updated_profile,
        "final_style": final_style,
        "final_style_db": style_to_db(final_style),
        "db_update": {
            "learning_style": style_to_db(final_style),
            "learning_mode": "structured",
            "exploration_style": None,
            "exploration_started_at": None,
            "exploration_ends_at": None,
        },
    }


if __name__ == "__main__":
    dummy_profile = {
        "user_id": "demo_user",
        "learning_style": "Visual",
        "bayesian_alpha_visual": 10,
        "bayesian_alpha_textual": 8,
        "bayesian_alpha_auditory": 2,
        "badges": [],
    }

    rescue_result = generate_mitchy_intervention(
        user_query="I do not understand LEFT JOIN.",
        topic_name="SQL Joins",
        failed_format="visual",
        user_profile=dummy_profile,
    )

    print(json.dumps(rescue_result, indent=2))

    drift_signal = {
        "visual_time_pct": 0.15,
        "textual_time_pct": 0.72,
        "confidence_score": 0.78,
    }

    if should_offer_exploration_nudge(drift_signal):
        nudge = build_exploration_nudge("textual")
        print(json.dumps(nudge, indent=2))

    accepted = accept_exploration_trial(dummy_profile, "textual")
    print(json.dumps(accepted, indent=2))
'@

Set-Content -Path "Edits/ml_pipeline_reviewed.py" -Encoding UTF8 -Value @'
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional


"""
Schema-aligned LearNova daily ML metrics pipeline.

Writes to existing table:
- ml_daily_metrics

Reads from existing tables:
- users
- content_engagement_logs
- student_module_attempts
- student_challenge_attempts
- student_level_attempts
- student_sentiment_history
- chat_sessions
- chat_messages

This replaces old references to:
- quiz_attempts
- mitchy_interaction_logs
- ml_aggregated_metrics
"""

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass

from services.supabase_client import supabase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_metric_date(raw: Optional[str]) -> date:
    if raw:
        return date.fromisoformat(raw)

    env_value = os.getenv("METRIC_DATE")
    if env_value:
        return date.fromisoformat(env_value)

    # Cron normally runs after midnight, so compute yesterday by default.
    return (utc_now() - timedelta(days=1)).date()


def day_window(metric_date: date) -> tuple[str, str]:
    start = datetime.combine(metric_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    return start.isoformat(), end.isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(value, high)), 4)


def fetch_all(table: str, select: str = "*", filters: Optional[List[tuple[str, str, Any]]] = None) -> List[Dict[str, Any]]:
    query = supabase.table(table).select(select)

    for operation, column, value in filters or []:
        if operation == "eq":
            query = query.eq(column, value)
        elif operation == "gte":
            query = query.gte(column, value)
        elif operation == "lt":
            query = query.lt(column, value)
        elif operation == "lte":
            query = query.lte(column, value)
        elif operation == "neq":
            query = query.neq(column, value)

    response = query.execute()
    data = response.data or []

    return data if isinstance(data, list) else []


def group_by_user(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for row in rows:
        user_id = row.get("user_id")
        if user_id:
            grouped[str(user_id)].append(row)

    return grouped


def average_score_from_attempts(rows: List[Dict[str, Any]]) -> Optional[float]:
    scores = []

    for row in rows:
        score = row.get("score")
        if score is not None:
            scores.append(safe_float(score))

    if not scores:
        return None

    # Scores in your app are usually 0-100.
    return mean(scores)


def failure_ratio(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0

    failures = 0

    for row in rows:
        if row.get("passed") is False:
            failures += 1
        elif row.get("completed") is False:
            failures += 1
        elif row.get("score") is not None and safe_float(row.get("score")) < 70:
            failures += 1

    return failures / len(rows)


def compute_engagement_velocity(
    engagement_rows: List[Dict[str, Any]],
    chat_rows: List[Dict[str, Any]],
) -> float:
    if not engagement_rows and not chat_rows:
        return 0.0

    time_spent = sum(int(row.get("time_spent_seconds") or 0) for row in engagement_rows)
    time_component = min(time_spent / 3600.0, 1.0)

    engagement_scores = [
        safe_float(row.get("engagement_score"))
        for row in engagement_rows
        if row.get("engagement_score") is not None
    ]

    score_component = clamp(mean(engagement_scores), 0.0, 1.0) if engagement_scores else 0.0
    chat_component = min(len(chat_rows) / 10.0, 1.0)

    return clamp((0.45 * time_component) + (0.35 * score_component) + (0.20 * chat_component))


def compute_topic_struggle_index(
    module_attempts: List[Dict[str, Any]],
    challenge_attempts: List[Dict[str, Any]],
    level_attempts: List[Dict[str, Any]],
    sentiments: List[Dict[str, Any]],
) -> float:
    attempts = module_attempts + challenge_attempts + level_attempts

    attempt_failure = failure_ratio(attempts)

    average_score = average_score_from_attempts(attempts)
    score_struggle = 0.0 if average_score is None else clamp((100.0 - average_score) / 100.0)

    negative_sentiments = [
        safe_float(row.get("sentiment_score"))
        for row in sentiments
        if row.get("sentiment_score") is not None and safe_float(row.get("sentiment_score")) < 0
    ]

    sentiment_struggle = 0.0
    if negative_sentiments:
        # -1.0 should become 1.0 struggle; -0.2 becomes 0.2.
        sentiment_struggle = clamp(abs(mean(negative_sentiments)))

    return clamp((0.40 * attempt_failure) + (0.35 * score_struggle) + (0.25 * sentiment_struggle))


def compute_concept_decay_score(
    engagement_rows: List[Dict[str, Any]],
    progress_like_attempts: List[Dict[str, Any]],
    sentiments: List[Dict[str, Any]],
) -> float:
    has_activity = bool(engagement_rows or progress_like_attempts or sentiments)

    if not has_activity:
        return 0.75

    negative_sentiments = [
        safe_float(row.get("sentiment_score"))
        for row in sentiments
        if row.get("sentiment_score") is not None and safe_float(row.get("sentiment_score")) < 0
    ]

    sentiment_component = clamp(abs(mean(negative_sentiments))) if negative_sentiments else 0.0
    low_engagement_component = 1.0 - compute_engagement_velocity(engagement_rows, [])

    return clamp((0.55 * low_engagement_component) + (0.45 * sentiment_component))


def run_pipeline(metric_date: Optional[date] = None) -> Dict[str, Any]:
    metric_date = metric_date or parse_metric_date(None)
    start_iso, end_iso = day_window(metric_date)

    users = fetch_all(
        "users",
        "id, email, role",
        filters=[("eq", "role", "student")],
    )

    engagement = fetch_all(
        "content_engagement_logs",
        "user_id, topic_id, format_type, time_spent_seconds, engagement_score, logged_at",
        filters=[("gte", "logged_at", start_iso), ("lt", "logged_at", end_iso)],
    )

    module_attempts = fetch_all(
        "student_module_attempts",
        "user_id, assessment_id, score, passed, submitted_at",
        filters=[("gte", "submitted_at", start_iso), ("lt", "submitted_at", end_iso)],
    )

    challenge_attempts = fetch_all(
        "student_challenge_attempts",
        "user_id, challenge_id, score, completed, submitted_at",
        filters=[("gte", "submitted_at", start_iso), ("lt", "submitted_at", end_iso)],
    )

    level_attempts = fetch_all(
        "student_level_attempts",
        "user_id, assessment_id, score, passed, submitted_at",
        filters=[("gte", "submitted_at", start_iso), ("lt", "submitted_at", end_iso)],
    )

    sentiments = fetch_all(
        "student_sentiment_history",
        "user_id, sentiment_score, learning_state, session_context, recorded_at",
        filters=[("gte", "recorded_at", start_iso), ("lt", "recorded_at", end_iso)],
    )

    sessions = fetch_all(
        "chat_sessions",
        "id, user_id, started_at",
        filters=[("lt", "started_at", end_iso)],
    )

    session_to_user = {
        str(row.get("id")): str(row.get("user_id"))
        for row in sessions
        if row.get("id") and row.get("user_id")
    }

    messages = fetch_all(
        "chat_messages",
        "session_id, role, sent_at",
        filters=[("gte", "sent_at", start_iso), ("lt", "sent_at", end_iso)],
    )

    chat_rows_by_user: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in messages:
        user_id = session_to_user.get(str(row.get("session_id")))
        if user_id:
            chat_rows_by_user[user_id].append(row)

    engagement_by_user = group_by_user(engagement)
    module_by_user = group_by_user(module_attempts)
    challenge_by_user = group_by_user(challenge_attempts)
    level_by_user = group_by_user(level_attempts)
    sentiment_by_user = group_by_user(sentiments)

    rows_to_upsert: List[Dict[str, Any]] = []

    for user in users:
        user_id = str(user["id"])

        user_engagement = engagement_by_user.get(user_id, [])
        user_module = module_by_user.get(user_id, [])
        user_challenge = challenge_by_user.get(user_id, [])
        user_level = level_by_user.get(user_id, [])
        user_sentiment = sentiment_by_user.get(user_id, [])
        user_chat = chat_rows_by_user.get(user_id, [])

        attempts = user_module + user_challenge + user_level

        row = {
            "user_id": user_id,
            "metric_date": metric_date.isoformat(),
            "concept_decay_score": compute_concept_decay_score(
                engagement_rows=user_engagement,
                progress_like_attempts=attempts,
                sentiments=user_sentiment,
            ),
            "engagement_velocity": compute_engagement_velocity(
                engagement_rows=user_engagement,
                chat_rows=user_chat,
            ),
            "topic_struggle_index": compute_topic_struggle_index(
                module_attempts=user_module,
                challenge_attempts=user_challenge,
                level_attempts=user_level,
                sentiments=user_sentiment,
            ),
            "computed_at": utc_now().isoformat(),
        }

        rows_to_upsert.append(row)

    if rows_to_upsert:
        supabase.table("ml_daily_metrics").upsert(
            rows_to_upsert,
            on_conflict="user_id,metric_date",
        ).execute()

    return {
        "ok": True,
        "metric_date": metric_date.isoformat(),
        "users_processed": len(users),
        "rows_upserted": len(rows_to_upsert),
        "source_counts": {
            "content_engagement_logs": len(engagement),
            "student_module_attempts": len(module_attempts),
            "student_challenge_attempts": len(challenge_attempts),
            "student_level_attempts": len(level_attempts),
            "student_sentiment_history": len(sentiments),
            "chat_messages": len(messages),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Metric date in YYYY-MM-DD. Defaults to yesterday UTC.")
    args = parser.parse_args()

    metric_date = parse_metric_date(args.date)
    result = run_pipeline(metric_date=metric_date)

    print(result)


if __name__ == "__main__":
    main()
'@

Set-Content -Path "Edits/daily_insight_generator_reviewed.py" -Encoding UTF8 -Value @'
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional


"""
Schema-aligned daily insight generator.

Reads:
- ml_daily_metrics
- users

Writes:
- in_app_notifications for admin users, using notification_type='general'

This avoids creating a new daily_briefings table for now.
"""

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass

from services.supabase_client import supabase


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_metric_date(raw: Optional[str]) -> date:
    if raw:
        return date.fromisoformat(raw)

    return (utc_now() - timedelta(days=1)).date()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_metrics(metric_date: date) -> List[Dict[str, Any]]:
    response = (
        supabase.table("ml_daily_metrics")
        .select(
            "user_id, concept_decay_score, engagement_velocity, "
            "topic_struggle_index, metric_date, computed_at"
        )
        .eq("metric_date", metric_date.isoformat())
        .execute()
    )

    data = response.data or []
    return data if isinstance(data, list) else []


def fetch_admin_users() -> List[Dict[str, Any]]:
    response = (
        supabase.table("users")
        .select("id, email, full_name, role")
        .eq("role", "admin")
        .execute()
    )

    data = response.data or []
    return data if isinstance(data, list) else []


def classify_health(avg_engagement: float, avg_struggle: float, avg_decay: float) -> str:
    if avg_struggle >= 0.65 or avg_decay >= 0.70:
        return "high_attention_needed"

    if avg_engagement >= 0.60 and avg_struggle <= 0.35:
        return "healthy"

    return "mixed"


def generate_daily_briefing(metric_date: date, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not metrics:
        return {
            "briefing": (
                f"LearNova Daily Insight — {metric_date.isoformat()}\n"
                "- No ML daily metrics were found for this date.\n"
                "- Run the ML pipeline first or check whether students had activity.\n"
                "- No admin action is required yet."
            ),
            "validation_passed": True,
            "health": "no_data",
            "summary": {
                "students_count": 0,
                "avg_engagement_velocity": 0.0,
                "avg_topic_struggle_index": 0.0,
                "avg_concept_decay_score": 0.0,
            },
        }

    engagement_values = [safe_float(row.get("engagement_velocity")) for row in metrics]
    struggle_values = [safe_float(row.get("topic_struggle_index")) for row in metrics]
    decay_values = [safe_float(row.get("concept_decay_score")) for row in metrics]

    avg_engagement = mean(engagement_values) if engagement_values else 0.0
    avg_struggle = mean(struggle_values) if struggle_values else 0.0
    avg_decay = mean(decay_values) if decay_values else 0.0

    high_struggle_count = sum(1 for value in struggle_values if value >= 0.65)
    high_decay_count = sum(1 for value in decay_values if value >= 0.70)
    low_engagement_count = sum(1 for value in engagement_values if value <= 0.25)

    health = classify_health(
        avg_engagement=avg_engagement,
        avg_struggle=avg_struggle,
        avg_decay=avg_decay,
    )

    briefing = (
        f"LearNova Daily Insight — {metric_date.isoformat()}\n"
        f"- Engagement: average engagement velocity is {avg_engagement:.2f}; "
        f"{low_engagement_count} student(s) had low engagement.\n"
        f"- Struggle: average topic struggle index is {avg_struggle:.2f}; "
        f"{high_struggle_count} student(s) show high struggle.\n"
        f"- Decay: average concept decay score is {avg_decay:.2f}; "
        f"{high_decay_count} student(s) may need review or intervention."
    )

    validation_passed = bool(briefing and "- Engagement:" in briefing and "- Struggle:" in briefing)

    return {
        "briefing": briefing,
        "validation_passed": validation_passed,
        "health": health,
        "summary": {
            "students_count": len(metrics),
            "avg_engagement_velocity": round(avg_engagement, 4),
            "avg_topic_struggle_index": round(avg_struggle, 4),
            "avg_concept_decay_score": round(avg_decay, 4),
            "high_struggle_count": high_struggle_count,
            "high_decay_count": high_decay_count,
            "low_engagement_count": low_engagement_count,
        },
    }


def save_admin_notifications(metric_date: date, result: Dict[str, Any]) -> Dict[str, Any]:
    admins = fetch_admin_users()

    if not admins:
        return {
            "ok": True,
            "notifications_inserted": 0,
            "reason": "No admin users found.",
        }

    rows = []

    for admin in admins:
        rows.append(
            {
                "user_id": admin["id"],
                "title": f"LearNova Daily Insight — {metric_date.isoformat()}",
                "body": result["briefing"],
                "notification_type": "general",
                "is_read": False,
                "metadata": {
                    "source": "daily_insight_generator_reviewed",
                    "metric_date": metric_date.isoformat(),
                    "validation_passed": result.get("validation_passed"),
                    "health": result.get("health"),
                    "summary": result.get("summary"),
                    "generated_at": utc_now().isoformat(),
                },
            }
        )

    response = supabase.table("in_app_notifications").insert(rows).execute()

    return {
        "ok": True,
        "notifications_inserted": len(response.data or rows),
    }


def generate_and_validate_daily_briefing(metric_date: Optional[date] = None, save: bool = True) -> Dict[str, Any]:
    metric_date = metric_date or parse_metric_date(None)
    metrics = fetch_metrics(metric_date)
    result = generate_daily_briefing(metric_date, metrics)

    save_result = None

    if save:
        save_result = save_admin_notifications(metric_date, result)

    return {
        "ok": True,
        "metric_date": metric_date.isoformat(),
        "result": result,
        "save_result": save_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Metric date in YYYY-MM-DD. Defaults to yesterday UTC.")
    parser.add_argument("--no-save", action="store_true", help="Generate but do not insert admin notifications.")
    args = parser.parse_args()

    metric_date = parse_metric_date(args.date)
    result = generate_and_validate_daily_briefing(metric_date=metric_date, save=not args.no_save)

    print(result)


if __name__ == "__main__":
    main()
'@

Write-Host "Schema-aligned Edits files written successfully."