from __future__ import annotations

import re
from typing import Any, Dict, Optional

from mitchy.language_utils import detect_language, normalize_for_intent, response_for_language


def _output(text: str, *, language: str, concept: str) -> Dict[str, Any]:
    return {
        "response_text": text,
        "learning_state": "curious_inquiry",
        "sentiment_score": 0.0,
        "cognitive_load": 0.25,
        "suggested_action": "answer_question",
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": 0.82,
        "metadata": {"source": "local_basic_concept_response", "used_gemini": False, "detected_language": language, "concept": concept},
    }


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def answer_basic_concept_if_needed(message: str) -> Optional[Dict[str, Any]]:
    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)

    if not text:
        return None

    # Arabic / English concept explanations that should never fall into the generic fallback.
    if _has_any(text, [r"تحليل\s+بيانات", r"تحليل\s+البيانات", r"data\s+analysis", r"data\s+analytics"]):
        return _output(
            response_for_language(
                "Data analysis means taking raw data, cleaning it, finding patterns, and turning it into useful decisions. For example, a company can analyze sales data to know which product is performing best and why.",
                "تحليل البيانات يعني إنك تاخد بيانات خام، تنظفها، تدور على الأنماط المهمة فيها، وتحولها لقرار مفيد. مثال: شركة تحلل المبيعات عشان تعرف أنهي منتج شغال أحسن وليه.",
                language,
            ),
            language=language,
            concept="data_analysis",
        )

    if _has_any(text, [r"\bsql\b", r"اس\s*كيو\s*ال"]):
        return _output(
            response_for_language(
                "SQL is the language used to ask databases for data. You use it to select rows, filter results, join tables, and summarize information.",
                "SQL هي اللغة اللي بنستخدمها عشان نطلب بيانات من قواعد البيانات. بتستخدمها تجيب صفوف، تعمل فلترة، تربط جداول، وتلخص معلومات.",
                language,
            ),
            language=language,
            concept="sql",
        )

    if _has_any(text, [r"joins?", r"جوين", r"ربط\s+جداول"]):
        return _output(
            response_for_language(
                "A JOIN combines rows from two related tables. For example, one table can store customers and another stores orders; a JOIN lets you see each order with the customer who made it.",
                "الـ JOIN بيربط صفوف من جدولين بينهم علاقة. مثال: جدول للعملاء وجدول للطلبات؛ الـ JOIN يخليك تشوف كل طلب مع العميل اللي عمله.",
                language,
            ),
            language=language,
            concept="sql_join",
        )

    if _has_any(text, [r"linear\s+algebra", r"liner\s+algebra", r"لينير", r"جبر\s+خطي"]):
        return _output(
            response_for_language(
                "Linear algebra is the math of vectors and matrices. In data and machine learning, it helps represent many values at once, like a row of features for a user, product, or image.",
                "الجبر الخطي هو رياضيات المتجهات والمصفوفات. في الداتا والـ Machine Learning بيساعدنا نمثل قيم كتير مرة واحدة، زي صف فيه خصائص مستخدم أو منتج أو صورة.",
                language,
            ),
            language=language,
            concept="linear_algebra",
        )

    if _has_any(text, [r"power\s*bi", r"باور\s*بي"]):
        return _output(
            response_for_language(
                "Power BI is a tool for building interactive dashboards and reports. It helps turn data into charts that business teams can understand and use for decisions.",
                "Power BI أداة لعمل داشبوردات وتقارير تفاعلية. بتساعدك تحول البيانات لرسومات وتقارير سهلة يفهمها فريق الشغل ويستخدمها في القرار.",
                language,
            ),
            language=language,
            concept="power_bi",
        )

    if _has_any(text, [r"python", r"بايثون"]):
        return _output(
            response_for_language(
                "Python is a programming language used a lot in data work because it is readable and has strong libraries for cleaning, analysis, visualization, automation, and machine learning.",
                "Python لغة برمجة مستخدمة جدًا في شغل الداتا لأنها سهلة القراءة وفيها مكتبات قوية للتنضيف، التحليل، الرسم، الأتمتة، والـ Machine Learning.",
                language,
            ),
            language=language,
            concept="python",
        )

    if _has_any(text, [r"data\s+cleaning", r"تنضيف\s+البيانات", r"تنظيف\s+البيانات"]):
        return _output(
            response_for_language(
                "Data cleaning means fixing messy data before analysis: removing duplicates, handling missing values, correcting types, and making columns consistent.",
                "تنضيف البيانات يعني تصلّح البيانات قبل التحليل: تشيل التكرار، تتعامل مع القيم الناقصة، تصلح الأنواع، وتخلي الأعمدة متناسقة.",
                language,
            ),
            language=language,
            concept="data_cleaning",
        )

    return None
