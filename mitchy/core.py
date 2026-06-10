from __future__ import annotations

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
from mitchy.basic_concepts import answer_basic_concept_if_needed
from mitchy.conversation_memory import answer_from_conversation_memory, fetch_chat_session_turns
from mitchy.document_retrieval import answer_from_document_chunks
from mitchy.health_safety import answer_health_safety_if_needed
from mitchy.identity_responses import answer_identity_or_smalltalk_if_needed
from mitchy.language_utils import detect_language, gentle_fallback_text, normalize_for_intent, response_for_language
from mitchy.parsing import parse_model_json
from mitchy.progress_context import answer_progress_status_question
from mitchy.prompting import build_mitchy_prompt
from mitchy.provider_client import call_backup_provider
from mitchy.schemas import normalize_mitchy_output, profile_to_recommended_format
from mitchy.user_context import build_user_context

LOW_VALUE_MESSAGES = {"ok", "okay", "k", "yes", "no", "thanks", "thank you", "thx", "brb", "afk"}


def _remove_unwanted_opening_greeting(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^(hey there!?|hi there!?|hello!?|hey!?|hi!?)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned


def _polish_output_for_chat_context(output: Dict[str, Any], *, clean_message: str, has_history: bool) -> Dict[str, Any]:
    if has_history and not re.fullmatch(r"\s*(hi+|hey+|hello|salam|اهلا|سلام)\s*[!.?]*\s*", clean_message, flags=re.IGNORECASE):
        output["response_text"] = _remove_unwanted_opening_greeting(output.get("response_text", ""))
    return output


def _safe_local_analysis(message: str, sentiment_history: list[float]) -> Dict[str, Any]:
    try:
        return process_chat({"message": message, "history": sentiment_history})
    except Exception:
        return {
            "response_text": "Let's slow this down and handle it one small step at a time.",
            "sentiment_score": 0.0,
            "cognitive_load": 0.3,
            "learning_state": "confused",
            "suggested_action": "rescue_explanation",
        }


def _should_call_provider(message: str) -> bool:
    text = normalize_for_intent(message).strip().lower()
    if not text or text in LOW_VALUE_MESSAGES:
        return False
    # At this stage local DB/basic/retrieval handlers did not answer. A real
    # assistant should still try the provider chain before final fallback.
    return True


def _model_payload_has_text(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    response_text = payload.get("response_text") or payload.get("text")
    return isinstance(response_text, str) and bool(response_text.strip())


def _force_non_empty_output(output: Dict[str, Any], local_analysis: Dict[str, Any], source: str, language: str) -> Dict[str, Any]:
    if not isinstance(output.get("response_text"), str) or not output.get("response_text", "").strip():
        output["response_text"] = gentle_fallback_text(language)
        output.setdefault("metadata", {})
        output["metadata"]["source"] = source
        output["metadata"]["used_gemini"] = False
        output["metadata"]["forced_non_empty_response"] = True
    return output


def _build_contextual_local_fallback(*, message: str, local_analysis: Dict[str, Any], default_format: str, user_context: Dict[str, Any]) -> Dict[str, Any]:
    language = detect_language(message)
    text = gentle_fallback_text(language)
    # Make final fallback helpful but not falsely specific.
    if local_analysis.get("learning_state") in {"frustrated", "anxious_overwhelmed", "burnout_fatigue"}:
        text = response_for_language(
            "I get that this feels frustrating. Tell me the exact part that is blocking you, and I’ll break it into one small step.",
            "فاهم إن الموضوع مضايقك. قولّي الجزء اللي موقفك بالظبط، وأنا هقسّمهولك لخطوة صغيرة.",
            language,
        )
    output = normalize_mitchy_output(
        payload={
            "response_text": text,
            "learning_state": local_analysis.get("learning_state", "curious_inquiry"),
            "suggested_action": local_analysis.get("suggested_action", "none"),
            "recommended_format": default_format,
            "confidence": 0.45,
            "metadata": {"source": "contextual_local_fallback", "detected_language": language},
        },
        local_analysis=local_analysis,
        default_format=default_format,
    )
    output["metadata"]["used_gemini"] = False
    output["metadata"]["source"] = "contextual_local_fallback"
    return output


def _build_provider_output(*, response_text: str, provider_name: str, local_analysis: Dict[str, Any], default_format: str, provider_error_context: Optional[str]) -> Dict[str, Any]:
    parsed_provider_output = parse_model_json(response_text)
    if parsed_provider_output and _model_payload_has_text(parsed_provider_output):
        output = normalize_mitchy_output(payload=parsed_provider_output, local_analysis=local_analysis, default_format=default_format)
    else:
        output = {
            "response_text": str(response_text or "").strip(),
            "learning_state": local_analysis.get("learning_state", "curious_inquiry"),
            "sentiment_score": local_analysis.get("sentiment_score", 0.0),
            "cognitive_load": local_analysis.get("cognitive_load", 0.3),
            "suggested_action": local_analysis.get("suggested_action", "none"),
            "recommended_format": default_format,
            "recommended_format_db": str(default_format or "textual").capitalize(),
            "confidence": 0.7,
            "metadata": {},
        }
    output.setdefault("metadata", {})
    output["metadata"].update({
        "source": f"{provider_name}_provider_fallback",
        "used_gemini": provider_name == "gemini",
        "backup_provider": provider_name,
    })
    if provider_error_context:
        output["metadata"]["provider_chain_context"] = provider_error_context
    return output


def _attach_context_metadata(output: Dict[str, Any], *, topic_id: Optional[str], module_id: Optional[str], screen_context: Optional[str], profile: Dict[str, Any], content_context: Dict[str, Any], language: str) -> Dict[str, Any]:
    output.setdefault("metadata", {})
    output["metadata"].update({
        "topic_id": topic_id,
        "module_id": module_id,
        "screen_context": screen_context,
        "profile_found": bool(profile),
        "detected_language": output["metadata"].get("detected_language") or language,
        "content_context_found": bool(content_context.get("topic") or content_context.get("module")),
    })
    return output


def process_mitchy_message(user_id: str, message: str, user_email: Optional[str] = None, full_name: Optional[str] = None, topic_id: Optional[str] = None, module_id: Optional[str] = None, screen_context: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    clean_message = str(message or "").strip()
    if not clean_message:
        raise ValueError("Message cannot be empty")

    language = detect_language(clean_message)
    profile = fetch_student_profile(user_id)
    rich_user_context = build_user_context(user_id=user_id, user_email=user_email, full_name=full_name, topic_id=topic_id, module_id=module_id, profile=profile)
    interaction_turns = fetch_recent_mitchy_turns(user_id=user_id, limit=24)
    session_turns = fetch_chat_session_turns(user_id=user_id, session_id=session_id, limit=36)
    recent_turns = session_turns if session_turns else interaction_turns
    sentiment_history = fetch_recent_sentiment_scores(user_id=user_id, limit=8)
    content_context = fetch_content_context(topic_id=topic_id, module_id=module_id)
    local_analysis = _safe_local_analysis(message=clean_message, sentiment_history=sentiment_history)
    default_format = profile_to_recommended_format(profile)

    raw_model_text: Optional[str] = None
    parsed_model_output: Optional[Dict[str, Any]] = None
    provider_chain_error: Optional[str] = None
    model_name: Optional[str] = None

    # Deterministic handlers first. These must not call providers.
    final_output: Optional[Dict[str, Any]] = answer_health_safety_if_needed(clean_message)
    if final_output:
        model_name = "local_health_safety_guard"
    if final_output is None:
        final_output = answer_identity_or_smalltalk_if_needed(clean_message, has_history=bool(recent_turns))
        if final_output:
            model_name = "local_identity_response"
    if final_output is None:
        final_output = answer_from_conversation_memory(clean_message, recent_turns)
        if final_output:
            model_name = "conversation_memory"
    if final_output is None:
        final_output = answer_progress_status_question(message=clean_message, user_id=user_id, topic_id=topic_id, module_id=module_id)
        if final_output:
            model_name = "db_progress_context"
    if final_output is None:
        final_output = answer_basic_concept_if_needed(clean_message)
        if final_output:
            model_name = "local_basic_concept_response"
    if final_output is None:
        final_output = answer_from_document_chunks(message=clean_message, topic_id=topic_id, screen_context=screen_context)
        if final_output:
            model_name = "document_chunks_retrieval"

    # Provider chain: Groq -> Gemini -> OpenRouter -> xAI by env. Final fallback only after all fail.
    if final_output is None and _should_call_provider(clean_message):
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
            raw_model_text, model_name, provider_chain_error = call_backup_provider(prompt)
            if raw_model_text and model_name:
                parsed_model_output = parse_model_json(raw_model_text)
                final_output = _build_provider_output(response_text=raw_model_text, provider_name=model_name, local_analysis=local_analysis, default_format=default_format, provider_error_context=provider_chain_error)
        except Exception as exc:
            provider_chain_error = f"provider_chain_exception: {type(exc).__name__}: {str(exc)}"

    if final_output is None:
        final_output = _build_contextual_local_fallback(message=clean_message, local_analysis=local_analysis, default_format=default_format, user_context=rich_user_context)
        model_name = "contextual_local_fallback"
        if provider_chain_error:
            final_output["metadata"]["provider_chain_error"] = provider_chain_error

    final_output = _attach_context_metadata(final_output, topic_id=topic_id, module_id=module_id, screen_context=screen_context, profile=profile, content_context=content_context, language=language)
    final_output.setdefault("metadata", {})["user_context_attached_to_provider_prompt"] = True
    if session_id:
        final_output["metadata"]["request_session_id"] = session_id
    final_output["metadata"]["chat_session_memory_attached"] = bool(session_turns)
    final_output = _force_non_empty_output(final_output, local_analysis, source="final_non_empty_guard", language=language)
    final_output = _polish_output_for_chat_context(final_output, clean_message=clean_message, has_history=bool(recent_turns))

    raw_model_output_for_db: Dict[str, Any] = {"raw_text": raw_model_text, "parsed": parsed_model_output, "provider_chain_error": provider_chain_error, "local_analysis": local_analysis}
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
