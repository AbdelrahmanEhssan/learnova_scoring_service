from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, List, Any
import os

import pandas as pd

from personalization.scoring_config import (
    TRACKS,
    TRACK_LABELS,
    IMMEDIATE_DESTINATION,
    FALLBACK_TRACK,
    FALLBACK_THRESHOLD,
    BASE_WEIGHT,
    MODIFIER_WEIGHT,
    ONET_TRACK_BASE_FEATURE,
    FEATURE_RANGES,
    FEATURE_DISPLAY_NAMES,
)


@dataclass
class ScoringResult:
    immediate_destination: str
    projected_specialization: str
    final_track_scores: Dict[str, float]
    base_scores: Dict[str, float]
    modifier_scores: Dict[str, float]
    normalized_features: Dict[str, float]
    top_contributors: Dict[str, List[Tuple[str, float]]]
    fallback_triggered: bool
    message: str


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def min_max_normalize(raw_value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        raise ValueError(f"Invalid normalization range: ({min_value}, {max_value})")
    return clamp((raw_value - min_value) / (max_value - min_value))


def load_track_weights(path: str) -> Dict[str, Dict[str, float]]:
    """
    Loads track weights from CSV or XLSX.
    Expected columns: feature, DA, DE, DS
    Re-normalizes columns in code to guarantee exact 1.0 totals at runtime.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError("Unsupported weights file format. Use CSV or XLSX.")

    required_cols = {"feature", "DA", "DE", "DS"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in weights file: {missing}")

    df["feature"] = df["feature"].astype(str).str.strip()

    for col in TRACKS:
        df[col] = pd.to_numeric(df[col], errors="raise")
        total = df[col].sum()
        if total <= 0:
            raise ValueError(f"Track column {col} sums to zero.")
        df[col] = df[col] / total

    weights: Dict[str, Dict[str, float]] = {track: {} for track in TRACKS}
    for _, row in df.iterrows():
        feature = row["feature"]
        for track in TRACKS:
            weights[track][feature] = float(row[track])

    return weights


def normalize_payload(raw_payload: Dict[str, Any]) -> Dict[str, float]:
    """
    Normalizes a flat payload using FEATURE_RANGES.

    Any missing feature defaults to its minimum range value.
    This safely handles absent fields such as spatial_reasoning until
    that exam section is added in a future sprint.
    """
    normalized: Dict[str, float] = {}

    for feature, (min_val, max_val) in FEATURE_RANGES.items():
        raw_val = raw_payload.get(feature, min_val)
        normalized[feature] = min_max_normalize(float(raw_val), min_val, max_val)

    return normalized


def compute_base_scores(normalized_features: Dict[str, float]) -> Dict[str, float]:
    """
    Tier 1 (Anchor):
    Pull the normalized O*NET anchor directly into the corresponding track base score.

    DA_base = artistic
    DE_base = realistic
    DS_base = investigative
    """
    return {
        track: normalized_features[feature]
        for track, feature in ONET_TRACK_BASE_FEATURE.items()
    }


def compute_modifier_scores(
    normalized_features: Dict[str, float],
    weights: Dict[str, Dict[str, float]],
) -> Tuple[Dict[str, float], Dict[str, List[Tuple[str, float]]]]:
    """
    Tier 2 (Modifiers):
    modifier_score = Σ(normalized_feature × normalized_weight)

    Because each track column is normalized to sum to 1.0,
    each modifier score stays in the 0.0 - 1.0 range.
    """
    modifier_scores: Dict[str, float] = {}
    contributors: Dict[str, List[Tuple[str, float]]] = {}

    for track in TRACKS:
        score = 0.0
        track_contribs: List[Tuple[str, float]] = []

        for feature, weight in weights[track].items():
            feature_value = normalized_features.get(feature, 0.0)
            contribution = feature_value * weight
            score += contribution
            track_contribs.append((feature, contribution))

        track_contribs.sort(key=lambda x: x[1], reverse=True)
        modifier_scores[track] = round(score, 6)
        contributors[track] = track_contribs

    return modifier_scores, contributors


def compute_final_scores(
    base_scores: Dict[str, float],
    modifier_scores: Dict[str, float],
) -> Dict[str, float]:
    """
    Two-Tiered Additive Scoring Formula:

    final_score = (base_score × BASE_WEIGHT) + (modifier_score × MODIFIER_WEIGHT)

    Where:
    - base_score comes from the hardcoded O*NET direct mapping
      (Artistic -> DA, Realistic -> DE, Investigative -> DS)
    - modifier_score comes from the weighted sum of the normalized
      IQ, IPIP, Soft Skills, and VARK features

    This additive approach prevents the base score from acting as a hard 
    mathematical ceiling, appropriately scaling both independent metric tiers.
    """
    return {
        track: round(
            (base_scores[track] * BASE_WEIGHT) + (modifier_scores[track] * MODIFIER_WEIGHT), 6
        )
        for track in TRACKS
    }


def build_ui_message(
    projected_track: str,
    fallback_triggered: bool,
    top_features: List[Tuple[str, float]],
) -> str:
    if fallback_triggered:
        return (
            "You will begin with the Shared Foundation. "
            "Your current assessment profile does not yet point strongly enough to one specialization, "
            "so the best next step is to strengthen your fundamentals before selecting a projected path."
        )

    strengths = [
        FEATURE_DISPLAY_NAMES.get(feature, feature)
        for feature, contribution in top_features[:2]
        if contribution > 0
    ]

    if strengths:
        joined = " and ".join(strengths)
        return (
            f"Based on your strong {joined}, your projected specialization is "
            f"{TRACK_LABELS[projected_track]}. Let’s start with the Shared Foundation "
            "to build the core skills for that path."
        )

    return (
        f"Your projected specialization is {TRACK_LABELS[projected_track]}. "
        "You will begin with the Shared Foundation to build your core knowledge first."
    )


def score_user(raw_payload: Dict[str, Any], weights_path: str) -> ScoringResult:
    weights = load_track_weights(weights_path)
    normalized_features = normalize_payload(raw_payload)

    base_scores = compute_base_scores(normalized_features)
    modifier_scores, contributors = compute_modifier_scores(normalized_features, weights)
    final_scores = compute_final_scores(base_scores, modifier_scores)

    projected_track = max(final_scores, key=final_scores.get)
    best_score = final_scores[projected_track]
    fallback_triggered = best_score < FALLBACK_THRESHOLD

    output_track = FALLBACK_TRACK if fallback_triggered else TRACK_LABELS[projected_track]
    top_features = contributors[projected_track][:5]
    message = build_ui_message(projected_track, fallback_triggered, top_features)

    formatted_top = {
        track: [
            (FEATURE_DISPLAY_NAMES.get(feature, feature), round(value, 6))
            for feature, value in contribs[:5]
        ]
        for track, contribs in contributors.items()
    }

    return ScoringResult(
        immediate_destination=IMMEDIATE_DESTINATION,
        projected_specialization=output_track,
        final_track_scores=final_scores,
        base_scores=base_scores,
        modifier_scores=modifier_scores,
        normalized_features=normalized_features,
        top_contributors=formatted_top,
        fallback_triggered=fallback_triggered,
        message=message,
    )