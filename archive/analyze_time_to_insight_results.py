from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

SUCCESS_TIME_SECONDS = 10.0
TARGET_SUCCESS_RATE = 0.95

def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}

def analyze(path: Path) -> Dict[str, object]:
    rows: List[Dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    evaluated = [
        row for row in rows
        if row.get("condition", "").strip().lower() == "learnnova_dashboard"
        and row.get("scenario", "").strip().lower() == "crisis"
        and row.get("time_seconds", "").strip()
    ]

    if not evaluated:
        return {
            "participants_evaluated": 0,
            "success_count": 0,
            "success_rate": 0.0,
            "metric_met": False,
            "message": "No completed LearnNova crisis rows were found."
        }

    success_count = 0
    times = []

    for row in evaluated:
        time_seconds = float(row["time_seconds"])
        times.append(time_seconds)

        topic_correct = parse_bool(row.get("crisis_topic_correct", "false"))
        student_correct = parse_bool(row.get("target_student_correct", "false"))
        under_time = time_seconds < SUCCESS_TIME_SECONDS

        if topic_correct and student_correct and under_time:
            success_count += 1

    success_rate = success_count / len(evaluated)

    return {
        "participants_evaluated": len(evaluated),
        "success_count": success_count,
        "success_rate": round(success_rate, 4),
        "average_time_seconds": round(sum(times) / len(times), 2),
        "fastest_time_seconds": round(min(times), 2),
        "slowest_time_seconds": round(max(times), 2),
        "metric_met": success_rate >= TARGET_SUCCESS_RATE,
    }

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_time_to_insight_results.py participant_results_template.csv")
        raise SystemExit(1)

    result = analyze(Path(sys.argv[1]))
    for key, value in result.items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()
