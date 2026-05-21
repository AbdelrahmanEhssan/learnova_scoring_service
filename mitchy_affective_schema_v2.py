from __future__ import annotations

from typing import Any, Dict


VALID_STATES = {
    "confused",
    "misconception",
    "frustrated",
    "anxious_overwhelmed",
    "curious_inquiry",
    "flow_mastered",
    "disengaged",
    "external_distraction",
    "burnout_fatigue",
}


def validate_affective_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("LLM output must be a dictionary.")

    if "metadata" not in payload or not isinstance(payload["metadata"], dict):
        raise ValueError("LLM output must include a metadata object.")

    metadata = payload["metadata"]

    if "learning_state" not in metadata:
        raise ValueError("metadata.learning_state is missing.")

    if "cognitive_load" not in metadata:
        raise ValueError("metadata.cognitive_load is missing.")

    learning_state = metadata["learning_state"]
    cognitive_load = metadata["cognitive_load"]

    if learning_state not in VALID_STATES:
        raise ValueError(
            f"Invalid learning_state '{learning_state}'. "
            f"Must be one of: {sorted(VALID_STATES)}"
        )

    if not isinstance(cognitive_load, (int, float)):
        raise TypeError("metadata.cognitive_load must be numeric.")

    if cognitive_load < 0.0 or cognitive_load > 1.0:
        raise ValueError("metadata.cognitive_load must be between 0.0 and 1.0.")

    metadata["cognitive_load"] = round(float(cognitive_load), 4)
    return payload
