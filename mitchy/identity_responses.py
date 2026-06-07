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
    r"^hello\s+mitchy$",
    r"^hi\s+mitchy$",
    r"^hey\s+mitchy$",
    r"^salam+$",
    r"^السلام\s+عليكم$",
]

MITCHY_PING_PATTERNS = [
    r"^mitchy\??$",
    r"^mitchy\s+\?$",
    r"^are\s+you\s+there\??$",
    r"^you\s+there\??$",
]

CASUAL_CHECK_PATTERNS = [
    r"^yasta\s+enta\s+tmm\??$",
    r"^enta\s+tmm\??$",
    r"^are\s+you\s+ok\??$",
    r"^are\s+you\s+okay\??$",
]

LOCAL_CONCEPT_PATTERNS = [
    r"^rank\??$",
    r"^what\s+is\s+(the\s+)?rank\??$",
    r"^what\s+does\s+rank\s+mean\??$",
]

CAPABILITY_PATTERNS = [
    r"\bwhat\s+can\s+you\s+do\b",
    r"\bhow\s+can\s+you\s+help\b",
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


def answer_identity_or_smalltalk_if_needed(
    message: str,
    *,
    has_history: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Handles greetings, Mitchy identity, and casual pings locally.

    These messages should never be routed to document_chunks or any AI provider.
    """

    text = str(message or "").strip().lower()
    text = re.sub(r"\s+", " ", text)

    if not text:
        return None

    if _matches_any(text, IDENTITY_PATTERNS):
        return _output(
            "I’m Mitchy, your virtual Learning Assistant in LearNova. I help you understand lessons, check your progress, and choose what to study next.",
            source="local_identity_response",
        )

    if _matches_any(text, GREETING_PATTERNS):
        if has_history:
            return _output(
                "I’m here. What would you like to work on next?",
                source="local_greeting_response",
            )

        return _output(
            "Hi, I’m Mitchy, your virtual Learning Assistant in LearNova. I can help you understand your lessons, check your progress, and choose what to study next.",
            source="local_greeting_response",
        )

    if _matches_any(text, MITCHY_PING_PATTERNS):
        return _output(
            "I’m here. What would you like to continue with?",
            source="local_smalltalk_response",
        )

    if _matches_any(text, LOCAL_CONCEPT_PATTERNS):
        return _output(
            "Rank means the position of something after sorting. In data work, ranking usually tells you which row is 1st, 2nd, 3rd, and so on based on a chosen value like score, sales, or date.",
            source="local_basic_concept_response",
        )

    if _matches_any(text, CASUAL_CHECK_PATTERNS):
        return _output(
            "I’m here and ready to help. Tell me what lesson, topic, or problem you want to work on.",
            source="local_smalltalk_response",
        )

    if _matches_any(text, CAPABILITY_PATTERNS):
        return _output(
            "I can explain LearNova course concepts, show your current track or progress, and suggest what to study next based on your assigned path.",
            source="local_capability_response",
        )

    return None
