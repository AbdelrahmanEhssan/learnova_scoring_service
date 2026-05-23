from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from personalization.learnova_scoring import score_user
from services.supabase_client import supabase


REQUIRED_TEST_NUMBERS = {1, 2, 3, 4, 5}

ROUTING_FEATURES = {
    "logical_reasoning",
    "abstract_reasoning",
    "spatial_reasoning",
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeable",
    "neuroticism",
    "communication",
    "teamwork",
    "conflict_resolution",
    "ethics",
    "leadership",
    "problem_solving",
    "emotional_intelligence",
    "time_management",
    "accountability",
    "visual",
    "auditory",
    "read_write",
    "kinesthetic",
    "realistic",
    "investigative",
    "artistic",
    "social",
    "enterprising",
    "conventional",
}


def _first_row(data: Any) -> Dict[str, Any]:
    if isinstance(data, list) and data:
        first = data[0]
        return first if isinstance(first, dict) else {}

    if isinstance(data, dict):
        return data

    return {}


def _get_weights_path() -> str:
    env_path = os.getenv("WEIGHTS_PATH")

    if env_path:
        return env_path

    root_dir = Path(__file__).resolve().parent.parent
    return str(root_dir / "personalization" / "track_weights.csv")


def _fetch_diagnostic_rows(user_id: str) -> List[Dict[str, Any]]:
    response = (
        supabase.table("diagnostic_test_results")
        .select("id, user_id, test_number, raw_answers, computed_scores, completed_at")
        .eq("user_id", user_id)
        .order("test_number")
        .execute()
    )

    rows = response.data or []
    return rows if isinstance(rows, list) else []


def _extract_features_from_computed_scores(computed_scores: Any) -> Dict[str, float]:
    if not isinstance(computed_scores, dict):
        return {}

    source = computed_scores.get("features")

    if not isinstance(source, dict):
        source = computed_scores

    features: Dict[str, float] = {}

    for key, value in source.items():
        if key not in ROUTING_FEATURES:
            continue

        try:
            features[key] = float(value)
        except (TypeError, ValueError):
            pass

    return features


