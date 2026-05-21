from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal


TrendState = Literal["stable", "watch", "take_break"]


@dataclass
class TrendResult:
    history: List[float]
    rolling_average: float
    current_sentiment: float
    trend_state: TrendState
    suggested_action: str
    reason: str


def validate_scores(scores: List[float]) -> None:
    if not isinstance(scores, list):
        raise TypeError("history must be a list of sentiment scores.")

    if len(scores) == 0:
        raise ValueError("history cannot be empty.")

    for score in scores:
        if not isinstance(score, (int, float)):
            raise TypeError("All sentiment scores must be numeric.")
        if score < -1.0 or score > 1.0:
            raise ValueError("Sentiment scores must be between -1.0 and 1.0.")


def get_last_five_scores(history: List[float]) -> List[float]:
    """
    Returns the last 5 sentiment scores.
    If fewer than 5 exist, uses all available scores.
    """
    return history[-5:]


def calculate_rolling_average(history: List[float]) -> float:
    """
    Task 3.2.1.2 formula:
    Rolling_Avg = Sum(Last_5_Scores) / 5

    To avoid unfairly shrinking shorter histories during early sessions,
    this implementation divides by the actual number of available scores
    if fewer than 5 exist.
    """
    validate_scores(history)
    last_five = get_last_five_scores(history)
    return sum(last_five) / len(last_five)


def get_trend_state(history: List[float]) -> TrendResult:
    """
    Task 3.2 logic:
    IF Rolling_Avg < -0.5 AND Current_Sentiment < -0.5
    THEN suggested_action = 'take_break'
    """
    validate_scores(history)

    last_five = get_last_five_scores(history)
    rolling_avg = calculate_rolling_average(last_five)
    current_sentiment = last_five[-1]

    if rolling_avg < -0.5 and current_sentiment < -0.5:
        return TrendResult(
            history=last_five,
            rolling_average=round(rolling_avg, 4),
            current_sentiment=round(current_sentiment, 4),
            trend_state="take_break",
            suggested_action="take_break",
            reason="Sustained negative emotional trend detected across recent messages.",
        )

    if rolling_avg < -0.3 or current_sentiment < -0.5:
        return TrendResult(
            history=last_five,
            rolling_average=round(rolling_avg, 4),
            current_sentiment=round(current_sentiment, 4),
            trend_state="watch",
            suggested_action="none",
            reason="Some negative sentiment detected, but escalation threshold not met.",
        )

    return TrendResult(
        history=last_five,
        rolling_average=round(rolling_avg, 4),
        current_sentiment=round(current_sentiment, 4),
        trend_state="stable",
        suggested_action="none",
        reason="No sustained negative trend detected.",
    )


if __name__ == "__main__":
    test_cases = [
        [-0.2, -0.4, -0.6, -0.8, -0.9],
        [0.1, -0.1, -0.2, -0.3, -0.4],
        [-0.1, -0.2, -0.1, -0.2, -0.7],
        [0.2, 0.1, 0.0, -0.1, 0.1],
    ]

    for i, case in enumerate(test_cases, start=1):
        result = get_trend_state(case)
        print(f"--- Test Case {i} ---")
        print(f"History: {result.history}")
        print(f"Rolling Average: {result.rolling_average}")
        print(f"Current Sentiment: {result.current_sentiment}")
        print(f"Trend State: {result.trend_state}")
        print(f"Suggested Action: {result.suggested_action}")
        print(f"Reason: {result.reason}")
        print()