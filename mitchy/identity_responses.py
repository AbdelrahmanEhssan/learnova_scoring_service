from __future__ import annotations

import re
from typing import Any, Dict, Optional

from mitchy.language_utils import (
    detect_language,
    language_capability_text,
    mitchy_identity_text,
    normalize_for_intent,
    response_for_language,
)


IDENTITY_PATTERNS = [
    r"\bwhat\s+is\s+your\s+name\b",
    r"\bwho\s+are\s+you\b",
    r"\bwho\s+are\s+u\b",
    r"\bwho\s+r\s+u\b",
    r"\byour\s+name\b",
    r"\bare\s+you\s+mitchy\b",
    r"\bwhat\s+do\s+i\s+call\s+you\b",
    r"انت\s+مين",
    r"إنت\s+مين",
    r"انتا\s+مين",
    r"مين\s+انت",
    r"من\s+انت",
    r"مين\s+انتا",
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
    r"^سلام$",
    r"^اهلا$",
    r"^أهلا$",
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
    r"انت\s+عامل\s+ا[يية]+",
    r"عامل\s+ا[يية]+",
]

LANGUAGE_PATTERNS = [
    r"\bcan\s+you\s+speak\s+arabic\b",
    r"\bdo\s+you\s+understand\s+arabic\b",
    r"\bdo\s+you\s+speak\s+arabic\b",
    r"\bany\s+different\s+language\b",
    r"\bspeak\s+arabic\b",
    r"اتكلم\s+.*عربي",
    r"تكلم\s+.*عربي",
    r"بتفهم\s+عربي",
]

LOCAL_CONCEPT_PATTERNS = [
    r"^rank$",
    r"^what\s+is\s+(the\s+)?rank$",
    r"^what\s+does\s+rank\s+mean$",
]

CAPABILITY_PATTERNS = [
    r"\bwhat\s+can\s+you\s+do\b",
    r"\bhow\s+can\s+you\s+help\b",
    r"\bhelp\s+me\b",
]


def _output(response_text: str, *, source: str = "local_identity_response", language: str = "en") -> Dict[str, Any]:
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
            "detected_language": language,
        },
    }


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def answer_identity_or_smalltalk_if_needed(
    message: str,
    *,
    has_history: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Handles greetings, Mitchy identity, language capability, slang, Arabic, and casual pings locally.

    These messages should never be routed to document_chunks or an AI provider.
    """

    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)

    if not text:
        return None

    if _matches_any(original, LANGUAGE_PATTERNS) or _matches_any(text, LANGUAGE_PATTERNS):
        return _output(
            language_capability_text(language),
            source="local_language_capability_response",
            language=language,
        )

    if _matches_any(original, IDENTITY_PATTERNS) or _matches_any(text, IDENTITY_PATTERNS):
        return _output(
            mitchy_identity_text(language),
            source="local_identity_response",
            language=language,
        )

    if _matches_any(text, GREETING_PATTERNS) or _matches_any(original, GREETING_PATTERNS):
        # Always introduce properly on direct greetings. Previous sessions should not suppress the intro.
        return _output(
            mitchy_identity_text(language),
            source="local_greeting_response",
            language=language,
        )

    if _matches_any(text, MITCHY_PING_PATTERNS):
        return _output(
            response_for_language(
                "I’m here. What would you like to continue with?",
                "أنا موجود. تحب نكمل في إيه؟",
                language,
            ),
            source="local_smalltalk_response",
            language=language,
        )

    if _matches_any(text, LOCAL_CONCEPT_PATTERNS):
        return _output(
            response_for_language(
                "Rank means position after sorting. In LearNova, your rank usually relates to your XP/leaderboard position; in data, ranking means ordering rows like 1st, 2nd, and 3rd by a value.",
                "الرانك يعني ترتيبك بعد المقارنة أو الفرز. في LearNova غالبًا بيكون مرتبط بالـ XP أو ترتيبك في الـ leaderboard، وفي الداتا يعني ترتيب الصفوف حسب قيمة معينة.",
                language,
            ),
            source="local_basic_concept_response",
            language=language,
        )

    if _matches_any(text, CASUAL_CHECK_PATTERNS) or _matches_any(original, CASUAL_CHECK_PATTERNS):
        return _output(
            response_for_language(
                "I’m good and ready to help. Tell me what lesson, topic, or progress question you want to work on.",
                "أنا تمام وجاهز أساعدك. قولّي عايز تشتغل على درس، موضوع، أو سؤال عن تقدمك؟",
                language,
            ),
            source="local_smalltalk_response",
            language=language,
        )

    if _matches_any(text, CAPABILITY_PATTERNS):
        return _output(
            response_for_language(
                "I can explain LearNova course concepts, show your track/progress, help with XP/rank questions when the data is available, and suggest what to study next.",
                "أقدر أشرح مفاهيم كورسات LearNova، أقولك التراك والتقدم، أساعدك في أسئلة الـ XP والرانك لو الداتا متاحة، وأقترح تذاكر إيه بعد كده.",
                language,
            ),
            source="local_capability_response",
            language=language,
        )

    return None
