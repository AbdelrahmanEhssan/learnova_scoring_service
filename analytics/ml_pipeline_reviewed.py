from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, Iterable, List, Optional


"""
Schema-aligned LearNova daily ML metrics pipeline.

Purpose:
- Keep this file as the Supabase orchestration layer.
- Fetch data from existing Supabase tables.
- Adapt rows into the shapes expected by analytics helper modules.
- Call stronger analytics modules when available.
- Fall back to the old safe internal calculations if any module fails.
- Write final values only to columns that exist in ml_daily_metrics.

Writes to existing table:
- ml_daily_metrics

Reads from existing tables:
- users
- student_profiles
- content_engagement_logs
- student_module_attempts
- student_challenge_attempts
- student_level_attempts
- student_sentiment_history
- chat_sessions
- chat_messages

Important:
ml_daily_metrics currently has no metadata/jsonb column, so this script does NOT
upsert adapter/debug metadata into ml_daily_metrics. It only returns/logs adapter
details from run_pipeline().
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

from analytics.adapters import (
    adapt_attempt_rows_for_concept_decay,
    adapt_bayesian_profile_update_for_supabase,
    adapt_engagement_logs_for_drift,
    adapt_rows_for_topic_struggle,
    adapt_student_profile_for_bayesian,
    clamp,
    extract_successful_rescue_signal,
    safe_float,
)


def _optional_callable(module_name: str, function_names: List[str]) -> Optional[Callable[..., Any]]:
    """
    Imports an optional analytics module/function safely.

    This keeps the cron backwards-compatible. If an edited analytics module has
    a different function name or import-time issue, the pipeline continues using
    the old internal fallback calculations instead of crashing.
    """

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        print(f"[analytics] optional module unavailable: {module_name}: {exc}")
        return None

    for function_name in function_names:
        candidate = getattr(module, function_name, None)
        if callable(candidate):
            return candidate

    print(
        f"[analytics] optional module loaded but no expected callable found: "
        f"{module_name}; tried {function_names}"
    )
    return None


detect_drift = _optional_callable(
    "analytics.detect_drift2",
    [
        "detect_drift",
        "detect_learning_style_drift",
        "run_drift_detection",
    ],
)

process_rescue_intervention = _optional_callable(
    "analytics.bayesian_engine3",
    [
        "process_rescue_intervention",
        "update_bayesian_profile",
        "bayesian_update",
        "update_learning_style_bayesian",
    ],
)

calculate_concept_decay_score = _optional_callable(
    "analytics.concept_decay_edited",
    [
        "calculate_concept_decay_score",
        "compute_concept_decay_score",
        "calculate_concept_decay",
        "compute_concept_decay",
    ],
)

calculate_topic_struggle_index = _optional_callable(
    "analytics.topic_struggle_index_edited",
    [
        "calculate_topic_struggle_index",
        "compute_topic_struggle_index",
        "calculate_struggle_index",
        "compute_struggle_index",
    ],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_metric_date(raw: Optional[str]) -> date:
    if raw:
        return date.fromisoformat(raw)

    env_value = os.getenv("METRIC_DATE")
    if env_value:
        return date.fromisoformat(env_value)

    # Cron normally runs after midnight UTC, so compute yesterday by default.
    return (utc_now() - timedelta(days=1)).date()


def day_window(metric_date: date) -> tuple[str, str]:
    start = datetime.combine(metric_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    return start.isoformat(), end.isoformat()


def _apply_filters(query: Any, filters: Optional[List[tuple[str, str, Any]]]) -> Any:
    for operation, column, value in filters or []:
        if operation == "eq":
            query = query.eq(column, value)
        elif operation == "gte":
            query = query.gte(column, value)
        elif operation == "gt":
            query = query.gt(column, value)
        elif operation == "lt":
            query = query.lt(column, value)
        elif operation == "lte":
            query = query.lte(column, value)
        elif operation == "neq":
            query = query.neq(column, value)
        else:
            raise ValueError(f"Unsupported Supabase filter operation: {operation}")

    return query


def fetch_all(
    table: str,
    select: str = "*",
    filters: Optional[List[tuple[str, str, Any]]] = None,
    page_size: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Fetches all rows with simple pagination.

    Supabase often returns limited pages by default, so this prevents silent
    truncation for larger tables.
    """

    rows: List[Dict[str, Any]] = []
    start = 0

    while True:
        end = start + page_size - 1
        query = supabase.table(table).select(select)
        query = _apply_filters(query, filters)
        response = query.range(start, end).execute()

        data = response.data or []
        if not isinstance(data, list):
            break

        rows.extend(data)

        if len(data) < page_size:
            break

        start += page_size

    return rows


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

    # Scores in LearNova attempts are usually 0-100.
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


