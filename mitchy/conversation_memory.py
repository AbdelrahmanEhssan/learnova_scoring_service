from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from mitchy.language_utils import detect_language, normalize_for_intent, response_for_language

try:
    from services.supabase_client import supabase
except Exception:  # pragma: no cover - local import guard
    supabase = None  # type: ignore

BAD_HISTORY_SOURCES = {
    "document_chunks_retrieval_error",
    "gemini_failed_local_fallback",
    "gemini_exception_local_fallback",
    "local_fallback",
    "contextual_local_fallback",
}

CONCEPT_PATTERNS: Dict[str, List[str]] = {
    "data": [r"\bdata\b", r"\braw data\b", r"\bdataset\b", r"\bبيانات\b", r"\bداتا\b"],
    "information": [r"\binformation\b", r"\binfo\b", r"\bمعلومات\b"],
    "knowledge": [r"\bknowledge\b", r"\bمعرفه\b", r"\bمعرفة\b"],
    "data analysis": [r"\bdata analysis\b", r"\bdata analytics\b", r"تحليل البيانات", r"تحليل بيانات"],
    "data engineering": [r"\bdata engineering\b", r"هندسة بيانات", r"هندسه بيانات"],
    "data science": [r"\bdata science\b", r"علم البيانات", r"علم بيانات"],
    "SQL": [r"\bsql\b", r"اس\s*كيو\s*ال", r"اسكيوال"],
    "SQL JOINs": [r"\bjoins?\b", r"\bsql joins?\b", r"جوين", r"ربط جداول"],
    "Python": [r"\bpython\b", r"بايثون"],
    "Power BI": [r"\bpower\s*bi\b", r"\bbi\s*power\b", r"باور\s*بي", r"بور\s*بي", r"bi\s*power"],
    "Excel": [r"\bexcel\b", r"اكسل", r"إكسل"],
    "machine learning": [r"\bmachine learning\b", r"\bml\b", r"تعلم الي", r"تعلم آلي"],
    "statistics": [r"\bstatistics\b", r"\bstats\b", r"احصاء", r"إحصاء"],
    "linear algebra": [r"\blinear algebra\b", r"\bliner algebra\b", r"جبر خطي"],
    "vectors": [r"\bvectors?\b", r"متجهات", r"متجه"],
    "Java": [r"\bjava\b", r"جافا"],
}

DEFINITION_BY_CONCEPT: Dict[str, Dict[str, str]] = {
    "data": {
        "en": "Data is raw facts or values before interpretation, like numbers, names, dates, clicks, or sales records.",
        "ar": "البيانات هي حقائق أو قيم خام قبل التفسير، زي أرقام، أسماء، تواريخ، نقرات، أو سجلات مبيعات.",
    },
    "information": {
        "en": "Information is data after it has been organized or processed so it answers a question or gives meaning.",
        "ar": "المعلومات هي بيانات اتنظمت أو اتعالجت عشان تجاوب على سؤال أو يكون لها معنى واضح.",
    },
    "knowledge": {
        "en": "Knowledge is the understanding you build from information and can use to make decisions or take action.",
        "ar": "المعرفة هي الفهم اللي بتبنيه من المعلومات وتقدر تستخدمه عشان تاخد قرار أو تعمل خطوة.",
    },
    "data analysis": {
        "en": "Data analysis means cleaning data, finding patterns, and turning those patterns into useful decisions.",
        "ar": "تحليل البيانات يعني تنظيف الداتا، اكتشاف الأنماط، وتحويل الأنماط دي لقرارات مفيدة.",
    },
    "SQL": {
        "en": "SQL is the language used to ask databases for data, filter rows, join tables, and summarize results.",
        "ar": "SQL هي اللغة اللي بنستخدمها عشان نطلب بيانات من قواعد البيانات، نفلتر الصفوف، نربط الجداول، ونلخص النتائج.",
    },
    "SQL JOINs": {
        "en": "A JOIN combines rows from related tables, like customers in one table and orders in another.",
        "ar": "الـ JOIN بيربط صفوف من جداول بينهم علاقة، زي جدول عملاء وجدول طلبات.",
    },
    "Power BI": {
        "en": "Power BI is a Microsoft tool for turning data into dashboards and interactive reports that teams can explore and refresh.",
        "ar": "Power BI أداة من Microsoft بتحول البيانات لداشبوردات وتقارير تفاعلية يقدر الفريق يستكشفها ويتابع تحديثها.",
    },
    "Python": {
        "en": "Python is a readable programming language used in data work for cleaning, analysis, automation, visualization, and machine learning.",
        "ar": "Python لغة برمجة سهلة القراءة وبتستخدم في شغل الداتا للتنضيف، التحليل، الأتمتة، الرسم، والـ Machine Learning.",
    },
    "statistics": {
        "en": "Statistics helps you summarize data, understand variation, and make decisions under uncertainty.",
        "ar": "الإحصاء بيساعدك تلخص البيانات، تفهم الاختلافات، وتاخد قرارات مع وجود عدم يقين.",
    },
    "linear algebra": {
        "en": "Linear algebra is the math of vectors and matrices, used to represent many data values at once.",
        "ar": "الجبر الخطي هو رياضيات المتجهات والمصفوفات، وبيستخدم لتمثيل قيم كتير من البيانات مرة واحدة.",
    },
    "Java": {
        "en": "Java is a general-purpose programming language often used for backend systems, Android apps, and enterprise software.",
        "ar": "Java لغة برمجة عامة بتستخدم كتير في أنظمة الباك إند، تطبيقات Android، وبرامج الشركات الكبيرة.",
    },
}


