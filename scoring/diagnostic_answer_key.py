from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ANSWER_KEY_FILENAME = "diagnostic_answer_key_full_seed_by_question_key.json"


def _seed_path() -> Path:
    return Path(__file__).resolve().parent / ANSWER_KEY_FILENAME

@lru_cache(maxsize=1)
def load_answer_key_rows() -> List[Dict[str, Any]]:
    path = _seed_path()

    if not path.exists():
        raise FileNotFoundError(
            f"Diagnostic answer-key seed not found at {path}. "
            f"Expected file: scoring/{ANSWER_KEY_FILENAME}"
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Supports both formats:
    # 1. Raw list: [...]
    # 2. Wrapped seed: {"rows": [...]}
    if isinstance(data, dict):
        rows = data.get("rows")
    else:
        rows = data

    if not isinstance(rows, list):
        raise ValueError(
            "Diagnostic answer-key seed must be either a JSON list "
            "or an object containing a 'rows' list."
        )

    return [row for row in rows if isinstance(row, dict)]


@lru_cache(maxsize=1)
def build_answer_key_indexes() -> Dict[str, Dict[Tuple[str, Any], Dict[str, Any]]]:
    by_selected_index: Dict[Tuple[str, int], Dict[str, Any]] = {}
    by_answer_value: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in load_answer_key_rows():
        question_key = row.get("question_key")

        if not question_key:
            continue

        selected_index = row.get("selected_index")
        answer_value = row.get("answer_value")

        if selected_index is not None:
            try:
                by_selected_index[(str(question_key), int(selected_index))] = row
            except (TypeError, ValueError):
                pass

        if answer_value is not None:
            by_answer_value[(str(question_key), str(answer_value))] = row

    return {
        "by_selected_index": by_selected_index,
        "by_answer_value": by_answer_value,
    }


def _extract_selected_index(raw_answer: Dict[str, Any]) -> Optional[int]:
    for key in ["selected_index", "selectedIndex", "choice_index", "option_index"]:
        value = raw_answer.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

    return None


def _extract_answer_value(raw_answer: Dict[str, Any]) -> Optional[str]:
    for key in [
        "answer_value",
        "selected_value",
        "selectedValue",
        "value",
        "selected_option",
        "selectedOption",
    ]:
        value = raw_answer.get(key)
        if value is not None:
            return str(value)

    selected_label = raw_answer.get("selected_label") or raw_answer.get("selectedLabel")

    if isinstance(selected_label, str) and selected_label.strip():
        label = selected_label.strip()

        # Handles labels like:
        # "B. Some managers may not be efficient."
        # "A"
        # "Strongly Agree"
        if len(label) >= 1 and label[0].isalpha():
            return label[0].upper()

    return None


def match_answer_key(raw_answer: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_answer, dict):
        return None

    question_key = raw_answer.get("question_key") or raw_answer.get("questionKey")

    if not question_key:
        return None

    question_key = str(question_key)

    indexes = build_answer_key_indexes()

    selected_index = _extract_selected_index(raw_answer)

    if selected_index is not None:
        match = indexes["by_selected_index"].get((question_key, selected_index))
        if match:
            return match

    answer_value = _extract_answer_value(raw_answer)

    if answer_value is not None:
        match = indexes["by_answer_value"].get((question_key, str(answer_value)))
        if match:
            return match

    return None

def get_answer_key_stats() -> Dict[str, Any]:
    rows = load_answer_key_rows()

    by_exam: Dict[str, int] = {}
    questions_by_exam: Dict[str, set] = {}

    for row in rows:
        exam_key = str(row.get("exam_key", "unknown"))
        question_key = str(row.get("question_key", ""))

        by_exam[exam_key] = by_exam.get(exam_key, 0) + 1

        if question_key:
            questions_by_exam.setdefault(exam_key, set()).add(question_key)

    return {
        "answer_key_file": str(_seed_path()),
        "total_rows": len(rows),
        "rows_by_exam": by_exam,
        "questions_by_exam": {
            exam_key: len(question_keys)
            for exam_key, question_keys in questions_by_exam.items()
        },
    }