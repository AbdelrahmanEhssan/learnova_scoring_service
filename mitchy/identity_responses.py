from __future__ import annotations

import re
from typing import Any, Dict, Optional


IDENTITY_PATTERNS = [
    r"\bwhat\s+is\s+your\s+name\b",
    r"\bwho\s+are\s+you\b",
    r"\byour\s+name\b",
    r"\bare\s+you\s+mitchy\b",
    r"\bwhat\s+do\s+i\s+call\s+you\b",
]

GREETING_PATTERNS = [
    r"^hi+$",
    r"^hey+$",
    r"^hello+$",
    r"^salam+$",
    r"^السلام\s+عليكم$",
]

CAPABILITY_PATTERNS = [
    r"\bwhat\s+can\s+you\s+do\b",
    r"\bhelp\s+me\b",
]


def _output(response_text: str, *, source: str = "local_identity_response") -> Dict[str, Any]:
    return {
        "response_text": response_text,
        "learning_state": "curious_inquiry",
        "sentiment_score": 0.0,
        "cognitive_load": 0.15,
        "suggested_action": "none",
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": 0.95,
        "metadata": {
            "source": source,
            "used_gemini": False,
        },
    }


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def answer_identity_or_smalltalk_if_needed(message: str) -> Optional[Dict[str, Any]]:
    """
    Handles greetings and Mitchy identity/capability questions locally.

    These messages should never be routed to document_chunks because they are not
    curriculum retrieval questions. Routing them to document_chunks caused random
    Excel/W3Schools chunks to be returned for questions like "what is your name?".
    """

    text = str(message or "").strip().lower()
    text = re.sub(r"\s+", " ", text)

    if not text:
        return None

    if _matches_any(text, IDENTITY_PATTERNS):
        return _output(
            "I’m Mitchy, your LearnNova AI mentor. I can help you understand your lessons, check your progress, and explain course concepts step by step.",
            source="local_identity_response",
        )

    if _matches_any(text, GREETING_PATTERNS):
        return _output(
            "Hey, I’m Mitchy. Ask me about your current topic, your progress, or any course concept you want to understand.",
            source="local_greeting_response",
        )

    if _matches_any(text, CAPABILITY_PATTERNS):
        return _output(
            "I can help with your LearnNova curriculum, explain concepts from your course material, and answer progress questions like your current track, level, module, or topic.",
            source="local_capability_response",
        )

    return None
