from __future__ import annotations

from typing import Any, Dict, Optional

from chat_logic_v3 import process_chat

from mitchy.db import (
    fetch_content_context,
    fetch_recent_mitchy_turns,
    fetch_recent_sentiment_scores,
    fetch_student_profile,
    save_mitchy_interaction,
)
from mitchy.gemini_client import generate_mitchy_json
from mitchy.parsing import parse_model_json
from mitchy.prompting import build_mitchy_prompt
from mitchy.schemas import (
    normalize_mitchy_output,
    profile_to_recommended_format,
)


CRISIS_PHRASES = [
    "i want to die",
    "i wanna die",
    "kill myself",
    "hurt myself",
    "end my life",
    "suicide",
    "i don't want to live",
    "i dont want to live",
]


LOW_VALUE_MESSAGES = {
    "ok",
    "okay",
    "k",
    "yes",
    "no",
    "thanks",
    "thank you",
    "thx",
    "brb",
    "afk",
}


def _contains_crisis_language(message: str) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in CRISIS_PHRASES)


def _safe_local_analysis(message: str, sentiment_history: list[float]) -> Dict[str, Any]:
    try:
        return process_chat(
            {
                "message": message,
                "history": sentiment_history,
            }
        )
    except Exception:
        return {
            "response_text": "Let's slow this down and handle it one small step at a time.",
            "sentiment_score": 0.0,
            "cognitive_load": 0.3,
            "learning_state": "confused",
            "suggested_action": "rescue_explanation",
        }


def _needs_gemini(message: str, local_analysis: Dict[str, Any]) -> bool:
    text = message.strip().lower()

    if not text:
        return False

    if text in LOW_VALUE_MESSAGES:
        return False

    learning_state = local_analysis.get("learning_state")
    suggested_action = local_analysis.get("suggested_action")

    if learning_state in {"external_distraction", "burnout_fatigue"}:
        return False

    if suggested_action == "take_break" and "?" not in text:
        return False

    if learning_state in {
        "confused",
        "misconception",
        "frustrated",
        "anxious_overwhelmed",
        "curious_inquiry",
    }:
        return True

    conceptual_triggers = [
        "explain",
        "example",
        "why",
        "how",
        "what is",
        "what are",
        "difference",
        "i don't understand",
        "i dont understand",
        "i don't get",
        "i dont get",
        "stuck",
        "confused",
    ]

    return any(trigger in text for trigger in conceptual_triggers)


def _build_local_only_output(
    local_analysis: Dict[str, Any],
    default_format: str,
) -> Dict[str, Any]:
    output = normalize_mitchy_output(
        payload=None,
        local_analysis=local_analysis,
        default_format=default_format,
    )

    output["metadata"]["used_gemini"] = False
    output["metadata"]["source"] = "local_fallback"

    return output


def _build_crisis_output(
    local_analysis: Dict[str, Any],
    default_format: str,
) -> Dict[str, Any]:
    output = normalize_mitchy_output(
        payload={
            "response_text": (
                "I'm really sorry you're feeling this. Please contact someone you trust now "
                "or emergency services in your area. You do not have to handle this alone."
            ),
            "learning_state": "human_support",
            "suggested_action": "human_support",
            "recommended_format": default_format,
            "confidence": 1.0,
            "metadata": {
                "needs_human_support": True,
                "short_reason": "The student expressed possible danger or self-harm language.",
            },
        },
        local_analysis=local_analysis,
        default_format=default_format,
    )

    output["metadata"]["used_gemini"] = False
    output["metadata"]["source"] = "safety_rule"

    return output


