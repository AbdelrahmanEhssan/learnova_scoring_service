from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional

from scoring.diagnostic_answer_key import match_answer_key


BIG5_DEFAULTS = {
    "openness": 0.0,
    "conscientiousness": 0.0,
    "extraversion": 0.0,
    "agreeable": 0.0,
    "neuroticism": 0.0,
}

SOFT_SKILL_DEFAULTS = {
    "communication": 0.0,
    "teamwork": 0.0,
    "conflict_resolution": 0.0,
    "ethics": 0.0,
    "leadership": 0.0,
    "problem_solving": 0.0,
    "emotional_intelligence": 0.0,
    "time_management": 0.0,
    "accountability": 0.0,
}

VARK_DEFAULTS = {
    "visual": 0.0,
    "auditory": 0.0,
    "read_write": 0.0,
    "kinesthetic": 0.0,
}

RIASEC_DEFAULTS = {
    "realistic": 0.0,
    "investigative": 0.0,
    "artistic": 0.0,
    "social": 0.0,
    "enterprising": 0.0,
    "conventional": 0.0,
}

IQ_DEFAULTS = {
    "logical_reasoning": 0.0,
    "abstract_reasoning": 0.0,
    # The optimized IQ exam currently has Abstract + Logical only.
    # Keep spatial_reasoning as 0 for compatibility with the routing model.
    "spatial_reasoning": 0.0,
}


def _round(value: float) -> float:
    return round(float(value), 4)


