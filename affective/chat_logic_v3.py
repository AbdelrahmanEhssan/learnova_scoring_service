from __future__ import annotations

import json
from typing import Any, Dict

from trend_tracker import get_trend_state
from mitchy_affective_schema_v2 import validate_affective_output
from json_repair import safe_parse_json


NEGATIVE_WORDS = {
    "don't", "dont", "can't", "cant", "stuck", "confused", "hard",
    "frustrated", "annoying", "hate", "again", "wrong", "error", "lost",
    "too much", "overwhelmed", "tired", "exhausted", "eyes hurt", "give up"
}
POSITIVE_WORDS = {
    "got it", "understand", "clear", "thanks", "good", "great", "nice", "worked", "next"
}

CONFUSION_PATTERNS = [
    "what", "why", "how", "i don't get", "i dont get", "still don't get",
    "still dont get", "wait", "confused"
]
FRUSTRATION_PATTERNS = [
    "again", "still not", "error", "frustrated", "this is hard", "annoying", "hate"
]
ANXIOUS_PATTERNS = [
    "where do i start", "too much", "overwhelmed", "so many steps", "this is a lot"
]
CURIOUS_PATTERNS = [
    "what if", "why did", "why do developers", "why build it", "could we instead"
]
FLOW_PATTERNS = ["got it", "next", "that worked", "makes sense", "understand"]
DISTRACTION_PATTERNS = ["brb", "afk", "dog is barking", "be right back", "one sec"]
BURNOUT_PATTERNS = ["my eyes hurt", "been at this for", "4 hours", "exhausted", "tired"]
DISENGAGED_SHORT = {"k", "ok", "okay", "yes", "no", "idk", "sure"}


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def analyze_sentiment(message: str) -> float:
    text = message.lower().strip()
    score = 0.0

    for phrase in POSITIVE_WORDS:
        if phrase in text:
            score += 0.35

    for token in NEGATIVE_WORDS:
        if token in text:
            score -= 0.20

    question_marks = text.count("?")
    if question_marks >= 2:
        score -= 0.15

    if "!" in text and any(p in text for p in FRUSTRATION_PATTERNS):
        score -= 0.15

    return round(_clamp(score), 4)


def estimate_cognitive_load(message: str, sentiment_score: float) -> float:
    text = message.lower().strip()
    clarification_count = sum(1 for p in CONFUSION_PATTERNS if p in text)
    question_marks = text.count("?")
    word_count = len(text.split())

    load = 0.2

    if clarification_count >= 1:
        load += 0.2
    if clarification_count >= 2 or question_marks >= 2:
        load += 0.2
    if word_count > 12:
        load += 0.1
    anxious_hits = sum(1 for p in ANXIOUS_PATTERNS if p in text)
    if anxious_hits >= 1:
        load += 0.4
    if sentiment_score < -0.2:
        load += 0.15
    if sentiment_score < -0.5:
        load += 0.15

    return round(max(0.0, min(load, 1.0)), 4)


def classify_learning_state(message: str, sentiment_score: float, cognitive_load: float) -> str:
    text = message.lower().strip()

    if any(p in text for p in DISTRACTION_PATTERNS):
        return "external_distraction"

    if any(p in text for p in BURNOUT_PATTERNS):
        return "burnout_fatigue"

    if text in DISENGAGED_SHORT:
        return "disengaged"

    if any(p in text for p in CURIOUS_PATTERNS) and sentiment_score >= -0.1:
        return "curious_inquiry"

    if any(p in text for p in FLOW_PATTERNS) and sentiment_score >= 0:
        return "flow_mastered"

    if "obviously" in text or "definitely" in text:
        return "misconception"

    if any(p in text for p in ANXIOUS_PATTERNS) or cognitive_load >= 0.85:
        return "anxious_overwhelmed"

    frustration_hits = sum(1 for p in FRUSTRATION_PATTERNS if p in text)
    if frustration_hits >= 1 and sentiment_score < -0.2 and cognitive_load >= 0.5:
        return "frustrated"

    confusion_hits = sum(1 for p in CONFUSION_PATTERNS if p in text)
    if confusion_hits >= 1 or ("?" in text and cognitive_load >= 0.5):
        return "confused"

    return "disengaged" if sentiment_score <= 0 else "flow_mastered"


def choose_action(learning_state: str, cognitive_load: float, trend_action: str) -> str:
    if trend_action == "take_break":
        return "take_break"

    action_map = {
        "confused": "quiz_review" if cognitive_load >= 0.7 else "none",
        "misconception": "quiz_review",
        "frustrated": "take_break",
        "anxious_overwhelmed": "take_break",
        "curious_inquiry": "none",
        "flow_mastered": "none",
        "disengaged": "none",
        "external_distraction": "none",
        "burnout_fatigue": "take_break",
    }
    return action_map.get(learning_state, "none")


def generate_response_text(learning_state: str, suggested_action: str) -> str:
    if suggested_action == "take_break":
        return "You've been pushing hard. Let's pause for a few minutes, then come back to it one small step at a time."

    responses = {
        "confused": "Let's break it down. Which part feels unclear first?",
        "misconception": "You're close, but one detail is off. Can you walk me through your reasoning step by step?",
        "frustrated": "I can see this is frustrating. Let's slow it down and focus on one tiny piece only.",
        "anxious_overwhelmed": "We do not need to solve everything at once. Let's find the smallest next step together.",
        "curious_inquiry": "That's a great question. Let's explore the idea just a little beyond the core lesson.",
        "flow_mastered": "Nice progress. Want to try one slightly harder example next?",
        "disengaged": "Let's make this simpler and more relevant to your goal.",
        "external_distraction": "No problem. We can pause here and continue from this exact point when you're back.",
        "burnout_fatigue": "You've already done meaningful work. Rest now, and you'll learn better when you return fresh.",
    }
    return responses.get(learning_state, "Let's continue one step at a time.")


def _simulate_llm_affective_json(message: str, sentiment_score: float) -> str:
    cognitive_load = estimate_cognitive_load(message, sentiment_score)
    learning_state = classify_learning_state(message, sentiment_score, cognitive_load)

    payload = {
        "text": "",
        "action": "none",
        "metadata": {
            "learning_state": learning_state,
            "cognitive_load": cognitive_load,
        },
    }
    return json.dumps(payload)


def process_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = str(payload.get("message", "")).strip()
    history = payload.get("history", [])

    if not isinstance(history, list):
        raise TypeError("history must be a list of sentiment scores")

    history = [float(x) for x in history if isinstance(x, (int, float))]

    sentiment_score = analyze_sentiment(message)

    trend_result = get_trend_state(history + [sentiment_score])
    trend_action = trend_result.suggested_action

    llm_output = _simulate_llm_affective_json(message, sentiment_score)
    repaired = safe_parse_json(llm_output)
    validated = validate_affective_output(repaired)

    learning_state = validated["metadata"]["learning_state"]
    cognitive_load = float(validated["metadata"]["cognitive_load"])

    suggested_action = choose_action(learning_state, cognitive_load, trend_action)
    response_text = generate_response_text(learning_state, suggested_action)

    return {
        "response_text": response_text,
        "sentiment_score": round(sentiment_score, 4),
        "cognitive_load": round(cognitive_load, 4),
        "learning_state": learning_state,
        "suggested_action": suggested_action,
    }