def process_mitchy_message(
    user_id: str,
    message: str,
    user_email: Optional[str] = None,
    full_name: Optional[str] = None,
    topic_id: Optional[str] = None,
    module_id: Optional[str] = None,
    screen_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main Mitchy controller.

    Pipeline:
    1. Fetch student profile.
    2. Fetch recent chat and sentiment history.
    3. Run local affective analysis from chat_logic_v3.py.
    4. Decide whether Gemini is needed.
    5. If needed, build prompt and call Gemini.
    6. Repair/normalize output.
    7. Save to Supabase using chat_sessions/chat_messages/student_sentiment_history.
    8. Return clean response to Railway endpoint.
    """
    clean_message = str(message or "").strip()

    if not clean_message:
        raise ValueError("Message cannot be empty")

    profile = fetch_student_profile(user_id)
    recent_turns = fetch_recent_mitchy_turns(user_id=user_id, limit=12)
    sentiment_history = fetch_recent_sentiment_scores(user_id=user_id, limit=8)
    content_context = fetch_content_context(topic_id=topic_id, module_id=module_id)

    local_analysis = _safe_local_analysis(
        message=clean_message,
        sentiment_history=sentiment_history,
    )

    default_format = profile_to_recommended_format(profile)

    raw_model_text: Optional[str] = None
    parsed_model_output: Optional[Dict[str, Any]] = None
    gemini_error: Optional[str] = None
    model_name: Optional[str] = None

    if _contains_crisis_language(clean_message):
        final_output = _build_crisis_output(
            local_analysis=local_analysis,
            default_format=default_format,
        )
        model_name = "local_safety_rule"

    elif _needs_gemini(clean_message, local_analysis):
        prompt = build_mitchy_prompt(
            message=clean_message,
            profile=profile,
            recent_history=recent_turns,
            local_analysis=local_analysis,
            recommended_format=default_format,
            content_context=content_context,
            topic_id=topic_id,
            module_id=module_id,
            screen_context=screen_context,
        )

        raw_model_text, gemini_error, model_name = generate_mitchy_json(prompt)
        parsed_model_output = parse_model_json(raw_model_text)

        if parsed_model_output:
            final_output = normalize_mitchy_output(
                payload=parsed_model_output,
                local_analysis=local_analysis,
                default_format=default_format,
            )
            final_output["metadata"]["used_gemini"] = True
            final_output["metadata"]["source"] = "gemini"
        else:
            final_output = _build_local_only_output(
                local_analysis=local_analysis,
                default_format=default_format,
            )
            final_output["metadata"]["gemini_error"] = gemini_error or "Could not parse Gemini output"
            final_output["metadata"]["source"] = "gemini_failed_local_fallback"

    else:
        final_output = _build_local_only_output(
            local_analysis=local_analysis,
            default_format=default_format,
        )
        model_name = "local_affective_logic"

    final_output["metadata"].update(
        {
            "topic_id": topic_id,
            "module_id": module_id,
            "screen_context": screen_context,
            "profile_found": bool(profile),
            "content_context_found": bool(content_context.get("topic") or content_context.get("module")),
        }
    )

    raw_model_output_for_db: Dict[str, Any] = {
        "raw_text": raw_model_text,
        "parsed": parsed_model_output,
        "gemini_error": gemini_error,
        "local_analysis": local_analysis,
    }

    log_result = save_mitchy_interaction(
        user_id=user_id,
        user_email=user_email,
        full_name=full_name,
        user_message=clean_message,
        mitchy_response=final_output["response_text"],
        sentiment_score=final_output["sentiment_score"],
        cognitive_load=final_output["cognitive_load"],
        learning_state=final_output["learning_state"],
        suggested_action=final_output["suggested_action"],
        recommended_format=final_output["recommended_format"],
        recommended_format_db=final_output["recommended_format_db"],
        topic_id=topic_id,
        module_id=module_id,
        screen_context=screen_context,
        model_name=model_name,
        raw_model_output=raw_model_output_for_db,
        metadata=final_output["metadata"],
    )

    final_output["metadata"]["logged"] = bool(log_result.get("ok"))

    if log_result.get("session_id"):
        final_output["metadata"]["session_id"] = log_result.get("session_id")

    if not log_result.get("ok"):
        final_output["metadata"]["log_error"] = log_result.get("error")

    return final_output
