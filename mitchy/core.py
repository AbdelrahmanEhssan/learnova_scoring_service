from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from affective.chat_logic_v3 import process_chat
from mitchy.db import (
    fetch_content_context,
    fetch_recent_mitchy_turns,
    fetch_recent_sentiment_scores,
    fetch_student_profile,
    save_mitchy_interaction,
)
from mitchy.document_retrieval import answer_from_document_chunks
from mitchy.basic_concepts import answer_basic_concept_if_needed
from mitchy.gemini_client import generate_mitchy_json
from mitchy.health_safety import answer_health_safety_if_needed
from mitchy.identity_responses import answer_identity_or_smalltalk_if_needed
from mitchy.parsing import parse_model_json
from mitchy.progress_context import answer_progress_status_question
from mitchy.prompting import build_mitchy_prompt
from mitchy.provider_client import call_backup_provider
from mitchy.language_utils import detect_language, gentle_fallback_text, normalize_for_intent, response_for_language
from mitchy.user_context import build_user_context
from mitchy.schemas import (
    normalize_mitchy_output,
    profile_to_recommended_format,
)


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


def _gemini_enabled() -> bool:
    return os.getenv("MITCHY_GEMINI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _remove_unwanted_opening_greeting(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"^(hey there!?|hi there!?|hello!?|hey!?|hi!?)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _polish_output_for_chat_context(
    output: Dict[str, Any],
    *,
    clean_message: str,
    has_history: bool,
) -> Dict[str, Any]:
    # Avoid repeatedly greeting mid-conversation.
    if has_history and not re.fullmatch(r"\s*(hi+|hey+|hello|salam)\s*[!.?]*\s*", clean_message, flags=re.IGNORECASE):
        output["response_text"] = _remove_unwanted_opening_greeting(output.get("response_text", ""))
    return output


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




def _is_career_or_language_or_identity_like(message: str) -> bool:
    text = normalize_for_intent(message)
    return any(
        phrase in text
        for phrase in (
            "who are you",
            "can you speak arabic",
            "do you understand arabic",
            "where can i work",
            "what is my job",
            "after finishing",
            "data analytics job",
            "career",
        )
    )


def _build_contextual_local_fallback(
    *,
    message: str,
    local_analysis: Dict[str, Any],
    default_format: str,
    user_context: Dict[str, Any],
) -> Dict[str, Any]:
    language = detect_language(message)
    track_label = ((user_context.get("track") or {}).get("track_label") or "your track")

    text = gentle_fallback_text(language)

    if _is_career_or_language_or_identity_like(message):
        text = response_for_language(
            f"I can help, but I don’t want to guess. You are currently connected to the {track_label} path, so ask me about a specific role, topic, XP/rank, or next learning step.",
            f"أقدر أساعدك، بس مش عايز أخمّن. أنت حاليًا مرتبط بمسار {track_label}، فاسألني عن وظيفة معينة، موضوع، XP/رانك، أو الخطوة اللي بعدها.",
            language,
        )

    output = normalize_mitchy_output(
        payload={
            "response_text": text,
            "learning_state": local_analysis.get("learning_state", "curious_inquiry"),
            "suggested_action": local_analysis.get("suggested_action", "none"),
            "recommended_format": default_format,
            "confidence": 0.5,
            "metadata": {
                "source": "contextual_local_fallback",
                "detected_language": language,
            },
        },
        local_analysis=local_analysis,
        default_format=default_format,
    )
    output["metadata"]["used_gemini"] = False
    output["metadata"]["source"] = "contextual_local_fallback"
    return output


def _model_payload_has_text(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False

    response_text = payload.get("response_text") or payload.get("text")

    return isinstance(response_text, str) and bool(response_text.strip())


def _force_non_empty_output(
    output: Dict[str, Any],
    local_analysis: Dict[str, Any],
    source: str,
) -> Dict[str, Any]:
    fallback_text = str(
        local_analysis.get("response_text")
        or "I’m here with you. Ask me one specific question and I’ll help step by step."
    ).strip()

    if not fallback_text:
        fallback_text = "I’m here with you. Ask me one specific question and I’ll help step by step."

    response_text = output.get("response_text")

    if not isinstance(response_text, str) or not response_text.strip():
        output["response_text"] = fallback_text
        output.setdefault("metadata", {})
        output["metadata"]["source"] = source
        output["metadata"]["used_gemini"] = False
        output["metadata"]["forced_non_empty_response"] = True

    return output


def _build_provider_output(
    *,
    response_text: str,
    provider_name: str,
    local_analysis: Dict[str, Any],
    default_format: str,
    gemini_error: Optional[str],
) -> Dict[str, Any]:
    parsed_provider_output = parse_model_json(response_text)

    if parsed_provider_output and _model_payload_has_text(parsed_provider_output):
        output = normalize_mitchy_output(
            payload=parsed_provider_output,
            local_analysis=local_analysis,
            default_format=default_format,
        )
        output["metadata"]["source"] = f"{provider_name}_provider_fallback"
        output["metadata"]["used_gemini"] = False
        output["metadata"]["gemini_error"] = gemini_error
        output["metadata"]["backup_provider"] = provider_name
        return output

    return {
        "response_text": response_text,
        "learning_state": local_analysis.get("learning_state", "curious_inquiry"),
        "sentiment_score": local_analysis.get("sentiment_score", 0.0),
        "cognitive_load": local_analysis.get("cognitive_load", 0.3),
        "suggested_action": local_analysis.get("suggested_action", "none"),
        "recommended_format": default_format,
        "recommended_format_db": str(default_format or "textual").capitalize(),
        "confidence": 0.65,
        "metadata": {
            "source": f"{provider_name}_provider_fallback",
            "used_gemini": False,
            "gemini_error": gemini_error,
            "backup_provider": provider_name,
        },
    }


def _attach_context_metadata(
    output: Dict[str, Any],
    *,
    topic_id: Optional[str],
    module_id: Optional[str],
    screen_context: Optional[str],
    profile: Dict[str, Any],
    content_context: Dict[str, Any],
) -> Dict[str, Any]:
    output.setdefault("metadata", {})
    output["metadata"].update(
        {
            "topic_id": topic_id,
            "module_id": module_id,
            "screen_context": screen_context,
            "profile_found": bool(profile),
            "content_context_found": bool(
                content_context.get("topic") or content_context.get("module")
            ),
        }
    )
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

    Safe routing order:
    1. Fetch student profile and lightweight context.
    2. Run local affective analysis.
    3. Handle health/safety locally without Gemini.
    4. Handle greeting/identity/capability questions locally without document_chunks.
    5. Answer progress/status questions from Supabase DB without Gemini.
    6. Answer course-content questions from document_chunks only if retrieval is strong.
    7. If still needed, call configured non-Gemini providers first.
    8. Gemini is optional and disabled by default for chat completions.
    9. If all providers fail, use local fallback.
    10. Save to chat_sessions/chat_messages/student_sentiment_history.
    """

    clean_message = str(message or "").strip()

    if not clean_message:
        raise ValueError("Message cannot be empty")

    profile = fetch_student_profile(user_id)
    rich_user_context = build_user_context(
        user_id=user_id,
        user_email=user_email,
        full_name=full_name,
        topic_id=topic_id,
        module_id=module_id,
        profile=profile,
    )
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

    # 1. Health/safety guard first. No Gemini.
    health_output = answer_health_safety_if_needed(clean_message)
    if health_output:
        final_output = health_output
        model_name = "local_health_safety_guard"

    else:
        # 2. Greeting / identity / capability questions. No document_chunks.
        identity_output = answer_identity_or_smalltalk_if_needed(
            clean_message,
            has_history=bool(recent_turns),
        )

        if identity_output:
            final_output = identity_output
            model_name = "local_identity_response"

        else:
            # 3. Progress/status DB retrieval. No Gemini.
            progress_output = answer_progress_status_question(
                message=clean_message,
                user_id=user_id,
                topic_id=topic_id,
                module_id=module_id,
            )

            if progress_output:
                final_output = progress_output
                model_name = "db_progress_context"

            else:
                # 4. Common course concepts in English/Arabic/slang. No provider needed.
                basic_concept_output = answer_basic_concept_if_needed(clean_message)

                if basic_concept_output:
                    final_output = basic_concept_output
                    model_name = "local_basic_concept_response"

                else:
                    # 5. Course-content retrieval from document_chunks. No Gemini.
                    document_output = answer_from_document_chunks(
                        message=clean_message,
                        topic_id=topic_id,
                        screen_context=screen_context,
                    )

                    if document_output:
                        final_output = document_output
                        model_name = "document_chunks_retrieval"

                    elif _needs_gemini(clean_message, local_analysis):
                        prompt: Optional[str] = None
    
                        try:
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
                                user_context=rich_user_context,
                            )
    
                            if _gemini_enabled():
                                raw_model_text, gemini_error, model_name = generate_mitchy_json(prompt)
                                parsed_model_output = parse_model_json(raw_model_text)
                            else:
                                raw_model_text = None
                                parsed_model_output = None
                                gemini_error = "Gemini chat completion disabled by MITCHY_GEMINI_ENABLED=false"
                                model_name = None
    
                            if parsed_model_output and _model_payload_has_text(parsed_model_output):
                                final_output = normalize_mitchy_output(
                                    payload=parsed_model_output,
                                    local_analysis=local_analysis,
                                    default_format=default_format,
                                )
                                final_output["metadata"]["used_gemini"] = True
                                final_output["metadata"]["source"] = "gemini"
                            else:
                                backup_text, backup_provider, backup_error = call_backup_provider(prompt)
    
                                if backup_text and backup_provider:
                                    final_output = _build_provider_output(
                                        response_text=backup_text,
                                        provider_name=backup_provider,
                                        local_analysis=local_analysis,
                                        default_format=default_format,
                                        gemini_error=(
                                            gemini_error
                                            or "Gemini returned invalid JSON, partial JSON, or an empty response_text"
                                        ),
                                    )
                                    model_name = backup_provider
                                else:
                                    final_output = _build_contextual_local_fallback(
                                        message=clean_message,
                                        local_analysis=local_analysis,
                                        default_format=default_format,
                                        user_context=rich_user_context,
                                    )
                                    final_output["metadata"]["gemini_error"] = (
                                        gemini_error
                                        or "Gemini returned invalid JSON, partial JSON, or an empty response_text"
                                    )
                                    final_output["metadata"]["backup_provider_error"] = backup_error
                                    final_output["metadata"]["source"] = "gemini_failed_local_fallback"
    
                        except Exception as exc:
                            gemini_error = f"{type(exc).__name__}: {str(exc)}"
    
                            if prompt:
                                backup_text, backup_provider, backup_error = call_backup_provider(prompt)
                            else:
                                backup_text, backup_provider, backup_error = None, None, "Prompt was not built"
    
                            if backup_text and backup_provider:
                                final_output = _build_provider_output(
                                    response_text=backup_text,
                                    provider_name=backup_provider,
                                    local_analysis=local_analysis,
                                    default_format=default_format,
                                    gemini_error=gemini_error,
                                )
                                model_name = backup_provider
                            else:
                                final_output = _build_contextual_local_fallback(
                                    message=clean_message,
                                    local_analysis=local_analysis,
                                    default_format=default_format,
                                    user_context=rich_user_context,
                                )
                                final_output["metadata"]["gemini_error"] = gemini_error
                                final_output["metadata"]["backup_provider_error"] = backup_error
                                final_output["metadata"]["source"] = "gemini_exception_local_fallback"
                                final_output["metadata"]["used_gemini"] = False
                    else:
                        final_output = _build_contextual_local_fallback(
                            message=clean_message,
                            local_analysis=local_analysis,
                            default_format=default_format,
                            user_context=rich_user_context,
                        )
                        model_name = "contextual_local_fallback"

    final_output = _attach_context_metadata(
        final_output,
        topic_id=topic_id,
        module_id=module_id,
        screen_context=screen_context,
        profile=profile,
        content_context=content_context,
    )
    final_output.setdefault("metadata", {})["user_context_attached_to_provider_prompt"] = True

    final_output = _force_non_empty_output(
        output=final_output,
        local_analysis=local_analysis,
        source="final_non_empty_guard",
    )

    final_output = _polish_output_for_chat_context(
        final_output,
        clean_message=clean_message,
        has_history=bool(recent_turns),
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