def _normalize_key(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip().lower()
    text = text.replace("-", "_").replace("/", "_").replace(" ", "_")

    aliases = {
        "read_write": "read_write",
        "readwrite": "read_write",
        "textual": "read_write",
        "text": "read_write",
        "visual": "visual",
        "auditory": "auditory",
        "kinesthetic": "kinesthetic",
        "openness": "openness",
        "conscientiousness": "conscientiousness",
        "extraversion": "extraversion",
        "agreeable": "agreeable",
        "agreeableness": "agreeable",
        "neuroticism": "neuroticism",
        "conflict_resolution": "conflict_resolution",
        "problem_solving": "problem_solving",
        "emotional_intelligence": "emotional_intelligence",
        "time_management": "time_management",
        "logical_reasoning": "logical_reasoning",
        "abstract_reasoning": "abstract_reasoning",
        "spatial_reasoning": "spatial_reasoning",
    }

    return aliases.get(text, text)


def _get_answer_items(raw_answers: Any) -> List[Any]:
    if isinstance(raw_answers, list):
        return raw_answers

    if isinstance(raw_answers, dict):
        for key in ["answers", "responses", "items", "data"]:
            value = raw_answers.get(key)
            if isinstance(value, list):
                return value

        if raw_answers:
            return list(raw_answers.values())

    return []


def _selected_summary(answer: Any) -> Dict[str, Any]:
    if not isinstance(answer, dict):
        return {}

    return {
        "question_key": answer.get("question_key"),
        "selected_index": answer.get("selected_index"),
        "selected_label": answer.get("selected_label"),
    }


def _match_rows(answers: List[Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    matched: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    for answer in answers:
        row = match_answer_key(answer)

        if row:
            matched.append(row)
        else:
            unmatched.append(_selected_summary(answer))

    return matched, unmatched


def _mean_features(values_by_feature: Dict[str, List[float]], defaults: Dict[str, float]) -> Dict[str, float]:
    output: Dict[str, float] = dict(defaults)

    for feature, values in values_by_feature.items():
        normalized = _normalize_key(feature)

        if not normalized:
            continue

        if values:
            output[normalized] = _round(mean(values))

    return output


def _get_score_value(row: Dict[str, Any], default: float = 0.0) -> float:
    value = row.get("score_value")

    if value is None:
        value = row.get("answer_value")

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score_ipip(answers: List[Any]) -> Dict[str, Any]:
    matched, unmatched = _match_rows(answers)

    values_by_feature: Dict[str, List[float]] = {}

    for row in matched:
        if row.get("test_number") != 1:
            continue

        feature_key = _normalize_key(row.get("feature_key") or row.get("trait"))

        if not feature_key:
            continue

        values_by_feature.setdefault(feature_key, []).append(_get_score_value(row, default=0.0))

    features = _mean_features(values_by_feature, BIG5_DEFAULTS)

    return {
        "exam": "personality_ipip",
        "status": "scored",
        "scoring_method": "answer_key_trait_likert",
        "answer_count": len(answers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "features": features,
        "warnings": [
            f"{len(unmatched)} answer(s) could not be matched by question_key + selected_index."
        ] if unmatched else [],
        "unmatched_answers": unmatched[:10],
    }


def score_soft_skills(answers: List[Any]) -> Dict[str, Any]:
    matched, unmatched = _match_rows(answers)

    values_by_feature: Dict[str, List[float]] = {}

    for row in matched:
        if row.get("test_number") != 2:
            continue

        contributions = row.get("feature_contributions")

        if isinstance(contributions, dict) and contributions:
            for feature_key, value in contributions.items():
                normalized = _normalize_key(feature_key)
                if not normalized:
                    continue

                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    numeric_value = _get_score_value(row, default=0.0)

                values_by_feature.setdefault(normalized, []).append(numeric_value)

            continue

        feature_keys = row.get("feature_keys") or []
        score_value = _get_score_value(row, default=0.0)

        if isinstance(feature_keys, list):
            for feature_key in feature_keys:
                normalized = _normalize_key(feature_key)
                if normalized:
                    values_by_feature.setdefault(normalized, []).append(score_value)

    features = _mean_features(values_by_feature, SOFT_SKILL_DEFAULTS)

    return {
        "exam": "soft_skills",
        "status": "scored",
        "scoring_method": "answer_key_sjt_weighted_score",
        "answer_count": len(answers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "features": features,
        "warnings": [
            f"{len(unmatched)} answer(s) could not be matched by question_key + selected_index."
        ] if unmatched else [],
        "unmatched_answers": unmatched[:10],
    }


def score_vark(answers: List[Any]) -> Dict[str, Any]:
    matched, unmatched = _match_rows(answers)

    features = dict(VARK_DEFAULTS)
    style_counts = {
        "Visual": 0,
        "Auditory": 0,
        "Textual": 0,
        "Kinesthetic": 0,
    }

    for row in matched:
        if row.get("test_number") != 3:
            continue

        feature_key = _normalize_key(row.get("feature_key") or row.get("style"))

        if feature_key in features:
            features[feature_key] += 1

        style = row.get("style")
        if style in style_counts:
            style_counts[style] += 1

    # DB supports Visual/Auditory/Textual only.
    db_style_scores = {
        "Visual": features["visual"],
        "Auditory": features["auditory"],
        "Textual": features["read_write"] + features["kinesthetic"],
    }

    dominant_db_learning_style = max(db_style_scores, key=db_style_scores.get)

    return {
        "exam": "vark",
        "status": "scored",
        "scoring_method": "answer_key_category_count",
        "answer_count": len(answers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "features": {
            key: _round(value)
            for key, value in features.items()
        },
        "style_counts": style_counts,
        "db_style_scores": db_style_scores,
        "dominant_style": dominant_db_learning_style,
        "warnings": [
            f"{len(unmatched)} answer(s) could not be matched by question_key + selected_index."
        ] if unmatched else [],
        "unmatched_answers": unmatched[:10],
    }


def score_career_onet(answers: List[Any]) -> Dict[str, Any]:
    matched, unmatched = _match_rows(answers)

    values_by_feature: Dict[str, List[float]] = {}
    track_weight_totals = {
        "DA": 0.0,
        "DE": 0.0,
        "DS": 0.0,
    }

    for row in matched:
        if row.get("test_number") != 4:
            continue

        feature_key = _normalize_key(
            row.get("feature_key")
            or row.get("aptitude_category")
            or row.get("trait")
        )

        score_value = _get_score_value(row, default=0.0)

        if feature_key:
            values_by_feature.setdefault(feature_key, []).append(score_value)

        for track_key, row_key in [
            ("DA", "weight_da"),
            ("DE", "weight_de"),
            ("DS", "weight_ds"),
        ]:
            try:
                track_weight_totals[track_key] += float(row.get(row_key) or 0.0)
            except (TypeError, ValueError):
                pass

    features = _mean_features(values_by_feature, RIASEC_DEFAULTS)

    return {
        "exam": "career_interest_onet",
        "status": "scored",
        "scoring_method": "answer_key_riasec_trait_score",
        "answer_count": len(answers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "features": features,
        "track_weight_totals": {
            key: _round(value)
            for key, value in track_weight_totals.items()
        },
        "warnings": [
            f"{len(unmatched)} answer(s) could not be matched by question_key + selected_index."
        ] if unmatched else [],
        "unmatched_answers": unmatched[:10],
    }


def score_iq(answers: List[Any]) -> Dict[str, Any]:
    matched, unmatched = _match_rows(answers)

    section_scores = dict(IQ_DEFAULTS)
    section_counts = {
        "logical_reasoning": 0,
        "abstract_reasoning": 0,
        "spatial_reasoning": 0,
    }

    for row in matched:
        if row.get("test_number") != 5:
            continue

        feature_key = _normalize_key(row.get("feature_key"))

        if feature_key not in section_scores:
            continue

        section_scores[feature_key] += _get_score_value(row, default=0.0)
        section_counts[feature_key] += 1

    return {
        "exam": "iq",
        "status": "scored",
        "scoring_method": "answer_key_correct_answer",
        "answer_count": len(answers),
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "features": {
            key: _round(value)
            for key, value in section_scores.items()
        },
        "section_counts": section_counts,
        "warnings": [
            f"{len(unmatched)} answer(s) could not be matched by question_key + selected_index."
        ] if unmatched else [],
        "unmatched_answers": unmatched[:10],
    }


def score_diagnostic(test_number: int, raw_answers: Any) -> Dict[str, Any]:
    answers = _get_answer_items(raw_answers)

    if test_number == 1:
        return score_ipip(answers)

    if test_number == 2:
        return score_soft_skills(answers)

    if test_number == 3:
        return score_vark(answers)

    if test_number == 4:
        return score_career_onet(answers)

    if test_number == 5:
        return score_iq(answers)

    return {
        "status": "error",
        "message": "Unknown diagnostic test number",
        "test_number": test_number,
        "answer_count": len(answers),
    }