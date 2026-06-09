from __future__ import annotations

import re
import unicodedata
from typing import Any

ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

# Common Egyptian Arabic and Arabizi tokens. This is not translation; it is used
# only for routing/language detection so clear Arabic/slang messages do not fall
# into generic fallback.
ARABIZI_TOKENS = {
    "ana", "enta", "enty", "enti", "anty", "yasta", "ya", "mesh", "msh", "fahem", "fahma", "fahm",
    "ezay", "izay", "ezzay", "ezai", "ezaay", "leh", "la2", "ah", "aywa", "aywaaa", "tmm", "tamam",
    "kda", "keda", "da", "de", "di", "el", "mn", "meen", "men", "momken", "mab2ash", "maba2ash",
    "shrah", "eshrah", "tshra7", "shra7", "araby", "3araby", "3raby", "arabic", "bas", "bs", "bardo",
    "mzaekra", "azaker", "zaker", "track", "trak", "msh", "hat3ml", "a3ml", "eh", "eih", "ayh",
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
    " tho ": " though ",
    " rn?": " right now ",
}

ARABIC_NORMALIZATION_MAP = str.maketrans({
    "إ": "ا", "أ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    "ـ": "",
})


def _strip_diacritics(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def has_arabic(text: Any) -> bool:
    return bool(ARABIC_CHAR_RE.search(str(text or "")))


def has_arabizi(text: Any) -> bool:
    raw = str(text or "").lower()
    words = set(re.findall(r"[a-zA-Z0-9]+", raw))
    hits = words & ARABIZI_TOKENS
    # Strong single tokens like yasta/enta/mesh usually indicate Arabizi.
    return len(hits) >= 2 or bool({"yasta", "enta", "enty", "mesh", "msh", "meen", "momken"} & hits)


def detect_language(text: Any) -> str:
    raw = str(text or "")
    if has_arabic(raw) or has_arabizi(raw):
        return "ar"
    return "en"


def normalize_arabic(text: Any) -> str:
    raw = str(text or "").strip().lower()
    raw = _strip_diacritics(raw)
    raw = raw.translate(ARABIC_NORMALIZATION_MAP)
    raw = raw.replace("ال xp", " xp ").replace("ال اكس بي", " xp ")
    raw = raw.replace("اكس بي", " xp ").replace("اكسبي", " xp ")
    raw = raw.replace("باور بي", " power bi ").replace("بور بي", " power bi ")
    raw = raw.replace("اس كيو ال", " sql ").replace("اسكيوال", " sql ")
    return raw


def normalize_for_intent(text: Any) -> str:
    raw = normalize_arabic(text)
    raw = re.sub(r"[؟?!.،,؛:؛\[\]{}()\"'`]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    padded = f" {raw} "

    for src, dst in SLANG_REPLACEMENTS.items():
        padded = padded.replace(src, dst)

    replacements = {
        " who r you ": " who are you ",
        " who are u ": " who are you ",
        " who r u ": " who are you ",
        " how r you ": " how are you ",
        " how are u ": " how are you ",
        " can u ": " can you ",
        " do u ": " do you ",
        " yasta enta meen ": " yasta enta men ",
        " yasta enta men ": " yasta enta men ",
        " enta meen ": " enta men ",
        " ana mesh ": " ana mesh ",
        " liner algebra ": " linear algebra ",
    }
    for src, dst in replacements.items():
        padded = padded.replace(src, dst)

    return re.sub(r"\s+", " ", padded).strip()


def response_for_language(en: str, ar: str, language: str) -> str:
    return ar if language == "ar" else en


def mitchy_identity_text(language: str) -> str:
    return response_for_language(
        "I’m Mitchy, your virtual Learning Assistant in LearNova. I help you understand concepts, decide what to study next, and track your progress clearly.",
        "أنا Mitchy، مساعدك التعليمي الافتراضي في LearNova. أقدر أشرحلك المفاهيم، أقولك تذاكر إيه بعد كده، وأساعدك تتابع تقدمك بوضوح.",
        language,
    )


def language_capability_text(language: str) -> str:
    return response_for_language(
        "Yes, I understand Arabic and English, including casual English and simple Arabizi. I’ll reply in the language you use, unless you ask me to switch.",
        "أيوه، بفهم عربي وإنجليزي، وكمان الإنجليزي العامي والعربيزي البسيط. هرد عليك بنفس اللغة اللي بتكلمني بيها إلا لو طلبت أغيّر اللغة.",
        language,
    )


def gentle_fallback_text(language: str) -> str:
    return response_for_language(
        "I’m here with you. Tell me what you want to understand or what goal you’re working on, and I’ll help clearly.",
        "أنا معاك. قولّي عايز تفهم إيه أو هدفك إيه، وأنا هساعدك بوضوح.",
        language,
    )
