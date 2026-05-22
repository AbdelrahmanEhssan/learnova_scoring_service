from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


"""
Schema-aligned Mitchy rescue/adaptation helper.

Current LearNova DB-supported styles:
- Visual
- Auditory
- Textual

Important:
- No kinesthetic output.
- Legacy read_write/readwrite/text labels are normalized to textual.
- Legacy kinesthetic input is safely mapped to textual, but never returned.
- student_profiles.learning_mode supports only: structured, exploration.
"""

SUPPORTED_STYLES = ("visual", "auditory", "textual")

STYLE_TO_DB = {
    "visual": "Visual",
    "auditory": "Auditory",
    "textual": "Textual",
}

DB_TO_STYLE = {
    "Visual": "visual",
    "Auditory": "auditory",
    "Textual": "textual",
}

STYLE_ALIASES = {
    "visual": "visual",
    "video": "visual",
    "visual_video": "visual",
    "diagram": "visual",
    "image": "visual",

    "auditory": "auditory",
    "audio": "auditory",
    "auditory_audio": "auditory",
    "spoken": "auditory",
    "conversation": "auditory",

    "textual": "textual",
    "text": "textual",
    "article": "textual",
    "textual_article": "textual",
    "read_write": "textual",
    "readwrite": "textual",
    "read/write": "textual",
    "reading": "textual",
    "writing": "textual",

    # Backward compatibility only.
    # Do not return kinesthetic. Map it to textual because current DB does not support it.
    "kinesthetic": "textual",
    "kinesthetic_challenge": "textual",
    "hands_on": "textual",
    "practical": "textual",
}

DEFAULT_EXPLORATION_DAYS = 7
DEFAULT_NUDGE_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_MIN_CANDIDATE_STYLE_PCT = 0.60
DEFAULT_MAX_CURRENT_STYLE_PCT = 0.20


def normalize_style(style: Optional[str], default: str = "textual") -> str:
    if not style:
        return default

    normalized = str(style).strip().replace("-", "_").replace(" ", "_")

    if normalized in DB_TO_STYLE:
        return DB_TO_STYLE[normalized]

    normalized = normalized.lower()
    mapped = STYLE_ALIASES.get(normalized, normalized)

    if mapped not in SUPPORTED_STYLES:
        return default

    return mapped


def style_to_db(style: Optional[str]) -> str:
    return STYLE_TO_DB[normalize_style(style)]


def call_llm_api(system_prompt: str, user_query: str) -> str:
    """
    Placeholder LLM call.

    This file should stay lightweight and not import Gemini directly.
    The real Mitchy Gemini call lives in mitchy/gemini_client.py.
    """
    return json.dumps(
        {
            "response_text": (
                "Let's reframe it in a simpler way. First, identify the main idea. "
                "Then follow one step at a time. Which step feels unclear?"
            ),
            "format_used": "textual",
        }
    )


def _alpha_keys_for_style(style: str) -> List[str]:
    """
    Support both current DB names and older in-memory names.
    Current schema:
    - bayesian_alpha_visual
    - bayesian_alpha_auditory
    - bayesian_alpha_textual
    """
    return [
        f"bayesian_alpha_{style}",
        f"{style}_alpha",
    ]


def get_style_alphas(user_profile: Dict[str, Any]) -> Dict[str, float]:
    alphas: Dict[str, float] = {}

    for style in SUPPORTED_STYLES:
        value = None

        for key in _alpha_keys_for_style(style):
            if user_profile.get(key) is not None:
                value = user_profile.get(key)
                break

        try:
            alphas[style] = max(float(value), 1.0) if value is not None else 1.0
        except (TypeError, ValueError):
            alphas[style] = 1.0

    return alphas


def calculate_style_probabilities(user_profile: Dict[str, Any]) -> Dict[str, float]:
    alphas = get_style_alphas(user_profile)
    total = sum(alphas.values()) or float(len(SUPPORTED_STYLES))
    return {style: round(alpha / total, 4) for style, alpha in alphas.items()}


def determine_fallback_format(failed_format: str, user_profile: Dict[str, Any]) -> str:
    failed = normalize_style(failed_format)
    probabilities = calculate_style_probabilities(user_profile)

    candidates = {style: prob for style, prob in probabilities.items() if style != failed}

    if not candidates:
        return "textual" if failed != "textual" else "visual"

    return max(candidates, key=candidates.get)