def _build_routing_payload(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    payload: Dict[str, float] = {}

    for row in rows:
        features = _extract_features_from_computed_scores(row.get("computed_scores"))
        payload.update(features)

    return payload


def _db_learning_style_from_payload(payload: Dict[str, float]) -> str:
    visual = float(payload.get("visual", 0.0))
    auditory = float(payload.get("auditory", 0.0))

    # Current database supports only Visual, Auditory, Textual.
    # For profile display, read_write + kinesthetic are merged into Textual.
    textual = float(payload.get("read_write", 0.0)) + float(payload.get("kinesthetic", 0.0))

    scores = {
        "Visual": visual,
        "Auditory": auditory,
        "Textual": textual,
    }

    return max(scores, key=scores.get)


def _bayesian_alphas_from_payload(payload: Dict[str, float]) -> Dict[str, float]:
    visual = max(1.0, float(payload.get("visual", 0.0)) + 1.0)
    auditory = max(1.0, float(payload.get("auditory", 0.0)) + 1.0)
    textual = max(
        1.0,
        float(payload.get("read_write", 0.0)) + float(payload.get("kinesthetic", 0.0)) + 1.0,
    )

    return {
        "bayesian_alpha_visual": round(visual, 4),
        "bayesian_alpha_auditory": round(auditory, 4),
        "bayesian_alpha_textual": round(textual, 4),
    }


def _assigned_track_from_scores(final_track_scores: Dict[str, float], fallback_triggered: bool) -> str:
    if fallback_triggered:
        return "Foundation"

    if not final_track_scores:
        return "Foundation"

    best_track = max(final_track_scores, key=final_track_scores.get)

    if best_track in {"DA", "DE", "DS"}:
        return best_track

    return "Foundation"


def _upsert_student_profile(
    *,
    user_id: str,
    assigned_track: str,
    learning_style: str,
    routing_payload: Dict[str, float],
    routing_result: Any,
) -> Dict[str, Any]:
    alpha_fields = _bayesian_alphas_from_payload(routing_payload)

    profile_row = {
        "user_id": user_id,
        "assigned_track": assigned_track,
        "learning_style": learning_style,
        "learning_mode": "structured",
        "onboarding_complete": True,
        **alpha_fields,
    }

    try:
        response = (
            supabase.table("student_profiles")
            .upsert(profile_row, on_conflict="user_id")
            .execute()
        )

        return {
            "ok": True,
            "method": "upsert",
            "profile": response.data,
            "profile_row": profile_row,
        }

    except Exception as upsert_error:
        # Fallback for environments where upsert behaves differently.
        existing_response = (
            supabase.table("student_profiles")
            .select("id, user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        existing = _first_row(existing_response.data)

        if existing.get("id"):
            update_response = (
                supabase.table("student_profiles")
                .update(profile_row)
                .eq("user_id", user_id)
                .execute()
            )

            return {
                "ok": True,
                "method": "update_after_upsert_failed",
                "upsert_error": str(upsert_error),
                "profile": update_response.data,
                "profile_row": profile_row,
            }

        insert_response = (
            supabase.table("student_profiles")
            .insert(profile_row)
            .execute()
        )

        return {
            "ok": True,
            "method": "insert_after_upsert_failed",
            "upsert_error": str(upsert_error),
            "profile": insert_response.data,
            "profile_row": profile_row,
        }


def maybe_update_diagnostic_profile(user_id: str) -> Dict[str, Any]:
    """
    Called after each /score/diagnostic-result row update.

    It updates student_profiles only when all 5 diagnostic tests exist and all 5
    have computed_scores with real feature values.
    """
    rows = _fetch_diagnostic_rows(user_id)

    if len(rows) < 5:
        return {
            "ok": True,
            "profile_updated": False,
            "reason": "diagnostic_tests_incomplete",
            "rows_found": len(rows),
        }

    found_test_numbers = {int(row.get("test_number")) for row in rows if row.get("test_number") is not None}
    missing_tests = sorted(REQUIRED_TEST_NUMBERS - found_test_numbers)

    if missing_tests:
        return {
            "ok": True,
            "profile_updated": False,
            "reason": "missing_test_numbers",
            "missing_tests": missing_tests,
            "rows_found": len(rows),
        }

    unscored = [
        row.get("test_number")
        for row in rows
        if row.get("computed_scores") is None
    ]

    if unscored:
        return {
            "ok": True,
            "profile_updated": False,
            "reason": "some_tests_not_scored_yet",
            "unscored_tests": unscored,
        }

    routing_payload = _build_routing_payload(rows)

    missing_features = sorted(ROUTING_FEATURES - set(routing_payload.keys()))

    if missing_features:
        return {
            "ok": True,
            "profile_updated": False,
            "reason": "computed_scores_missing_routing_features",
            "missing_features": missing_features,
            "available_features": sorted(routing_payload.keys()),
        }

    weights_path = _get_weights_path()
    routing_result = score_user(routing_payload, weights_path)

    assigned_track = _assigned_track_from_scores(
        final_track_scores=routing_result.final_track_scores,
        fallback_triggered=routing_result.fallback_triggered,
    )

    learning_style = _db_learning_style_from_payload(routing_payload)

    profile_result = _upsert_student_profile(
        user_id=user_id,
        assigned_track=assigned_track,
        learning_style=learning_style,
        routing_payload=routing_payload,
        routing_result=routing_result,
    )

    return {
        "ok": True,
        "profile_updated": True,
        "assigned_track": assigned_track,
        "learning_style": learning_style,
        "weights_path": weights_path,
        "routing_payload": routing_payload,
        "routing_result": {
            "immediate_destination": routing_result.immediate_destination,
            "projected_specialization": routing_result.projected_specialization,
            "final_track_scores": routing_result.final_track_scores,
            "base_scores": routing_result.base_scores,
            "modifier_scores": routing_result.modifier_scores,
            "normalized_features": routing_result.normalized_features,
            "top_contributors": routing_result.top_contributors,
            "fallback_triggered": routing_result.fallback_triggered,
            "message": routing_result.message,
        },
        "profile_result": profile_result,
    }