def compute_topic_struggle_index_fallback(
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


def compute_concept_decay_score_fallback(
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


def compute_drift_with_adapter(
    engagement_rows: List[Dict[str, Any]],
    profile_by_user: Dict[str, Dict[str, Any]],
    metric_date: date,
) -> Dict[str, Dict[str, Any]]:
    """
    Runs detect_drift2.py through adapter mapping.

    This currently returns results for logging/inspection. Since ml_daily_metrics
    has no metadata column, drift details are not written to that table.
    """

    if detect_drift is None:
        return {}

    try:
        adapted_logs = adapt_engagement_logs_for_drift(engagement_rows)

        current_profiles = {
            user_id: adapt_student_profile_for_bayesian(profile)
            for user_id, profile in profile_by_user.items()
        }

        now = datetime.combine(metric_date, time.max, tzinfo=timezone.utc)

        try:
            drift_rows = detect_drift(
                engagement_logs=adapted_logs,
                current_profiles=current_profiles,
                now=now,
            )
        except TypeError:
            try:
                drift_rows = detect_drift(adapted_logs, current_profiles, now)
            except TypeError:
                drift_rows = detect_drift(adapted_logs, current_profiles)

        if isinstance(drift_rows, dict):
            # Accept either {user_id: result} or a single result dict with user_id.
            if "user_id" in drift_rows:
                user_id = str(drift_rows.get("user_id"))
                return {user_id: drift_rows} if user_id else {}

            return {
                str(user_id): result
                for user_id, result in drift_rows.items()
                if user_id and isinstance(result, dict)
            }

        if isinstance(drift_rows, list):
            return {
                str(row.get("user_id")): row
                for row in drift_rows
                if isinstance(row, dict) and row.get("user_id")
            }

        return {}

    except Exception as exc:
        print(f"[analytics] detect_drift adapter failed safely: {exc}")
        return {}


def compute_concept_decay_with_adapter(
    engagement_rows: List[Dict[str, Any]],
    module_attempts: List[Dict[str, Any]],
    challenge_attempts: List[Dict[str, Any]],
    level_attempts: List[Dict[str, Any]],
    sentiments: List[Dict[str, Any]],
) -> float:
    """
    Uses concept_decay_edited.py if available; otherwise falls back to the
    existing internal simplified computation.
    """

    adapted_attempts = adapt_attempt_rows_for_concept_decay(
        module_attempts=module_attempts,
        challenge_attempts=challenge_attempts,
        level_attempts=level_attempts,
    )

    if calculate_concept_decay_score is not None:
        try:
            return clamp(
                calculate_concept_decay_score(
                    attempts=adapted_attempts,
                    engagement_rows=engagement_rows,
                    sentiments=sentiments,
                )
            )
        except TypeError:
            try:
                return clamp(calculate_concept_decay_score(adapted_attempts))
            except Exception as exc:
                print(f"[analytics] concept_decay module fallback triggered: {exc}")
        except Exception as exc:
            print(f"[analytics] concept_decay adapter failed safely: {exc}")

    return compute_concept_decay_score_fallback(
        engagement_rows=engagement_rows,
        progress_like_attempts=module_attempts + challenge_attempts + level_attempts,
        sentiments=sentiments,
    )


def compute_topic_struggle_with_adapter(
    module_attempts: List[Dict[str, Any]],
    challenge_attempts: List[Dict[str, Any]],
    level_attempts: List[Dict[str, Any]],
    sentiments: List[Dict[str, Any]],
) -> float:
    """
    Uses topic_struggle_index_edited.py if available; otherwise falls back to
    the existing internal simplified computation.
    """

    adapted = adapt_rows_for_topic_struggle(
        module_attempts=module_attempts,
        challenge_attempts=challenge_attempts,
        level_attempts=level_attempts,
        sentiment_rows=sentiments,
    )

    if calculate_topic_struggle_index is not None:
        try:
            return clamp(
                calculate_topic_struggle_index(
                    attempts_per_quiz=adapted["attempt_count"],
                    scores=adapted["scores"],
                    sentiment_scores=adapted["sentiment_scores"],
                )
            )
        except TypeError:
            try:
                return clamp(
                    calculate_topic_struggle_index(
                        avg_attempts=adapted["attempt_count"],
                        avg_score=adapted["average_score"] or 0.0,
                        negative_sentiment_rate=adapted["negative_sentiment_rate"],
                    )
                )
            except Exception as exc:
                print(f"[analytics] topic_struggle module fallback triggered: {exc}")
        except Exception as exc:
            print(f"[analytics] topic_struggle adapter failed safely: {exc}")

    return compute_topic_struggle_index_fallback(
        module_attempts=module_attempts,
        challenge_attempts=challenge_attempts,
        level_attempts=level_attempts,
        sentiments=sentiments,
    )


def maybe_update_bayesian_profile(
    user_id: str,
    profile_row: Optional[Dict[str, Any]],
    chat_rows: List[Dict[str, Any]],
    sentiment_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Updates student_profiles Bayesian alpha fields only when there is a reliable
    successful rescue/adaptation signal.

    This is intentionally conservative. If there is no clear evidence, no profile
    update is made.
    """

    if process_rescue_intervention is None:
        return {
            "updated": False,
            "reason": "bayesian_engine3_not_available",
        }

    signal = extract_successful_rescue_signal(
        chat_rows=chat_rows,
        sentiment_rows=sentiment_rows,
    )

    if not signal:
        return {
            "updated": False,
            "reason": "no_valid_rescue_success_signal",
        }

    try:
        bayesian_profile = adapt_student_profile_for_bayesian(profile_row)

        try:
            result = process_rescue_intervention(
                user_profile=bayesian_profile,
                successful_format=signal["successful_format"],
                sentiment_score=safe_float(signal["sentiment_score"]),
            )
        except TypeError:
            result = process_rescue_intervention(
                bayesian_profile,
                signal["successful_format"],
                safe_float(signal["sentiment_score"]),
            )

        if not isinstance(result, dict):
            return {
                "updated": False,
                "reason": "bayesian_engine_returned_non_dict_result",
                "result": str(result),
            }

        updated_profile = result.get("updated_profile") or result.get("profile")

        if not isinstance(updated_profile, dict):
            return {
                "updated": False,
                "reason": "bayesian_engine_returned_no_updated_profile",
                "result": result,
            }

        update_payload = adapt_bayesian_profile_update_for_supabase(updated_profile)

        supabase.table("student_profiles").upsert(
            {
                "user_id": user_id,
                **update_payload,
            },
            on_conflict="user_id",
        ).execute()

        return {
            "updated": True,
            "status": result.get("status"),
            "successful_format": signal["successful_format"],
            "sentiment_score": signal["sentiment_score"],
            "payload": update_payload,
        }

    except Exception as exc:
        print(f"[analytics] bayesian profile update failed safely for {user_id}: {exc}")
        return {
            "updated": False,
            "reason": "exception",
            "error": str(exc),
        }


def run_pipeline(metric_date: Optional[date] = None) -> Dict[str, Any]:
    metric_date = metric_date or parse_metric_date(None)
    start_iso, end_iso = day_window(metric_date)

    users = fetch_all(
        "users",
        "id, email, role",
        filters=[("eq", "role", "student")],
    )

    profiles = fetch_all(
        "student_profiles",
        (
            "user_id, learning_style, "
            "bayesian_alpha_visual, bayesian_alpha_auditory, bayesian_alpha_textual"
        ),
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
        "session_id, role, mitchy_action, sent_at",
        filters=[("gte", "sent_at", start_iso), ("lt", "sent_at", end_iso)],
    )

    chat_rows_by_user: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in messages:
        user_id = session_to_user.get(str(row.get("session_id")))
        if user_id:
            chat_rows_by_user[user_id].append(row)

    profile_by_user = {
        str(row.get("user_id")): row
        for row in profiles
        if row.get("user_id")
    }

    engagement_by_user = group_by_user(engagement)
    module_by_user = group_by_user(module_attempts)
    challenge_by_user = group_by_user(challenge_attempts)
    level_by_user = group_by_user(level_attempts)
    sentiment_by_user = group_by_user(sentiments)

    drift_by_user = compute_drift_with_adapter(
        engagement_rows=engagement,
        profile_by_user=profile_by_user,
        metric_date=metric_date,
    )

    rows_to_upsert: List[Dict[str, Any]] = []
    bayesian_updates: Dict[str, Dict[str, Any]] = {}

    for user in users:
        user_id = str(user["id"])

        user_engagement = engagement_by_user.get(user_id, [])
        user_module = module_by_user.get(user_id, [])
        user_challenge = challenge_by_user.get(user_id, [])
        user_level = level_by_user.get(user_id, [])
        user_sentiment = sentiment_by_user.get(user_id, [])
        user_chat = chat_rows_by_user.get(user_id, [])

        bayesian_update = maybe_update_bayesian_profile(
            user_id=user_id,
            profile_row=profile_by_user.get(user_id),
            chat_rows=user_chat,
            sentiment_rows=user_sentiment,
        )
        bayesian_updates[user_id] = bayesian_update

        row = {
            "user_id": user_id,
            "metric_date": metric_date.isoformat(),
            "concept_decay_score": compute_concept_decay_with_adapter(
                engagement_rows=user_engagement,
                module_attempts=user_module,
                challenge_attempts=user_challenge,
                level_attempts=user_level,
                sentiments=user_sentiment,
            ),
            "engagement_velocity": compute_engagement_velocity(
                engagement_rows=user_engagement,
                chat_rows=user_chat,
            ),
            "topic_struggle_index": compute_topic_struggle_with_adapter(
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

    updated_bayesian_count = sum(
        1
        for update in bayesian_updates.values()
        if update.get("updated") is True
    )

    return {
        "ok": True,
        "metric_date": metric_date.isoformat(),
        "users_processed": len(users),
        "rows_upserted": len(rows_to_upsert),
        "source_counts": {
            "users": len(users),
            "student_profiles": len(profiles),
            "content_engagement_logs": len(engagement),
            "student_module_attempts": len(module_attempts),
            "student_challenge_attempts": len(challenge_attempts),
            "student_level_attempts": len(level_attempts),
            "student_sentiment_history": len(sentiments),
            "chat_sessions": len(sessions),
            "chat_messages": len(messages),
        },
        "adapter_counts": {
            "drift_results": len(drift_by_user),
            "bayesian_profiles_updated": updated_bayesian_count,
        },
        "module_status": {
            "detect_drift2": detect_drift is not None,
            "bayesian_engine3": process_rescue_intervention is not None,
            "concept_decay_edited": calculate_concept_decay_score is not None,
            "topic_struggle_index_edited": calculate_topic_struggle_index is not None,
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