def _build_format_instruction(target_format: str) -> str:
    target_format = normalize_style(target_format)

    if target_format == "textual":
        return "Use clear short steps, simple definitions, and compact examples."

    if target_format == "visual":
        return "Use spatial language, mental images, small diagrams, or layout-based explanations."

    if target_format == "auditory":
        return "Write conversationally, like a tutor explaining aloud with rhythm and examples."

    return "Use a simple, supportive explanation."


def generate_mitchy_intervention(
    user_query: str,
    topic_name: str,
    failed_format: str,
    user_profile: Dict[str, Any],
) -> Dict[str, Any]:
    failed_format_normalized = normalize_style(failed_format)
    target_format = determine_fallback_format(failed_format_normalized, user_profile)

    system_prompt = f"""
You are Mitchy, the empathetic AI mentor for LearNova.

The learner is struggling with this topic: {topic_name}.
The failed format was: {failed_format_normalized}.

Your mission:
Explain the same concept using the target format: {target_format}.

Format instruction:
{_build_format_instruction(target_format)}

Return strict JSON only with this schema:
{{
  "response_text": "Your empathetic explanation here...",
  "format_used": "{target_format}"
}}

Allowed format_used values:
visual, auditory, textual

Do not use kinesthetic.
""".strip()

    try:
        llm_response_string = call_llm_api(system_prompt, user_query)
        response_data = json.loads(llm_response_string)

        response_text = str(response_data.get("response_text", "")).strip()
        format_used = normalize_style(str(response_data.get("format_used", target_format)))

        if not response_text:
            raise ValueError("LLM returned empty response_text.")

        if format_used not in SUPPORTED_STYLES:
            format_used = target_format

        return {
            "status": "success",
            "mitchy_message": response_text,
            "format_attempted": format_used,
            "format_attempted_db": style_to_db(format_used),
            "failed_format": failed_format_normalized,
            "failed_format_db": style_to_db(failed_format_normalized),
            "bayesian_evidence_pending": True,
        }

    except Exception as exc:
        return {
            "status": "fallback_response_used",
            "mitchy_message": (
                "I know this topic can feel tricky. Let's slow it down. "
                "Tell me the exact step that confused you, and I'll explain it another way."
            ),
            "format_attempted": "textual",
            "format_attempted_db": "Textual",
            "failed_format": failed_format_normalized,
            "failed_format_db": style_to_db(failed_format_normalized),
            "bayesian_evidence_pending": False,
            "error": str(exc),
        }


def should_offer_exploration_nudge(
    drift_signal: Dict[str, Any],
    current_style: str = "visual",
    candidate_style: str = "textual",
    confidence_threshold: float = DEFAULT_NUDGE_CONFIDENCE_THRESHOLD,
    min_candidate_style_pct: float = DEFAULT_MIN_CANDIDATE_STYLE_PCT,
    max_current_style_pct: float = DEFAULT_MAX_CURRENT_STYLE_PCT,
) -> bool:
    current_style = normalize_style(current_style)
    candidate_style = normalize_style(candidate_style)

    current_pct = float(drift_signal.get(f"{current_style}_time_pct", 0.0))
    candidate_pct = float(drift_signal.get(f"{candidate_style}_time_pct", 0.0))

    confidence = float(
        drift_signal.get("confidence_score", drift_signal.get("normalized_confidence", 0.0))
    )

    return (
        current_style != candidate_style
        and current_pct < max_current_style_pct
        and candidate_pct > min_candidate_style_pct
        and confidence > confidence_threshold
    )


def build_exploration_nudge(
    candidate_style: str,
    badge_name: str = "Learning Explorer",
    trial_days: int = DEFAULT_EXPLORATION_DAYS,
) -> Dict[str, Any]:
    candidate_style = normalize_style(candidate_style)
    friendly_style = f"{style_to_db(candidate_style)} Mode"

    return {
        "type": "exploration_nudge",
        "candidate_style": candidate_style,
        "candidate_style_db": style_to_db(candidate_style),
        "trial_days": trial_days,
        "badge_awarded_on_accept": badge_name,
        "message": (
            f"You're engaging a lot with {friendly_style}. "
            f"Want to try {friendly_style} for {trial_days} days?"
        ),
        "primary_action": "Start 7-Day Trial",
        "secondary_action": "Not Now",
    }


