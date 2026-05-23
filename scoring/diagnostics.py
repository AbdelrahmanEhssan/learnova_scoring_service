from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional, Tuple


BIG5_TRAITS = [
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeable",
    "neuroticism",
]

SOFT_SKILLS = [
    "communication",
    "teamwork",
    "conflict_resolution",
    "ethics",
    "leadership",
    "problem_solving",
    "emotional_intelligence",
    "time_management",
    "accountability",
]

VARK_STYLES = [
    "visual",
    "auditory",
    "read_write",
    "kinesthetic",
]

RIASEC_TRAITS = [
    "realistic",
    "investigative",
    "artistic",
    "social",
    "enterprising",
    "conventional",
]

IQ_SECTIONS = [
    ("logical_reasoning", 15),
    ("abstract_reasoning", 20),
    ("spatial_reasoning", 20),
]


CATEGORY_ALIASES = {
    # Big Five
    "agreeableness": "agreeable",
    "agreeable": "agreeable",
    "openness": "openness",
    "conscientiousness": "conscientiousness",
    "extraversion": "extraversion",
    "neuroticism": "neuroticism",

    # Soft skills
    "communication": "communication",
    "teamwork": "teamwork",
    "conflict": "conflict_resolution",
    "conflict_resolution": "conflict_resolution",
    "ethics": "ethics",
    "leadership": "leadership",
    "problem_solving": "problem_solving",
    "problem solving": "problem_solving",
    "emotional_intelligence": "emotional_intelligence",
    "emotional intelligence": "emotional_intelligence",
    "time_management": "time_management",
    "time management": "time_management",
    "accountability": "accountability",

    # VARK
    "v": "visual",
    "visual": "visual",
    "a": "auditory",
    "auditory": "auditory",
    "r": "read_write",
    "read": "read_write",
    "read_write": "read_write",
    "read/write": "read_write",
    "readwrite": "read_write",
    "textual": "read_write",
    "text": "read_write",
    "k": "kinesthetic",
    "kinesthetic": "kinesthetic",

    # RIASEC
    "realistic": "realistic",
    "investigative": "investigative",
    "artistic": "artistic",
    "social": "social",
    "enterprising": "enterprising",
    "conventional": "conventional",

    # IQ
    "logical": "logical_reasoning",
    "logic": "logical_reasoning",
    "logical_reasoning": "logical_reasoning",
    "abstract": "abstract_reasoning",
    "abstract_reasoning": "abstract_reasoning",
    "spatial": "spatial_reasoning",
    "spatial_reasoning": "spatial_reasoning",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def round_score(value: float) -> float:
    return round(float(value), 4)


def normalize_category(value: Any) -> Optional[str]:
    if value is None:
        return None

    key = str(value).strip().lower().replace("-", "_")
    key = key.replace(" ", "_")

    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]

    key_space = key.replace("_", " ")
    return CATEGORY_ALIASES.get(key_space)


def get_answer_items(raw_answers: Any) -> List[Any]:
    if isinstance(raw_answers, dict):
        for key in ["answers", "responses", "items", "data"]:
            value = raw_answers.get(key)
            if isinstance(value, list):
                return value

        # Sometimes raw_answers itself is a dict of question_id -> answer.
        if raw_answers:
            return list(raw_answers.values())

        return []

    if isinstance(raw_answers, list):
        return raw_answers

    return []


def extract_numeric_value(item: Any) -> Optional[float]:
    if isinstance(item, bool):
        return 1.0 if item else 0.0

    if isinstance(item, (int, float)):
        return float(item)

    if isinstance(item, str):
        stripped = item.strip()
        try:
            return float(stripped)
        except ValueError:
            return None

    if not isinstance(item, dict):
        return None

    if isinstance(item.get("is_correct"), bool):
        return 1.0 if item["is_correct"] else 0.0

    for key in [
        "score",
        "value",
        "answer_value",
        "selected_value",
        "rating",
        "points",
        "raw_score",
    ]:
        if key in item and item[key] is not None:
            try:
                return float(item[key])
            except (TypeError, ValueError):
                pass

    answer = item.get("answer") or item.get("selected") or item.get("selected_option")

    if isinstance(answer, bool):
        return 1.0 if answer else 0.0

    if isinstance(answer, (int, float)):
        return float(answer)

    if isinstance(answer, str):
        try:
            return float(answer.strip())
        except ValueError:
            return None

    return None


