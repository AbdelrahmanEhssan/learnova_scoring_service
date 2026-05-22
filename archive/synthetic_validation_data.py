from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

SEED = 65
random.seed(SEED)

OUTPUT_DIR = Path(__file__).resolve().parent

TOPICS = [
    ("sf_python_loops", "Python Loops"),
    ("sf_sql_joins", "SQL Joins"),
    ("sf_statistics_mean_variance", "Mean & Variance"),
    ("sf_data_cleaning", "Data Cleaning"),
    ("sf_visualization_basics", "Visualization Basics"),
]

CRISIS_TOPIC_ID = "sf_python_loops"
CRISIS_TOPIC_NAME = "Python Loops"
CRISIS_TARGET_STUDENT_ID = "u_017"

def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))

def round3(value: float) -> float:
    return round(value, 3)

def make_students(count: int = 50) -> List[str]:
    return [f"u_{i:03d}" for i in range(1, count + 1)]

def make_momentum(start: date, healthy: bool) -> List[Dict[str, object]]:
    rows = []
    for offset in range(14):
        current = start + timedelta(days=offset)
        if healthy:
            velocity = 0.62 + random.uniform(-0.04, 0.05)
        else:
            # A downward slope makes the crisis visible in the line chart.
            velocity = 0.65 - (offset * 0.025) + random.uniform(-0.025, 0.025)
        rows.append({
            "date": current.isoformat(),
            "velocity": round3(clamp(velocity, 0.0, 1.0)),
        })
    return rows

def make_struggle_map(healthy: bool) -> List[Dict[str, object]]:
    rows = []
    for topic_id, name in TOPICS:
        if healthy:
            struggle = random.uniform(0.16, 0.34)
        elif topic_id == CRISIS_TOPIC_ID:
            struggle = random.uniform(0.86, 0.94)
        else:
            struggle = random.uniform(0.25, 0.48)
        rows.append({
            "topic_id": topic_id,
            "name": name,
            "struggle_index": round3(struggle),
        })
    rows.sort(key=lambda row: row["struggle_index"], reverse=True)
    return rows

def make_student_topic_rows(students: List[str], healthy: bool) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    for user_id in students:
        for topic_id, name in TOPICS:
            if healthy:
                score = random.uniform(0.72, 0.96)
                sentiment = random.uniform(0.05, 0.72)
            else:
                if topic_id == CRISIS_TOPIC_ID:
                    score = random.uniform(0.32, 0.58)
                    sentiment = random.uniform(-0.82, -0.18)
                else:
                    score = random.uniform(0.62, 0.93)
                    sentiment = random.uniform(-0.10, 0.62)

            if not healthy and user_id == CRISIS_TARGET_STUDENT_ID and topic_id == CRISIS_TOPIC_ID:
                score = 0.24
                sentiment = -0.91

            rows.append({
                "user_id": user_id,
                "topic_id": topic_id,
                "topic_name": name,
                "latest_score": round3(score),
                "sentiment": round3(sentiment),
            })

    return rows

def make_risk_radar(student_topic_rows: List[Dict[str, object]], healthy: bool) -> List[Dict[str, object]]:
    # One point per student, using the student's lowest score and lowest sentiment.
    by_user: Dict[str, List[Dict[str, object]]] = {}
    for row in student_topic_rows:
        by_user.setdefault(row["user_id"], []).append(row)

    radar = []
    for user_id, rows in by_user.items():
        lowest_score = min(float(r["latest_score"]) for r in rows)
        lowest_sentiment = min(float(r["sentiment"]) for r in rows)
        radar.append({
            "user_id": user_id,
            "sentiment": round3(lowest_sentiment),
            "score": round3(lowest_score),
        })

    radar.sort(key=lambda row: (row["score"], row["sentiment"]))
    return radar

def make_drilldown(student_topic_rows: List[Dict[str, object]], topic_id: str) -> List[Dict[str, object]]:
    rows = [
        {
            "user_id": row["user_id"],
            "latest_score": row["latest_score"],
            "sentiment": row["sentiment"],
        }
        for row in student_topic_rows
        if row["topic_id"] == topic_id and float(row["latest_score"]) < 0.60
    ]
    rows.sort(key=lambda row: (row["latest_score"], row["sentiment"]))
    return rows

def make_dashboard_payload(healthy: bool) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    students = make_students(50)
    student_topic_rows = make_student_topic_rows(students, healthy=healthy)
    struggle_map = make_struggle_map(healthy=healthy)
    risk_radar = make_risk_radar(student_topic_rows, healthy=healthy)
    momentum = make_momentum(date(2026, 2, 1), healthy=healthy)

    top_topic = struggle_map[0]
    drilldown = make_drilldown(student_topic_rows, top_topic["topic_id"])

    if healthy:
        expected_topic_id = None
        expected_student_id = None
        briefing = [
            "No system-wide crisis is visible today; all listed topics remain below the high-struggle threshold.",
            "Class momentum is stable, with engagement velocity remaining within the healthy range.",
            "No single student requires immediate escalation based on the current score and sentiment signals."
        ]
    else:
        expected_topic_id = CRISIS_TOPIC_ID
        expected_student_id = CRISIS_TARGET_STUDENT_ID
        briefing = [
            "Python Loops is the main crisis topic, showing the highest struggle index and widespread low scores.",
            "Student u_017 is the most at-risk learner because they have the lowest score and most negative sentiment.",
            "Class momentum is declining, so the instructor should prioritize a targeted Python Loops intervention."
        ]

    payload = {
        "scenario": "healthy_class" if healthy else "crisis",
        "date": "2026-02-14",
        "expected_answers": {
            "crisis_topic_id": expected_topic_id,
            "target_student_id": expected_student_id,
        },
        "charts": {
            "risk_radar": risk_radar,
            "struggle_map": struggle_map,
            "momentum": momentum,
        },
        "drilldowns": {
            str(top_topic["topic_id"]): drilldown,
        },
        "daily_briefing": briefing,
    }

    return payload, student_topic_rows

def write_json(filename: str, payload: Dict[str, object]) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def write_csv(filename: str, rows: List[Dict[str, object]]) -> None:
    path = OUTPUT_DIR / filename
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["user_id", "topic_id", "topic_name", "latest_score", "sentiment"]
        )
        writer.writeheader()
        writer.writerows(rows)

def main() -> None:
    crisis_payload, crisis_rows = make_dashboard_payload(healthy=False)
    healthy_payload, healthy_rows = make_dashboard_payload(healthy=True)

    write_json("crisis_dashboard_data.json", crisis_payload)
    write_json("healthy_dashboard_data.json", healthy_payload)
    write_csv("baseline_crisis_spreadsheet.csv", crisis_rows)
    write_csv("baseline_healthy_spreadsheet.csv", healthy_rows)

    print("Synthetic validation data generated successfully.")
    print("Crisis expected topic:", crisis_payload["expected_answers"]["crisis_topic_id"])
    print("Crisis expected student:", crisis_payload["expected_answers"]["target_student_id"])

if __name__ == "__main__":
    main()
