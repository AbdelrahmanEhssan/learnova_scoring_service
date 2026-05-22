from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from json_repair import safe_parse_json


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(r"\s*```$", "", cleaned)

    return cleaned.strip()


def _extract_json_object(text: str) -> Optional[str]:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else None


def parse_model_json(raw_text: str | None) -> Optional[Dict[str, Any]]:
    """
    Parse Gemini JSON.

    First tries normal JSON.
    Then tries code-fence/object extraction.
    Finally uses the existing json_repair.safe_parse_json as a fallback.
    """
    if not raw_text:
        return None

    cleaned = _strip_code_fence(raw_text)

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    extracted = _extract_json_object(cleaned)
    if extracted:
        try:
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

    try:
        repaired = safe_parse_json(raw_text)

        if isinstance(repaired, dict):
            metadata = repaired.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}

            return {
                "response_text": repaired.get("response_text")
                or repaired.get("text"),
                "suggested_action": repaired.get("suggested_action")
                or repaired.get("action"),
                "learning_state": repaired.get("learning_state")
                or metadata.get("learning_state"),
                "recommended_format": repaired.get("recommended_format")
                or repaired.get("format_used"),
                "confidence": repaired.get("confidence", 0.4),
                "metadata": metadata,
            }
    except Exception:
        pass

    return None