def extract_category(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return normalize_category(item)

    if not isinstance(item, dict):
        return None

    for key in [
        "category",
        "trait",
        "dimension",
        "skill",
        "scale",
        "domain",
        "style",
        "section",
        "type",
    ]:
        if key in item:
            normalized = normalize_category(item.get(key))
            if normalized:
                return normalized

    for key in ["answer", "selected", "selected_option", "selected_style"]:
        if key in item:
            normalized = normalize_category(item.get(key))
            if normalized:
                return normalized

    return None


def is_reverse_scored(item: Any) -> bool:
    if not isinstance(item, dict):
        return False

    for key in ["reverse", "reverse_scored", "is_reverse"]:
        if isinstance(item.get(key), bool):
            return item[key]

    return False


def maybe_reverse_likert(value: float, reverse: bool, low: float = 1.0, high: float = 5.0) -> float:
    if not reverse:
        return value

    return high + low - value


def grouped_average_scores(
    items: List[Any],
    labels: List[str],
    value_low: float,
    value_high: float,
) -> Tuple[Dict[str, float], List[str]]:
    grouped: Dict[str, List[float]] = {label: [] for label in labels}
    warnings: List[str] = []

    for item in items:
        category = extract_category(item)

        if category not in grouped:
            continue

        value = extract_numeric_value(item)

        if value is None:
            warnings.append(f"Missing numeric value for category {category}")
            continue

        value = maybe_reverse_likert(
            value,
            reverse=is_reverse_scored(item),
            low=value_low,
            high=value_high,
        )

        grouped[category].append(clamp(value, value_low, value_high))

    scores: Dict[str, float] = {}

    for label in labels:
        values = grouped[label]
        if values:
            scores[label] = round_score(mean(values))
        else:
            scores[label] = value_low
            warnings.append(f"No answers found for {label}; defaulted to {value_low}")

    return scores, warnings


def chunk_average_scores(
    items: List[Any],
    labels: List[str],
    value_low: float,
    value_high: float,
) -> Tuple[Dict[str, float], List[str]]:
    warnings = ["Used fallback chunk-based scoring because answer categories were missing."]

    values = []

    for item in items:
        value = extract_numeric_value(item)
        if value is not None:
            values.append(clamp(value, value_low, value_high))

    if not values:
        return {label: value_low for label in labels}, warnings + ["No numeric answers found."]

    chunk_size = max(1, len(values) // len(labels))
    scores: Dict[str, float] = {}

    for index, label in enumerate(labels):
        start = index * chunk_size
        end = len(values) if index == len(labels) - 1 else (index + 1) * chunk_size
        chunk = values[start:end]
        scores[label] = round_score(mean(chunk)) if chunk else value_low

    return scores, warnings


def has_any_known_category(items: List[Any], labels: List[str]) -> bool:
    label_set = set(labels)

    for item in items:
        category = extract_category(item)
        if category in label_set:
            return True

    return False


def score_ipip(answers: List[Any]) -> Dict[str, Any]:
    if has_any_known_category(answers, BIG5_TRAITS):
        features, warnings = grouped_average_scores(
            answers,
            BIG5_TRAITS,
            value_low=1.0,
            value_high=5.0,
        )
        method = "category_average"
    else:
        features, warnings = chunk_average_scores(
            answers,
            BIG5_TRAITS,
            value_low=1.0,
            value_high=5.0,
        )
        method = "fallback_chunk_average"

    return {
        "exam": "personality_ipip",
        "status": "scored",
        "scoring_method": method,
        "answer_count": len(answers),
        "features": features,
        "warnings": warnings,
    }


def scale_to_0_10(value: float) -> float:
    # If values are Likert 1-5, convert to 0-10.
    if 1.0 <= value <= 5.0:
        return ((value - 1.0) / 4.0) * 10.0

    return clamp(value, 0.0, 10.0)


def score_soft_skills(answers: List[Any]) -> Dict[str, Any]:
    if has_any_known_category(answers, SOFT_SKILLS):
        raw_features, warnings = grouped_average_scores(
            answers,
            SOFT_SKILLS,
            value_low=0.0,
            value_high=10.0,
        )
        method = "category_average"
    else:
        raw_features, warnings = chunk_average_scores(
            answers,
            SOFT_SKILLS,
            value_low=0.0,
            value_high=10.0,
        )
        method = "fallback_chunk_average"

    features = {
        skill: round_score(scale_to_0_10(value))
        for skill, value in raw_features.items()
    }

    return {
        "exam": "soft_skills",
        "status": "scored",
        "scoring_method": method,
        "answer_count": len(answers),
        "features": features,
        "warnings": warnings,
    }


def score_vark(answers: List[Any]) -> Dict[str, Any]:
    counts = {style: 0 for style in VARK_STYLES}
    warnings: List[str] = []

    for item in answers:
        selected_values: List[Any] = []

        if isinstance(item, dict):
            for key in [
                "selected_styles",
                "selected_options",
                "answers",
                "answer",
                "selected",
                "selected_option",
                "style",
            ]:
                if key in item:
                    value = item.get(key)
                    if isinstance(value, list):
                        selected_values.extend(value)
                    else:
                        selected_values.append(value)
                    break
        else:
            selected_values.append(item)

        if not selected_values:
            warnings.append("Missing VARK selected option.")
            continue

        for selected in selected_values:
            style = normalize_category(selected)

            if style in counts:
                counts[style] += 1
            else:
                warnings.append(f"Unknown VARK option: {selected}")

    dominant_style = max(counts, key=counts.get) if counts else "read_write"

    return {
        "exam": "vark",
        "status": "scored",
        "scoring_method": "style_count",
        "answer_count": len(answers),
        "features": counts,
        "dominant_style": dominant_style,
        "warnings": warnings,
    }


def score_career_onet(answers: List[Any]) -> Dict[str, Any]:
    if has_any_known_category(answers, RIASEC_TRAITS):
        features, warnings = grouped_average_scores(
            answers,
            RIASEC_TRAITS,
            value_low=1.0,
            value_high=5.0,
        )
        method = "category_average"
    else:
        features, warnings = chunk_average_scores(
            answers,
            RIASEC_TRAITS,
            value_low=1.0,
            value_high=5.0,
        )
        method = "fallback_chunk_average"

    return {
        "exam": "career_interest_onet",
        "status": "scored",
        "scoring_method": method,
        "answer_count": len(answers),
        "features": features,
        "warnings": warnings,
    }


def score_iq(answers: List[Any]) -> Dict[str, Any]:
    section_scores = {
        "logical_reasoning": 0.0,
        "abstract_reasoning": 0.0,
        "spatial_reasoning": 0.0,
    }

    section_counts = {
        "logical_reasoning": 0,
        "abstract_reasoning": 0,
        "spatial_reasoning": 0,
    }

    warnings: List[str] = []

    if has_any_known_category(answers, list(section_scores.keys())):
        method = "section_correctness_or_score"

        for item in answers:
            section = extract_category(item)

            if section not in section_scores:
                continue

            value = extract_numeric_value(item)

            if value is None:
                warnings.append(f"Missing IQ score/correctness value for {section}")
                continue

            # Most IQ rows should be 0/1 correctness. If a larger score is provided,
            # this still sums it safely.
            section_scores[section] += max(0.0, value)
            section_counts[section] += 1

    else:
        method = "fallback_chunk_sum"
        warnings.append(
            "Used fallback IQ chunk scoring because section/correctness fields were missing."
        )

        values = []

        for item in answers:
            value = extract_numeric_value(item)
            if value is not None:
                values.append(max(0.0, value))

        cursor = 0

        for section, expected_count in IQ_SECTIONS:
            chunk = values[cursor: cursor + expected_count]
            cursor += expected_count

            if not chunk:
                continue

            # Treat positive values as points. If Flutter sends 0/1, this is true score.
            section_scores[section] = sum(chunk)
            section_counts[section] = len(chunk)

    # Clamp to configured ranges used by personalization/scoring_config.py.
    section_scores["logical_reasoning"] = clamp(section_scores["logical_reasoning"], 0.0, 15.0)
    section_scores["abstract_reasoning"] = clamp(section_scores["abstract_reasoning"], 0.0, 20.0)
    section_scores["spatial_reasoning"] = clamp(section_scores["spatial_reasoning"], 0.0, 20.0)

    features = {
        key: round_score(value)
        for key, value in section_scores.items()
    }

    return {
        "exam": "iq",
        "status": "scored",
        "scoring_method": method,
        "answer_count": len(answers),
        "features": features,
        "section_counts": section_counts,
        "warnings": warnings,
    }


def score_diagnostic(test_number: int, raw_answers: Any) -> Dict[str, Any]:
    answers = get_answer_items(raw_answers)

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
    }