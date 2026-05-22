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
                f"LearNova Daily Insight â€” {metric_date.isoformat()}\n"
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
        f"LearNova Daily Insight â€” {metric_date.isoformat()}\n"
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
                "title": f"LearNova Daily Insight â€” {metric_date.isoformat()}",
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
