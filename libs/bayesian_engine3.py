"""
Sprint 5.3: Bayesian Learning Style Drift Engine
LearnNova Personalization Engine

This file preserves the teammate's Bayesian enhancement while adding production safeguards.
UPDATED V3: Constrained to a strictly 3-dimensional state space (Visual, Auditory, Textual).
Kinesthetic has been removed to prevent broken feedback loops.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Any, Optional

# STRICT 3D STATE SPACE
STYLES = ("visual", "auditory", "textual")

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
    "textual_article": "textual",
    "read_write": "textual",
}


def normalize_style(style: str) -> str:
    key = str(style).strip().lower().replace("-", "_").replace(" ", "_")
    if key not in STYLE_ALIASES:
        raise ValueError(f"Unsupported learning style: {style!r}")
    return STYLE_ALIASES[key]


def alpha_key(style: str) -> str:
    return f"{normalize_style(style)}_alpha"


def calculate_probabilities(user_profile: Dict[str, Any]) -> Dict[str, float]:
    """Calculate Dirichlet posterior mean probabilities from alpha values."""
    total_alpha = sum(max(1, int(user_profile.get(f"{style}_alpha", 1))) for style in STYLES)
    return {
        style: max(1, int(user_profile.get(f"{style}_alpha", 1))) / total_alpha
        for style in STYLES
    }


def process_rescue_intervention(
    user_profile: Dict[str, Any],
    successful_format: str,
    sentiment_score: float,
    sentiment_threshold: float = 0.40,
    min_total_evidence: int = 8,
    default_shift_threshold: float = 0.65,
) -> Dict[str, Any]:
    """
    Update Bayesian posterior probabilities based on Mitchy's intervention.
    """
    profile = deepcopy(user_profile)

    if sentiment_score <= sentiment_threshold:
        return {
            "status": "ignored",
            "reason": "Sentiment not strongly positive enough to qualify as evidence.",
            "sentiment_score": sentiment_score,
            "required_sentiment": sentiment_threshold,
            "updated_profile": profile,
        }

    normalized_format = normalize_style(successful_format)
    key = alpha_key(normalized_format)
    profile[key] = max(1, int(profile.get(key, 1))) + 1

    probabilities = calculate_probabilities(profile)
    new_dominant_style = max(probabilities, key=probabilities.get)
    current_style = normalize_style(profile.get("current_primary_style", "visual"))
    shift_threshold = float(profile.get("shift_threshold", default_shift_threshold))
    total_evidence = sum(max(1, int(profile.get(f"{style}_alpha", 1))) for style in STYLES)

    profile["current_primary_style"] = current_style

    if (
        new_dominant_style != current_style
        and probabilities[new_dominant_style] >= shift_threshold
        and total_evidence >= min_total_evidence
    ):
        profile["current_primary_style"] = new_dominant_style
        return {
            "status": "silent_shift_triggered",
            "old_style": current_style,
            "new_style": new_dominant_style,
            "confidence_score": round(probabilities[new_dominant_style], 4),
            "probabilities": {k: round(v, 4) for k, v in probabilities.items()},
            "total_evidence": total_evidence,
            "updated_profile": profile,
            "mitchy_notification": (
                "I noticed you seem to understand this type of topic better when it is "
                f"presented in a {new_dominant_style} format. "
                "I've optimized your upcoming lessons accordingly."
            ),
        }

    return {
        "status": "posterior_updated",
        "dominant_style": new_dominant_style,
        "confidence_score": round(probabilities[new_dominant_style], 4),
        "probabilities": {k: round(v, 4) for k, v in probabilities.items()},
        "total_evidence": total_evidence,
        "updated_profile": profile,
    }


def revert_drift_event(
    user_profile: Dict[str, Any],
    rejected_format: str,
    previous_format: str,
    sentiment_score: float,
    negative_sentiment_threshold: float = -0.50,
) -> Dict[str, Any]:
    """
    Self-healing rollback protocol.
    """
    profile = deepcopy(user_profile)

    if sentiment_score >= negative_sentiment_threshold:
        return {
            "status": "ignored",
            "reason": "Feedback not strongly negative enough to trigger rollback.",
            "sentiment_score": sentiment_score,
            "required_sentiment_below": negative_sentiment_threshold,
            "updated_profile": profile,
        }

    rejected = normalize_style(rejected_format)
    previous = normalize_style(previous_format)
    key = alpha_key(rejected)

    profile[key] = max(1, int(profile.get(key, 2)) - 1)
    profile["current_primary_style"] = previous

    probabilities = calculate_probabilities(profile)

    return {
        "status": "reverted",
        "rejected_style": rejected,
        "restored_style": previous,
        "confidence_score": round(probabilities[previous], 4),
        "probabilities": {k: round(v, 4) for k, v in probabilities.items()},
        "updated_profile": profile,
        "admin_alert": True,
        "mitchy_notification": f"I'm sorry — I'll switch your lessons back to {previous} immediately.",
    }


if __name__ == "__main__":
    # Updated to 3D state space
    demo_profile = {
        "visual_alpha": 6,
        "auditory_alpha": 1,
        "textual_alpha": 5,
        "current_primary_style": "visual",
        "shift_threshold": 0.65,
    }

    print(process_rescue_intervention(demo_profile, "textual", 0.75))