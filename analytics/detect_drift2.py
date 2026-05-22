"""
Sprint 5.3: Drift Detection & Confidence Score
LearnNova Personalization Engine

UPDATED V3: Constrained to a strictly 3-dimensional state space (Visual, Auditory, Textual).
Kinesthetic has been removed from tracking arrays and metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from collections import defaultdict


STYLE_ALIASES = {
    "visual": "visual",
    "video": "visual",
    "visual_video": "visual",

    "auditory": "auditory",
    "audio": "auditory",
    "auditory_audio": "auditory",

    "text": "textual",
    "textual": "textual",
    "article": "textual",
    "read": "textual",
    "read_write": "textual",
    "textual_article": "textual",
}

# STRICT 3D STATE SPACE
TRACKED_STYLES = ("visual", "auditory", "textual")


@dataclass
class DriftResult:
    user_id: str
    dominant_style: str
    old_style: Optional[str]
    visual_time_pct: float
    auditory_time_pct: float
    textual_time_pct: float
    days_consistent: int
    raw_confidence: float
    confidence_score: float
    should_nudge: bool
    action: str
    reason: str


def _parse_datetime(value: Any) -> datetime:
    """Parse a timestamp from datetime or ISO string and return timezone-aware UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    else:
        raise ValueError(f"Unsupported created_at value: {value!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_style(value: Any) -> Optional[str]:
    """Map database content_type / selected_slot names to one of the tracked styles."""
    if value is None:
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return STYLE_ALIASES.get(key)


def _normalize_completion_percentage(value: Any) -> float:
    """
    Return completion as 0-100.
    """
    if value is None:
        return 100.0
    completion = float(value)
    if 0 <= completion <= 1:
        completion *= 100
    return max(0.0, min(100.0, completion))


def _safe_duration(value: Any) -> int:
    if value is None:
        return 0
    return max(0, int(value))


def _effective_duration_seconds(
    log: Dict[str, Any],
    min_completion_pct: float,
    downweight_low_completion: bool,
) -> int:
    """Calculate engagement duration after AFK protection."""
    duration = _safe_duration(log.get("duration_seconds"))
    completion = _normalize_completion_percentage(log.get("completion_percentage"))

    if completion < min_completion_pct:
        return 0

    if downweight_low_completion:
        return int(duration * (completion / 100.0))

    return duration


def _style_from_log(log: Dict[str, Any]) -> Optional[str]:
    return _normalize_style(log.get("selected_slot")) or _normalize_style(log.get("content_type"))


def _pct_map(seconds_by_style: Dict[str, int]) -> Dict[str, float]:
    total = sum(seconds_by_style.values())
    if total <= 0:
        return {style: 0.0 for style in TRACKED_STYLES}
    return {style: seconds_by_style.get(style, 0) / total for style in TRACKED_STYLES}


def _count_consistent_days(
    daily_seconds: Dict[datetime.date, Dict[str, int]],
    candidate_style: str,
    min_daily_pct: float = 0.50,
) -> int:
    consistent_days = 0
    for style_seconds in daily_seconds.values():
        pct = _pct_map(style_seconds)
        dominant = max(pct, key=pct.get)
        if dominant == candidate_style and pct[candidate_style] > min_daily_pct:
            consistent_days += 1
    return consistent_days


def calculate_confidence(
    new_style_pct: float,
    days_consistent: int,
    window_days: int = 14,
) -> Tuple[float, float]:
    consistency_factor = min(max(days_consistent, 0), window_days) / float(window_days)
    raw_confidence = max(0.0, (new_style_pct - 0.50) * consistency_factor)
    normalized_confidence = max(0.0, min(1.0, (new_style_pct - 0.50) * 2.0 * consistency_factor))
    return raw_confidence, normalized_confidence


def detect_drift(
    engagement_logs: Iterable[Dict[str, Any]],
    current_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    window_days: int = 14,
    confidence_threshold: float = 0.70,
    min_completion_pct: float = 20.0,
    downweight_low_completion: bool = True,
) -> List[Dict[str, Any]]:
    
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    current_profiles = current_profiles or {}
    cutoff = now - timedelta(days=window_days)

    user_seconds: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    user_daily_seconds: Dict[str, Dict[datetime.date, Dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )

    for log in engagement_logs:
        try:
            created_at = _parse_datetime(log.get("created_at"))
        except Exception:
            continue

        if created_at < cutoff or created_at > now:
            continue

        user_id = str(log.get("user_id", "")).strip()
        if not user_id:
            continue

        style = _style_from_log(log)
        if style not in TRACKED_STYLES:
            continue

        effective_duration = _effective_duration_seconds(
            log,
            min_completion_pct=min_completion_pct,
            downweight_low_completion=downweight_low_completion,
        )

        if effective_duration <= 0:
            continue

        user_seconds[user_id][style] += effective_duration
        user_daily_seconds[user_id][created_at.date()][style] += effective_duration

    results: List[DriftResult] = []

    for user_id, seconds_by_style in user_seconds.items():
        pct = _pct_map(seconds_by_style)
        dominant_style = max(pct, key=pct.get)
        dominant_pct = pct[dominant_style]
        days_consistent = _count_consistent_days(
            user_daily_seconds[user_id],
            dominant_style,
            min_daily_pct=0.50,
        )

        raw_confidence, confidence_score = calculate_confidence(
            dominant_pct,
            days_consistent,
            window_days=window_days,
        )

        old_style = current_profiles.get(user_id, {}).get("current_primary_style")
        should_nudge = (
            pct["visual"] < 0.20
            and pct["textual"] > 0.60
            and confidence_score > confidence_threshold
        )

        if should_nudge:
            action = "flag_for_nudge"
            reason = (
                "Visual usage is below 20%, textual usage is above 60%, "
                "and normalized confidence exceeds the threshold."
            )
        elif dominant_pct <= 0.50:
            action = "no_action"
            reason = "No style exceeded 50% usage, so the signal is weak."
        elif confidence_score <= confidence_threshold:
            action = "observe"
            reason = "A dominant style exists, but consistency/confidence is not strong enough."
        else:
            action = "candidate_shift"
            reason = "High-confidence drift detected, but it does not match the configured nudge rule."

        results.append(
            DriftResult(
                user_id=user_id,
                dominant_style=dominant_style,
                old_style=old_style,
                visual_time_pct=round(pct["visual"], 4),
                auditory_time_pct=round(pct["auditory"], 4),
                textual_time_pct=round(pct["textual"], 4),
                days_consistent=days_consistent,
                raw_confidence=round(raw_confidence, 4),
                confidence_score=round(confidence_score, 4),
                should_nudge=should_nudge,
                action=action,
                reason=reason,
            )
        )

    results.sort(key=lambda r: r.confidence_score, reverse=True)
    return [asdict(result) for result in results]


if __name__ == "__main__":
    demo_now = datetime(2026, 5, 2, tzinfo=timezone.utc)
    logs = []

    for day_offset in range(14):
        created = demo_now - timedelta(days=day_offset)
        logs.append({
            "user_id": "user_001",
            "selected_slot": "textual",
            "content_type": "textual_article",
            "duration_seconds": 900,
            "completion_percentage": 95,
            "created_at": created.isoformat(),
        })
        logs.append({
            "user_id": "user_001",
            "selected_slot": "visual",
            "content_type": "visual_video",
            "duration_seconds": 100,
            "completion_percentage": 80,
            "created_at": created.isoformat(),
        })

    output = detect_drift(
        logs,
        current_profiles={"user_001": {"current_primary_style": "visual"}},
        now=demo_now,
    )

    from pprint import pprint
    pprint(output)