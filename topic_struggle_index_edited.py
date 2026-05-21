from __future__ import annotations

from typing import Iterable, List


def _validate_probability(value: float, field_name: str) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0.0 and 1.0.")
    return float(value)


def _validate_non_negative(value: float, field_name: str) -> float:
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return float(value)


def calculate_topic_struggle_index(
    avg_attempts: float,
    avg_score: float,
    negative_sentiment_rate: float,
) -> float:
    attempts = _validate_non_negative(avg_attempts, "avg_attempts")
    score = _validate_probability(avg_score, "avg_score")
    sentiment_rate = _validate_probability(negative_sentiment_rate, "negative_sentiment_rate")

    struggle_index = attempts * (1.0 - score) * (1.0 + sentiment_rate)
    return round(struggle_index, 6)


def calculate_negative_sentiment_rate(sentiment_scores: Iterable[float], threshold: float = -0.05) -> float:
    values = list(sentiment_scores)
    if not values:
        return 0.0

    negative_count = sum(1 for score in values if score < threshold)
    return round(negative_count / len(values), 6)


def calculate_average(values: Iterable[float], *, default: float = 0.0) -> float:
    values_list = list(values)
    if not values_list:
        return default
    return sum(values_list) / len(values_list)


def calculate_topic_struggle_index_from_records(
    attempts_per_quiz: Iterable[float],
    scores: Iterable[float],
    sentiment_scores: Iterable[float],
) -> float:
    avg_attempts = calculate_average(attempts_per_quiz, default=0.0)
    avg_score = calculate_average(scores, default=1.0)
    negative_rate = calculate_negative_sentiment_rate(sentiment_scores)
    return calculate_topic_struggle_index(avg_attempts, avg_score, negative_rate)


def update_struggle_probability(
    prior_probability: float,
    evidence_signals: List[str],
) -> float:
    likelihood_ratios = {
        "failed_quiz": 2.5,
        "multiple_attempts": 1.8,
        "negative_sentiment": 3.0,
        "passed_quiz": 0.2,
        "positive_sentiment": 0.6,
        "high_completion_rate": 0.5,
    }

    prior_prob = min(max(float(prior_probability), 0.001), 0.999)
    odds = prior_prob / (1.0 - prior_prob)

    for signal in evidence_signals:
        odds *= likelihood_ratios.get(signal, 1.0)

    posterior_prob = odds / (1.0 + odds)
    return round(posterior_prob, 4)


if __name__ == "__main__":
    print("Required struggle index:", calculate_topic_struggle_index(2.4, 0.62, 0.35))
    print("Advanced Bayesian probability:", update_struggle_probability(0.30, ["failed_quiz", "negative_sentiment"]))
