from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from math import exp
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple

from supabase import Client, create_client

UserTopicKey = Tuple[str, str]

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
LOOKBACK_DAYS = int(os.environ.get("ANALYTICS_LOOKBACK_DAYS", "30"))
PASSING_SCORE = float(os.environ.get("ANALYTICS_PASSING_SCORE", "0.60"))


def require_env() -> None:
    """Fail fast if production credentials are not configured."""
    missing = [
        name
        for name, value in {
            "SUPABASE_URL": SUPABASE_URL,
            "SUPABASE_SERVICE_ROLE_KEY": SUPABASE_KEY,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def get_supabase_client() -> Client:
    require_env()
    return create_client(SUPABASE_URL, SUPABASE_KEY)  # type: ignore[arg-type]


def parse_datetime(value: Any) -> datetime:
    """Parse Supabase/PostgreSQL timestamps safely."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def average(values: Iterable[float], default: float = 0.0) -> float:
    values_list = list(values)
    if not values_list:
        return default
    return sum(values_list) / len(values_list)


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))

def calculate_concept_decay_from_quizzes(quiz_rows: List[Dict[str, Any]]) -> Optional[float]:
    if len(quiz_rows) < 2:
        return None

    ordered = sorted(quiz_rows, key=lambda row: parse_datetime(row.get("created_at")))
    first = ordered[0]
    latest = ordered[-1]

    first_score = clamp_probability(safe_float(first.get("score")))
    latest_score = clamp_probability(safe_float(latest.get("score")))
    first_at = parse_datetime(first.get("created_at"))
    latest_at = parse_datetime(latest.get("created_at"))

    days_between = (latest_at - first_at).total_seconds() / 86_400
    safe_days = max(days_between, 1.0)  # avoids divide-by-zero and noisy same-day infinity

    return round((first_score - latest_score) / safe_days, 6)


def calculate_engagement_velocity_7d(engagement_rows: List[Dict[str, Any]]) -> float:
    minutes_by_day: DefaultDict[date, float] = defaultdict(float)
    for row in engagement_rows:
        created_day = parse_datetime(row.get("created_at")).date()
        minutes_by_day[created_day] += safe_float(row.get("duration_seconds")) / 60.0

    if not minutes_by_day:
        return 0.0

    recent_days = sorted(minutes_by_day.keys())[-7:]
    values = [minutes_by_day[day] for day in recent_days]
    return round(sum(values) / len(values), 2)


def calculate_engagement_ema(engagement_rows: List[Dict[str, Any]], alpha: float = 0.3) -> float:
    minutes_by_day: DefaultDict[date, float] = defaultdict(float)
    for row in engagement_rows:
        created_day = parse_datetime(row.get("created_at")).date()
        minutes_by_day[created_day] += safe_float(row.get("duration_seconds")) / 60.0

    ordered_minutes = [minutes_by_day[day] for day in sorted(minutes_by_day.keys())]
    if not ordered_minutes:
        return 0.0

    ema = ordered_minutes[0]
    for minutes in ordered_minutes[1:]:
        ema = (minutes * alpha) + (ema * (1.0 - alpha))
    return round(ema, 2)


def calculate_retention_estimate(quiz_rows: List[Dict[str, Any]], decay_constant: float = 0.1) -> float:
    if not quiz_rows:
        return 0.0

    latest = max(quiz_rows, key=lambda row: parse_datetime(row.get("created_at")))
    latest_score = clamp_probability(safe_float(latest.get("score")))
    latest_at = parse_datetime(latest.get("created_at"))
    days_since_latest = max((datetime.now(timezone.utc) - latest_at).total_seconds() / 86_400, 0.0)

    retention = latest_score * exp(-decay_constant * days_since_latest)
    return round(clamp_probability(retention), 4)


def calculate_negative_sentiment_rate(sentiment_rows: List[Dict[str, Any]]) -> float:
    sentiment_scores = [safe_float(row.get("sentiment_score")) for row in sentiment_rows if row.get("sentiment_score") is not None]
    if not sentiment_scores:
        return 0.0
    negative_count = sum(1 for score in sentiment_scores if score < 0)
    return round(negative_count / len(sentiment_scores), 6)


def calculate_topic_struggle_index(
    quiz_rows: List[Dict[str, Any]],
    sentiment_rows: List[Dict[str, Any]],
) -> Optional[float]:
    if not quiz_rows:
        return None

    attempt_count = len(quiz_rows)
    avg_score = average([clamp_probability(safe_float(row.get("score"))) for row in quiz_rows], default=1.0)
    negative_rate = calculate_negative_sentiment_rate(sentiment_rows)

    return round(attempt_count * (1.0 - avg_score) * (1.0 + negative_rate), 6)


def update_struggle_probability(prior_probability: float, evidence_signals: List[str]) -> float:
    likelihood_ratios = {
        "failed_quiz": 2.5,
        "multiple_attempts": 1.8,
        "negative_sentiment": 3.0,
        "low_completion_rate": 1.6,
        "passed_quiz": 0.2,
        "positive_sentiment": 0.6,
        "high_completion_rate": 0.5,
    }

    prior = min(max(prior_probability, 0.001), 0.999)
    odds = prior / (1.0 - prior)

    for signal in evidence_signals:
        odds *= likelihood_ratios.get(signal, 1.0)

    posterior = odds / (1.0 + odds)
    return round(clamp_probability(posterior), 4)


def build_evidence_signals(
    engagement_rows: List[Dict[str, Any]],
    quiz_rows: List[Dict[str, Any]],
    sentiment_rows: List[Dict[str, Any]],
) -> List[str]:
    evidence: List[str] = []

    scores = [clamp_probability(safe_float(row.get("score"))) for row in quiz_rows]
    if scores:
        latest_quiz = max(quiz_rows, key=lambda row: parse_datetime(row.get("created_at")))
        latest_score = clamp_probability(safe_float(latest_quiz.get("score")))
        if latest_score < PASSING_SCORE:
            evidence.append("failed_quiz")
        else:
            evidence.append("passed_quiz")

    if len(quiz_rows) >= 2:
        evidence.append("multiple_attempts")

    sentiment_scores = [safe_float(row.get("sentiment_score")) for row in sentiment_rows if row.get("sentiment_score") is not None]
    if sentiment_scores:
        avg_sentiment = average(sentiment_scores)
        if calculate_negative_sentiment_rate(sentiment_rows) >= 0.30:
            evidence.append("negative_sentiment")
        elif avg_sentiment > 0.20:
            evidence.append("positive_sentiment")

    completion_values = [safe_float(row.get("completion_percentage"), 100.0) for row in engagement_rows]
    if completion_values:
        avg_completion = average(completion_values, default=100.0)
        if avg_completion < 50:
            evidence.append("low_completion_rate")
        elif avg_completion >= 80:
            evidence.append("high_completion_rate")

    return evidence

def fetch_table(client: Client, table_name: str, select_clause: str = "*") -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()

    query = client.table(table_name).select(select_clause)
    if table_name in {"content_engagement_logs", "mitchy_interaction_logs"}:
        query = query.gte("created_at", since)

    response = query.execute()
    return response.data or []


def fetch_raw_data(client: Client) -> Dict[str, List[Dict[str, Any]]]:
    print("Fetching raw analytics data from Supabase...")
    return {
        "engagement": fetch_table(client, "content_engagement_logs"),
        "quizzes": fetch_table(client, "quiz_attempts"),
        "sentiment": fetch_table(client, "mitchy_interaction_logs"),
    }


def group_by_user_topic(rows: Iterable[Dict[str, Any]]) -> Dict[UserTopicKey, List[Dict[str, Any]]]:
    grouped: DefaultDict[UserTopicKey, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        user_id = row.get("user_id")
        topic_id = row.get("topic_id")
        if not user_id or not topic_id:
            continue
        grouped[(str(user_id), str(topic_id))].append(row)
    return dict(grouped)


def process_metrics(raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    engagement_by_key = group_by_user_topic(raw_data.get("engagement", []))
    quizzes_by_key = group_by_user_topic(raw_data.get("quizzes", []))
    sentiment_by_key = group_by_user_topic(raw_data.get("sentiment", []))

    all_keys = sorted(set(engagement_by_key) | set(quizzes_by_key) | set(sentiment_by_key))
    today = date.today().isoformat()
    calculated_at = datetime.now(timezone.utc).isoformat()

    payload: List[Dict[str, Any]] = []
    for user_id, topic_id in all_keys:
        engagement_rows = engagement_by_key.get((user_id, topic_id), [])
        quiz_rows = quizzes_by_key.get((user_id, topic_id), [])
        sentiment_rows = sentiment_by_key.get((user_id, topic_id), [])

        concept_decay_rate = calculate_concept_decay_from_quizzes(quiz_rows)
        engagement_velocity_7d = calculate_engagement_velocity_7d(engagement_rows)
        engagement_ema = calculate_engagement_ema(engagement_rows)
        retention_estimate = calculate_retention_estimate(quiz_rows)
        topic_struggle_index = calculate_topic_struggle_index(quiz_rows, sentiment_rows)

        evidence = build_evidence_signals(engagement_rows, quiz_rows, sentiment_rows)
        struggle_probability = update_struggle_probability(0.30, evidence)

        payload.append(
            {
                "snapshot_date": today,
                "user_id": user_id,
                "topic_id": topic_id,
                "concept_decay_rate": concept_decay_rate,
                "engagement_velocity_7d": engagement_velocity_7d,
                "topic_struggle_index": topic_struggle_index,
                "engagement_ema": engagement_ema,
                "retention_estimate": retention_estimate,
                "struggle_probability": struggle_probability,
                "calculated_at": calculated_at,
            }
        )

    return payload


def upsert_metrics(client: Client, metrics_payload: List[Dict[str, Any]]) -> None:
    if not metrics_payload:
        print("No metrics to upsert.")
        return

    print(f"Upserting {len(metrics_payload)} daily metric rows into ml_aggregated_metrics...")
    client.table("ml_aggregated_metrics").upsert(
        metrics_payload,
        on_conflict="snapshot_date,user_id,topic_id",
    ).execute()
    print("Metrics upsert completed.")


def run_pipeline() -> None:
    print("--- Starting LearNova Analytics Orchestrator ---")
    client = get_supabase_client()
    raw_data = fetch_raw_data(client)
    metrics_payload = process_metrics(raw_data)
    upsert_metrics(client, metrics_payload)
    print("--- Analytics pipeline finished successfully ---")


if __name__ == "__main__":
    run_pipeline()
