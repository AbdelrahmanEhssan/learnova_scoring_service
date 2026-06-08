from __future__ import annotations

import re
from typing import Any


ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

# Common Egyptian/Arabizi tokens. This is not translation; it is only used to
# detect and route casual Arabic written in Latin letters.
ARABIZI_TOKENS = {
    "ana", "enta", "enty", "enti", "yasta", "ya", "mesh", "msh", "fahem", "fahma",
    "ezay", "izay", "ezzay", "leh", "la2", "ah", "aywa", "tmm", "tamam", "kda", "keda",
    "da", "el", "mn", "meen", "men", "momken", "shrah", "eshrah", "tshra7", "araby", "arabic",
}

SLANG_REPLACEMENTS = {
    " u ": " you ",
    " r ": " are ",
    " ur ": " your ",
    " rn ": " right now ",
    " idk ": " i do not know ",
    " ngl ": " not gonna lie ",
    " btw ": " by the way ",
    " pls ": " please ",
    " plz ": " please ",
    " cuz ": " because ",
    " bc ": " because ",
}


def has_arabic(text: Any) -> bool:
    return bool(ARABIC_CHAR_RE.search(str(text or "")))


def has_arabizi(text: Any) -> bool:
    raw = str(text or "").lower()
    words = set(re.findall(r"[a-zA-Z0-9]+", raw))
    # One strong word like yasta/enta + another token is usually enough.
    hits = words & ARABIZI_TOKENS
    return len(hits) >= 2 or bool({"yasta", "enta", "enty", "mesh", "msh"} & hits)


def detect_language(text: Any) -> str:
    raw = str(text or "")
    if has_arabic(raw) or has_arabizi(raw):
        return "ar"
    return "en"


def normalize_for_intent(text: Any) -> str:
    raw = str(text or "").strip().lower()
    raw = raw.replace("إ", "ا").replace("أ", "ا").replace("آ", "ا")
    raw = raw.replace("ى", "ي").replace("ة", "ه")
    raw = re.sub(r"[؟?!.،,؛:]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    padded = f" {raw} "

    for src, dst in SLANG_REPLACEMENTS.items():
        padded = padded.replace(src, dst)

    # compact slang variants
    replacements = {
        " who r you ": " who are you ",
        " who are u ": " who are you ",
        " who r u ": " who are you ",
        " how r you ": " how are you ",
        " how are u ": " how are you ",
        " can u ": " can you ",
        " do u ": " do you ",
        " tell me ": " tell me ",
        " yasta enta meen ": " yasta enta men ",
        " yasta enta men ": " yasta enta men ",
    }
    for src, dst in replacements.items():
        padded = padded.replace(src, dst)

    return re.sub(r"\s+", " ", padded).strip()


def response_for_language(en: str, ar: str, language: str) -> str:
    return ar if language == "ar" else en


def mitchy_identity_text(language: str) -> str:
    return response_for_language(
        "I’m Mitchy, your virtual Learning Assistant in LearNova. I can explain concepts, guide what to study next, and help you understand your progress without making things complicated.",
        "أنا Mitchy، مساعدك التعليمي الافتراضي في LearNova. أقدر أشرحلك المفاهيم، أقولك تذاكر إيه بعد كده، وأساعدك تفهم تقدمك بطريقة بسيطة.",
        language,
    )


def language_capability_text(language: str) -> str:
    return response_for_language(
        "Yes, I understand Arabic and English, including casual/slang English like “who r u” and simple Arabizi. I’ll usually reply in the same language you use.",
        "أيوه، بفهم عربي وإنجليزي، وكمان الاختصارات زي “who r u” والعربيزي البسيط. غالبًا هرد عليك بنفس اللغة اللي بتكلمني بيها.",
        language,
    )


def gentle_fallback_text(language: str) -> str:
    return response_for_language(
        "I’m with you. Send the concept, lesson, or goal you want help with, and I’ll guide you step by step.",
        "أنا معاك. ابعتلي المفهوم، الدرس، أو الهدف اللي محتاج مساعدة فيه، وأنا أوضحلك خطوة بخطوة.",
        language,
    )