def _parse_action_meta(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _history_source(item: Dict[str, Any]) -> str:
    meta = item.get("metadata") or item.get("mitchy_action") or {}
    meta = _parse_action_meta(meta)
    if isinstance(meta, dict):
        nested = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else meta
        return str(nested.get("source") or "")
    return ""


def _safe_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _role_of(item: Dict[str, Any]) -> str:
    role = str(item.get("role") or "").lower().strip()
    if role in {"user", "student"}:
        return "student"
    if role in {"assistant", "mitchy"}:
        return "mitchy"
    if item.get("user_message"):
        return "pair"
    return "unknown"


def _iter_history_messages(recent_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in recent_history or []:
        if _history_source(item) in BAD_HISTORY_SOURCES:
            continue
        role = _role_of(item)
        if role == "student":
            content = _safe_text(item.get("content") or item.get("message") or item.get("user_message"))
            if content:
                rows.append({"role": "student", "content": content})
        elif role == "mitchy":
            content = _safe_text(item.get("content") or item.get("mitchy_response") or item.get("assistant") or item.get("response"))
            if content:
                rows.append({"role": "mitchy", "content": content})
        elif role == "pair":
            user_message = _safe_text(item.get("user_message") or item.get("user") or item.get("prompt"))
            assistant = _safe_text(item.get("mitchy_response") or item.get("assistant") or item.get("response"))
            if user_message:
                rows.append({"role": "student", "content": user_message})
            if assistant:
                rows.append({"role": "mitchy", "content": assistant})
        else:
            content = _safe_text(item.get("content") or item.get("message"))
            if content:
                rows.append({"role": "unknown", "content": content})
    return rows


def _message_texts_from_history(recent_history: List[Dict[str, Any]]) -> List[str]:
    return [row["content"] for row in _iter_history_messages(recent_history) if row.get("content")]


def _find_concepts_in_text(text: str) -> List[str]:
    normalized = normalize_for_intent(text).lower()
    found: List[str] = []
    for concept, patterns in CONCEPT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                if concept not in found:
                    found.append(concept)
                break
    return found


def extract_recent_concepts(recent_history: List[Dict[str, Any]], limit: int = 4) -> List[str]:
    concepts: List[str] = []
    for text in _message_texts_from_history(recent_history)[-24:]:
        for concept in _find_concepts_in_text(text):
            if concept not in concepts:
                concepts.append(concept)
    return concepts[-limit:]


def last_assistant_response(recent_history: List[Dict[str, Any]]) -> Optional[str]:
    for row in reversed(_iter_history_messages(recent_history)):
        if row.get("role") == "mitchy" and row.get("content"):
            return row["content"]
    return None


def fetch_chat_session_turns(*, user_id: str, session_id: Optional[str] = None, limit: int = 32) -> List[Dict[str, Any]]:
    """Reads the real chat session from Supabase chat_sessions/chat_messages.

    It is intentionally optional and safe: if these tables do not exist or the
    endpoint does not pass session_id yet, Mitchy still works using interaction logs.
    """
    if supabase is None:
        return []
    resolved_session_id = session_id
    try:
        if not resolved_session_id:
            # Prefer latest session for this user. Different schema versions may
            # use updated_at, last_message_at, or created_at.
            for order_col in ("updated_at", "last_message_at", "created_at"):
                try:
                    res = supabase.table("chat_sessions").select("id").eq("user_id", user_id).order(order_col, desc=True).limit(1).execute()
                    rows = getattr(res, "data", None) or []
                    if rows:
                        resolved_session_id = rows[0].get("id")
                        break
                except Exception:
                    continue
        if not resolved_session_id:
            return []
        res = supabase.table("chat_messages").select("role, content, sent_at, mitchy_action").eq("session_id", resolved_session_id).order("sent_at", desc=True).limit(limit).execute()
        rows = list(getattr(res, "data", None) or [])
        rows.reverse()
        return rows
    except Exception:
        return []


def is_followup_reference(message: str) -> bool:
    text = normalize_for_intent(message).lower()
    return bool(re.search(r"\b(both|same|that|it|them|those|again|compare|comparison|difference|simpler|easier|translate)\b", text)) or any(
        phrase in text for phrase in ["الاتنين", "الاتنين دول", "نفس", "ده", "دي", "دول", "قارن", "الفرق", "اشرحها", "اشرحه", "تاني", "نفس الكلام", "ابسط", "أسهل"]
    )


def _is_compare_question(text: str) -> bool:
    lowered = normalize_for_intent(text).lower()
    return bool(re.search(r"\b(compare|comparison|difference|versus|vs|both)\b", lowered)) or any(
        phrase in lowered for phrase in ["قارن", "الفرق", "ايه الفرق", "بين الاتنين", "الاتنين"]
    )


def _is_translate_same_question(text: str) -> Optional[str]:
    lowered = normalize_for_intent(text).lower()
    if re.search(r"\b(same thing|same concept|same answer|translate|in arabic|arabic version|say it in arabic)\b", lowered) or any(p in lowered for p in ["نفس الكلام", "قولها بالعربي", "اشرحها بالعربي", "بالعربي"]):
        return "ar"
    if re.search(r"\b(in english|english version|say it in english|translate.*english|explain.*english)\b", lowered) or any(p in lowered for p in ["بالانجليزي", "بالإنجليزي", "انجليزي"]):
        return "en"
    return None


def _is_simplify_followup(text: str) -> bool:
    lowered = normalize_for_intent(text).lower()
    return bool(re.search(r"\b(make that easier|make it easier|simpler|explain again|explain it again|again)\b", lowered)) or any(p in lowered for p in ["ابسط", "أسهل", "اشرحها تاني", "بسطها"])


def _compare_two_concepts(a: str, b: str, language: str) -> str:
    pair = {a.lower(), b.lower()}
    if pair == {"data", "knowledge"}:
        return response_for_language(
            "Data is the raw facts; knowledge is the understanding you build from processed information so you can make decisions. Example: sales numbers are data, a sales report is information, and knowing which product to focus on next is knowledge.",
            "البيانات هي الحقائق الخام؛ المعرفة هي الفهم اللي بتبنيه من المعلومات عشان تاخد قرار. مثال: أرقام المبيعات بيانات، تقرير المبيعات معلومات، ومعرفتك بأي منتج تركز عليه بعد كده هي معرفة.",
            language,
        )
    if pair == {"data", "information"}:
        return response_for_language(
            "Data is raw facts; information is data after it is organized to answer a question. Example: individual sales rows are data, while total sales per month is information.",
            "البيانات هي حقائق خام؛ المعلومات هي البيانات بعد تنظيمها عشان تجاوب على سؤال. مثال: صفوف المبيعات الفردية بيانات، لكن إجمالي المبيعات لكل شهر معلومات.",
            language,
        )
    if pair == {"information", "knowledge"}:
        return response_for_language(
            "Information tells you what the data means; knowledge is using that meaning to decide what to do. Example: knowing sales dropped is information, knowing you should improve a weak product category is knowledge.",
            "المعلومات بتقولك معنى البيانات؛ المعرفة هي استخدام المعنى ده عشان تقرر تعمل إيه. مثال: معرفة إن المبيعات قلت معلومات، لكن معرفة إنك لازم تحسن فئة منتجات ضعيفة دي معرفة.",
            language,
        )
    left = DEFINITION_BY_CONCEPT.get(a, {}).get(language) or DEFINITION_BY_CONCEPT.get(a, {}).get("en") or f"{a} is the first concept."
    right = DEFINITION_BY_CONCEPT.get(b, {}).get(language) or DEFINITION_BY_CONCEPT.get(b, {}).get("en") or f"{b} is the second concept."
    return response_for_language(f"{left} By contrast, {right}", f"{left} أما {b}: {right}", language)


def _concept_answer(concept: str, language: str, *, prefix: str = "") -> str:
    answer = DEFINITION_BY_CONCEPT.get(concept, {}).get(language) or DEFINITION_BY_CONCEPT.get(concept, {}).get("en")
    if not answer:
        return ""
    return f"{prefix}{answer}" if prefix else answer


def answer_from_conversation_memory(message: str, recent_history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    language = detect_language(message)
    text = normalize_for_intent(message)
    concepts_in_message = _find_concepts_in_text(text)
    recent_concepts = extract_recent_concepts(recent_history, limit=5)

    if _is_compare_question(message):
        concepts: List[str] = []
        for item in concepts_in_message + recent_concepts:
            if item not in concepts:
                concepts.append(item)
        if len(concepts) >= 2:
            response_text = _compare_two_concepts(concepts[-2], concepts[-1], language)
            return {
                "response_text": response_text,
                "learning_state": "curious_inquiry",
                "sentiment_score": 0.0,
                "cognitive_load": 0.25,
                "suggested_action": "answer_question",
                "recommended_format": "textual",
                "recommended_format_db": "Textual",
                "confidence": 0.86,
                "metadata": {"source": "conversation_memory", "used_gemini": False, "detected_language": language, "answered_field": "followup_comparison", "resolved_concepts": concepts[-2:]},
            }

    target_language = _is_translate_same_question(message)
    if target_language:
        concepts = concepts_in_message or recent_concepts
        if concepts:
            concept = concepts[-1]
            response_text = _concept_answer(concept, target_language)
            if response_text:
                return {
                    "response_text": response_text,
                    "learning_state": "progressing",
                    "sentiment_score": 0.0,
                    "cognitive_load": 0.2,
                    "suggested_action": "answer_question",
                    "recommended_format": "textual",
                    "recommended_format_db": "Textual",
                    "confidence": 0.78,
                    "metadata": {"source": "conversation_memory", "used_gemini": False, "detected_language": target_language, "answered_field": "same_concept_language_followup", "resolved_concept": concept},
                }
        # Let the provider handle arbitrary translation/rephrasing with full session memory.
        return None

    if _is_simplify_followup(message):
        concepts = concepts_in_message or recent_concepts
        if concepts:
            concept = concepts[-1]
            response_text = _concept_answer(concept, language)
            if response_text:
                simple_prefix = response_for_language("Simply: ", "ببساطة: ", language)
                return {
                    "response_text": simple_prefix + response_text,
                    "learning_state": "progressing",
                    "sentiment_score": 0.0,
                    "cognitive_load": 0.2,
                    "suggested_action": "rescue_explanation",
                    "recommended_format": "textual",
                    "recommended_format_db": "Textual",
                    "confidence": 0.72,
                    "metadata": {"source": "conversation_memory", "used_gemini": False, "detected_language": language, "answered_field": "simplify_followup", "resolved_concept": concept},
                }
    return None


def build_raw_chat_session_context(recent_history: List[Dict[str, Any]], max_turns: int = 18) -> List[Dict[str, str]]:
    rows = _iter_history_messages(recent_history)
    clean_rows: List[Dict[str, str]] = []
    for row in rows[-max_turns * 2:]:
        role = row.get("role") or "unknown"
        content = _safe_text(row.get("content"))
        if not content:
            continue
        if role not in {"student", "mitchy"}:
            role = "student"
        clean_rows.append({"role": role, "content": content[:700]})
    return clean_rows[-max_turns * 2:]
