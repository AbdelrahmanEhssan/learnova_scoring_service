from __future__ import annotations

from typing import Any, Dict, Optional


SELF_HARM_PHRASES = [
    "i want to die", "i wanna die", "kill myself", "hurt myself",
    "end my life", "suicide", "i don't want to live", "i dont want to live",
    "self harm",
]

URGENT_HEALTH_PHRASES = [
    "chest pain", "can't breathe", "cant breathe", "difficulty breathing",
    "severe bleeding", "bleeding a lot", "fainted", "seizure", "stroke",
    "heart attack", "overdose", "poison", "unconscious",
]

PERSONAL_HEALTH_PHRASES = [
    "i feel sick", "i am sick", "i'm sick", "headache", "fever", "pain",
    "rash", "infection", "medicine", "medication", "diagnose", "diagnosis",
    "doctor", "hospital", "anxiety attack", "panic attack", "depressed",
    "depression",
]


def _base_output(
    response_text: str,
    *,
    learning_state: str = "human_support",
    suggested_action: str = "human_support",
    source: str = "local_health_safety_guard",
    confidence: float = 1.0,
    needs_human_support: bool = True,
) -> Dict[str, Any]:
    return {
        "response_text": response_text,
        "learning_state": learning_state,
        "sentiment_score": -0.6,
        "cognitive_load": 0.8,
        "suggested_action": suggested_action,
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": confidence,
        "metadata": {
            "source": source,
            "used_gemini": False,
            "needs_human_support": needs_human_support,
        },
    }


def answer_health_safety_if_needed(message: str) -> Optional[Dict[str, Any]]:
    """
    Local safety guard for personal health / urgent health / self-harm messages.

    This intentionally avoids Gemini for health-sensitive situations.
    It does not diagnose. It gives safe, general support and encourages
    professional help when appropriate.
    """
    text = str(message or "").strip().lower()
    if not text:
        return None

    if any(phrase in text for phrase in SELF_HARM_PHRASES):
        return _base_output(
            "I’m really sorry you’re feeling this. Please contact someone you trust right now, "
            "and if you might hurt yourself or you feel unsafe, contact emergency services immediately. "
            "You do not have to handle this alone.",
            source="local_self_harm_safety_guard",
            confidence=1.0,
        )

    if any(phrase in text for phrase in URGENT_HEALTH_PHRASES):
        return _base_output(
            "This could be urgent. I can’t diagnose you, but if symptoms are severe, sudden, "
            "or you feel unsafe, please contact emergency services or a medical professional now.",
            source="local_urgent_health_guard",
            confidence=0.95,
        )

    health_advice_triggers = [
        "what should i do", "should i take", "is this normal", "diagnose",
        "treatment", "medicine", "medication", "doctor", "hospital",
    ]

    if any(phrase in text for phrase in PERSONAL_HEALTH_PHRASES) and any(
        trigger in text for trigger in health_advice_triggers
    ):
        return _base_output(
            "I can help you think through this generally, but I can’t diagnose or replace a doctor. "
            "If symptoms are severe, worsening, unusual, or worrying you, please contact a medical professional.",
            learning_state="concerned",
            suggested_action="seek_human_support",
            source="local_personal_health_guard",
            confidence=0.85,
            needs_human_support=True,
        )

    return None
