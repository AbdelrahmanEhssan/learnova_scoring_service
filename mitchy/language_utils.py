from __future__ import annotations

import re
from typing import Any


ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

SLANG_REPLACEMENTS = {
    " u ": " you ",
    " r ": " are ",
    " ur ": " your ",
    " ya ": " you are ",
    " yasta ": " bro ",
    " tmm ": " okay ",
    " btw ": " by the way ",
    " idk ": " i do not know ",
    " rn ": " right now ",
    " pls ": " please ",
    " plz ": " please ",
}


def has_arabic(text: Any) -> bool:
    return bool(ARABIC_CHAR_RE.search(str(text or "")))


def detect_language(text: Any) -> str:
    return "ar" if has_arabic(text) else "en"


def normalize_for_intent(text: Any) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"[؟?!.،,]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    padded = f" {raw} "

    for src, dst in SLANG_REPLACEMENTS.items():
        padded = padded.replace(src, dst)

    # direct compact slang variants
    padded = padded.replace(" who r you ", " who are you ")
    padded = padded.replace(" who are u ", " who are you ")
    padded = padded.replace(" who r u ", " who are you ")
    padded = padded.replace(" how r you ", " how are you ")
    padded = padded.replace(" how are u ", " how are you ")
    padded = padded.replace(" can u ", " can you ")
    padded = padded.replace(" do u ", " do you ")

    return re.sub(r"\s+", " ", padded).strip()


def response_for_language(en: str, ar: str, language: str) -> str:
    return ar if language == "ar" else en


def mitchy_identity_text(language: str) -> str:
    return response_for_language(
        "Hi, I’m Mitchy, your virtual Learning Assistant in LearNova. I help you understand lessons, check your progress, track your XP/rank when available, and choose what to study next.",
        "أهلًا، أنا Mitchy، مساعدك التعليمي الافتراضي في LearNova. أقدر أساعدك تفهم الدروس، تتابع تقدمك، وتشوف تدرس إيه بعد كده.",
        language,
    )


def language_capability_text(language: str) -> str:
    return response_for_language(
        "Yes. I can understand English, casual/slang English like “who r u,” and Arabic. I’ll reply in the same language you use unless you ask me to switch.",
        "أيوه، أقدر أفهم العربي والإنجليزي وكمان الاختصارات زي “who r u”. هرد عليك بنفس اللغة اللي بتكلمني بيها إلا لو طلبت تغيّر اللغة.",
        language,
    )


def gentle_fallback_text(language: str) -> str:
    return response_for_language(
        "I’m here with you. Ask me one specific question about your track, progress, XP/rank, or a course concept, and I’ll help step by step.",
        "أنا معاك. اسألني سؤال محدد عن التراك، تقدمك، الـ XP أو الرانك، أو أي مفهوم في الكورس، وأنا أساعدك خطوة بخطوة.",
        language,
    )
