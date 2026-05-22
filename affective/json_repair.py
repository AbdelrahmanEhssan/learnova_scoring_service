from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


DEFAULT_RESPONSE: Dict[str, Any] = {
    "text": "",
    "action": "none",
    "metadata": {
        "learning_state": "progressing",
        "cognitive_load": 0.3,
    },
}


def log_malformed_json(raw_output: str, log_path: str = "error_log.txt", reason: str = "Malformed JSON") -> None:
    path = Path(log_path)
    timestamp = datetime.now().isoformat(timespec="seconds")

    with path.open("a", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"Reason: {reason}\n")
        f.write("Raw Output:\n")
        f.write(raw_output + "\n\n")


def _extract_json_object(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else None


def _basic_json_cleanup(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    cleaned = (
        cleaned.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "text": payload.get("text", DEFAULT_RESPONSE["text"]),
        "action": payload.get("action", DEFAULT_RESPONSE["action"]),
        "metadata": {
            "learning_state": DEFAULT_RESPONSE["metadata"]["learning_state"],
            "cognitive_load": DEFAULT_RESPONSE["metadata"]["cognitive_load"],
        },
    }

    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        result["metadata"]["learning_state"] = metadata.get(
            "learning_state",
            DEFAULT_RESPONSE["metadata"]["learning_state"],
        )
        result["metadata"]["cognitive_load"] = metadata.get(
            "cognitive_load",
            DEFAULT_RESPONSE["metadata"]["cognitive_load"],
        )

    return result


def safe_parse_json(llm_output: str, log_path: str = "error_log.txt") -> Dict[str, Any]:
    if not isinstance(llm_output, str):
        log_malformed_json(str(llm_output), log_path, reason="Non-string LLM output")
        return DEFAULT_RESPONSE.copy()

    try:
        parsed = json.loads(llm_output)
        if isinstance(parsed, dict):
            return _normalize_payload(parsed)
        log_malformed_json(llm_output, log_path, reason="Parsed JSON is not an object")
        return DEFAULT_RESPONSE.copy()
    except Exception:
        pass

    try:
        extracted = _extract_json_object(llm_output)
        if extracted:
            cleaned = _basic_json_cleanup(extracted)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                log_malformed_json(llm_output, log_path, reason="Recovered via regex fallback")
                return _normalize_payload(parsed)
    except Exception:
        pass

    log_malformed_json(llm_output, log_path, reason="Failed parse, returned default")
    return DEFAULT_RESPONSE.copy()