def accept_exploration_trial(
    user_profile: Dict[str, Any],
    candidate_style: str,
    now: Optional[datetime] = None,
    trial_days: int = DEFAULT_EXPLORATION_DAYS,
    badge_name: str = "Learning Explorer",
) -> Dict[str, Any]:
    candidate_style = normalize_style(candidate_style)
    now = now or datetime.now(timezone.utc)
    exploration_ends_at = now + timedelta(days=trial_days)

    updated_profile = deepcopy(user_profile)
    updated_profile["exploration_style"] = style_to_db(candidate_style)
    updated_profile["exploration_started_at"] = now.isoformat()
    updated_profile["exploration_ends_at"] = exploration_ends_at.isoformat()

    # Current DB check constraint allows only structured/exploration.
    updated_profile["learning_mode"] = "exploration"

    badges: List[str] = list(updated_profile.get("badges", []))
    if badge_name not in badges:
        badges.append(badge_name)

    updated_profile["badges"] = badges

    return {
        "status": "exploration_started",
        "updated_profile": updated_profile,
        "db_update": {
            "learning_mode": "exploration",
            "exploration_style": style_to_db(candidate_style),
            "exploration_started_at": updated_profile["exploration_started_at"],
            "exploration_ends_at": updated_profile["exploration_ends_at"],
        },
        "badge_awarded": badge_name,
        "confirmation_required_at": updated_profile["exploration_ends_at"],
    }


def build_exploration_confirmation(user_profile: Dict[str, Any]) -> Dict[str, Any]:
    exploration_style = normalize_style(user_profile.get("exploration_style", "textual"))
    friendly_style = f"{style_to_db(exploration_style)} Mode"

    return {
        "type": "exploration_confirmation",
        "candidate_style": exploration_style,
        "candidate_style_db": style_to_db(exploration_style),
        "message": f"Your 7-day {friendly_style} trial is complete. Keep {friendly_style}?",
        "primary_action": f"Keep {friendly_style}",
        "secondary_action": "Return to Previous Mode",
    }


def confirm_exploration_decision(
    user_profile: Dict[str, Any],
    keep_new_style: bool,
) -> Dict[str, Any]:
    updated_profile = deepcopy(user_profile)

    exploration_style = normalize_style(updated_profile.get("exploration_style", "textual"))
    previous_style = normalize_style(
        updated_profile.get("previous_primary_style")
        or updated_profile.get("learning_style")
        or "textual"
    )

    final_style = exploration_style if keep_new_style else previous_style
    status = "exploration_kept_permanent" if keep_new_style else "exploration_reverted"

    updated_profile["learning_style"] = style_to_db(final_style)
    updated_profile["learning_mode"] = "structured"
    updated_profile["exploration_style"] = None
    updated_profile["exploration_started_at"] = None
    updated_profile["exploration_ends_at"] = None

    return {
        "status": status,
        "updated_profile": updated_profile,
        "final_style": final_style,
        "final_style_db": style_to_db(final_style),
        "db_update": {
            "learning_style": style_to_db(final_style),
            "learning_mode": "structured",
            "exploration_style": None,
            "exploration_started_at": None,
            "exploration_ends_at": None,
        },
    }


if __name__ == "__main__":
    dummy_profile = {
        "user_id": "demo_user",
        "learning_style": "Visual",
        "bayesian_alpha_visual": 10,
        "bayesian_alpha_textual": 8,
        "bayesian_alpha_auditory": 2,
        "badges": [],
    }

    rescue_result = generate_mitchy_intervention(
        user_query="I do not understand LEFT JOIN.",
        topic_name="SQL Joins",
        failed_format="visual",
        user_profile=dummy_profile,
    )

    print(json.dumps(rescue_result, indent=2))

    drift_signal = {
        "visual_time_pct": 0.15,
        "textual_time_pct": 0.72,
        "confidence_score": 0.78,
    }

    if should_offer_exploration_nudge(drift_signal):
        nudge = build_exploration_nudge("textual")
        print(json.dumps(nudge, indent=2))

    accepted = accept_exploration_trial(dummy_profile, "textual")
    print(json.dumps(accepted, indent=2))
