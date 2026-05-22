from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional


@dataclass(frozen=True)
class QuizAttempt:
    user_id: str
    topic_id: str
    score: float  
    created_at: datetime
    quiz_type: str = "quiz"  


@dataclass(frozen=True)
class ConceptDecayResult:
    user_id: str
    topic_id: str
    first_score: float
    latest_score: float
    days_between: float
    concept_decay_per_day: float
    interpretation: str
    measurable: bool


def _validate_score(score: float, field_name: str = "score") -> float:
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{field_name} must be normalized between 0.0 and 1.0.")
    return float(score)


def calculate_concept_decay(
    first_score: float,
    latest_score: float,
    days_between: float,
    *,
    minimum_days: float = 1.0,
) -> float:
    first = _validate_score(first_score, "first_score")
    latest = _validate_score(latest_score, "latest_score")

    if days_between < 0:
        raise ValueError("days_between cannot be negative.")

    safe_days = max(float(days_between), minimum_days)
    return round((first - latest) / safe_days, 6)


def calculate_concept_decay_from_attempts(
    attempts: Iterable[QuizAttempt],
    *,
    minimum_days: float = 1.0,
) -> Optional[ConceptDecayResult]:
    ordered_attempts = sorted(attempts, key=lambda item: item.created_at)
    if len(ordered_attempts) < 2:
        return None

    first_attempt = ordered_attempts[0]
    latest_attempt = ordered_attempts[-1]  # always use the most recent follow-up/quiz

    if first_attempt.user_id != latest_attempt.user_id:
        raise ValueError("All attempts must belong to the same user.")
    if first_attempt.topic_id != latest_attempt.topic_id:
        raise ValueError("All attempts must belong to the same topic.")

    raw_days = (latest_attempt.created_at - first_attempt.created_at).total_seconds() / 86_400
    decay = calculate_concept_decay(
        first_attempt.score,
        latest_attempt.score,
        raw_days,
        minimum_days=minimum_days,
    )

    if decay > 0:
        interpretation = "decay_detected"
    elif decay < 0:
        interpretation = "improvement_detected"
    else:
        interpretation = "stable"

    return ConceptDecayResult(
        user_id=first_attempt.user_id,
        topic_id=first_attempt.topic_id,
        first_score=first_attempt.score,
        latest_score=latest_attempt.score,
        days_between=round(max(raw_days, minimum_days), 4),
        concept_decay_per_day=decay,
        interpretation=interpretation,
        measurable=True,
    )


def calculate_ebbinghaus_retention(
    initial_score: float,
    days_elapsed: float,
    decay_constant: float = 0.1,
) -> float:
    initial = _validate_score(initial_score, "initial_score")
    if days_elapsed < 0:
        raise ValueError("days_elapsed cannot be negative.")
    if decay_constant < 0:
        raise ValueError("decay_constant cannot be negative.")

    retention = initial * math.exp(-decay_constant * days_elapsed)
    return max(0.0, min(1.0, round(retention, 4)))


if __name__ == "__main__":
    sample_attempts = [
        QuizAttempt("u1", "sql_joins", 0.80, datetime(2026, 5, 1, 10, 0)),
        QuizAttempt("u1", "sql_joins", 0.92, datetime(2026, 5, 4, 10, 0)),
    ]

    result = calculate_concept_decay_from_attempts(sample_attempts)
    print(result)
    print("Advanced retention estimate:", calculate_ebbinghaus_retention(0.92, 7))
