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
