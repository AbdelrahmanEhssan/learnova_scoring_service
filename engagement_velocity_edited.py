from __future__ import annotations

from typing import Iterable, List


def _validate_minutes(minutes: float) -> float:
    if minutes < 0:
        raise ValueError("Engagement minutes cannot be negative.")
    return float(minutes)


def calculate_engagement_velocity_rolling(
    daily_engagement_minutes: Iterable[float],
    *,
    window_days: int = 7,
) -> float:
    if window_days <= 0:
        raise ValueError("window_days must be positive.")

    values = [_validate_minutes(value) for value in daily_engagement_minutes]
    if not values:
        return 0.0

    recent_values = values[-window_days:]
    return round(sum(recent_values) / len(recent_values), 2)


def calculate_engagement_velocity_series(
    daily_engagement_minutes: Iterable[float],
    *,
    window_days: int = 7,
) -> List[float]:
    values = [_validate_minutes(value) for value in daily_engagement_minutes]
    return [
        calculate_engagement_velocity_rolling(values[: index + 1], window_days=window_days)
        for index in range(len(values))
    ]


def calculate_engagement_ema(
    daily_engagement_minutes: Iterable[float],
    alpha: float = 0.3,
) -> float:
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be greater than 0 and less than or equal to 1.")

    values = [_validate_minutes(value) for value in daily_engagement_minutes]
    if not values:
        return 0.0

    ema = values[0]
    for minutes in values[1:]:
        ema = (minutes * alpha) + (ema * (1.0 - alpha))
    return round(ema, 2)


if __name__ == "__main__":
    activity_history = [10.0, 0.0, 0.0, 5.0, 60.0]
    print("Required rolling velocity:", calculate_engagement_velocity_rolling(activity_history))
    print("Rolling series:", calculate_engagement_velocity_series(activity_history))
    print("Advanced EMA:", calculate_engagement_ema(activity_history))
