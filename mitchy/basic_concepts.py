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
        "confidence": 0.86,
        "metadata": {"source": "local_basic_concept_response", "used_gemini": False, "detected_language": language, "concept": concept},
    }


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _has_start_intent(text: str) -> bool:
    return _has_any(text, [
        r"\bwhere\s+(do|should|can)\s+i\s+start\b",
        r"\bhow\s+(do|should|can)\s+i\s+start\b",
        r"\bstart\s+(with|learning|studying)\b",
        r"\bfocus\s+on\b",
        r"\bi\s+want\s+to\s+focus\s+on\b",
        r"\bstuck\b",
        r"\bnot\s+understand\b",
        r"\bمش\s+فاهم\b",
        r"\bنبدأ\b",
        r"\bنبدا\b",
        r"\bأبدأ\b",
        r"\bابدأ\b",
        r"\bابدا\b",
    ])


def answer_basic_concept_if_needed(message: str) -> Optional[Dict[str, Any]]:
    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)
    if not text:
        return None

    if _has_any(text, [r"\bwhat\s+is\s+data\b", r"\bdefine\s+data\b", r"يعني\s+ايه\s+داتا", r"يعني\s+ايه\s+بيانات", r"ما\s+هي\s+البيانات"]):
        return _output(response_for_language(
            "Data is raw facts or values before interpretation, like sales numbers, dates, names, clicks, or survey answers.",
            "البيانات هي حقائق أو قيم خام قبل تفسيرها، زي أرقام مبيعات، تواريخ، أسماء، نقرات، أو إجابات استبيان.",
            language), language=language, concept="data")

    if _has_any(text, [r"\bwhat\s+is\s+knowledge\b", r"\bdefine\s+knowledge\b", r"يعني\s+ايه\s+معرفه", r"يعني\s+ايه\s+معرفة", r"ما\s+هي\s+المعرفة"]):
        return _output(response_for_language(
            "Knowledge is the understanding you build from information and use to make decisions or take action.",
            "المعرفة هي الفهم اللي بتبنيه من المعلومات وتستخدمه عشان تاخد قرار أو تعمل خطوة.",
            language), language=language, concept="knowledge")

    if _has_any(text, [r"\bwhat\s+is\s+information\b", r"\bdefine\s+information\b", r"يعني\s+ايه\s+معلومات", r"ما\s+هي\s+المعلومات"]):
        return _output(response_for_language(
            "Information is data after it has been organized or processed so it becomes meaningful and useful.",
            "المعلومات هي البيانات بعد ما تتنظم أو تتعالج فتكون مفهومة ومفيدة.",
            language), language=language, concept="information")

    if _has_any(text, [r"تحليل\s+بيانات", r"تحليل\s+البيانات", r"data\s+analysis", r"data\s+analytics"]):
        return _output(response_for_language(
            "Data analysis means taking raw data, cleaning it, finding patterns, and turning it into useful decisions. For example, a company can analyze sales data to know which product performs best and why.",
            "تحليل البيانات يعني إنك تاخد بيانات خام، تنظفها، تدور على الأنماط المهمة، وتحولها لقرار مفيد. مثال: شركة تحلل المبيعات عشان تعرف أنهي منتج شغال أحسن وليه.",
            language), language=language, concept="data_analysis")

    if _has_any(text, [r"data\s+cleaning", r"cleaning\s+data", r"تنضيف\s+البيانات", r"تنظيف\s+البيانات", r"cleaning"]):
        return _output(response_for_language(
            "Data cleaning means fixing messy data before analysis: removing duplicates, handling missing values, correcting data types, and making columns consistent.",
            "تنضيف البيانات يعني تصلّح الداتا قبل التحليل: تشيل التكرار، تتعامل مع القيم الناقصة، تصلح أنواع البيانات، وتخلي الأعمدة متناسقة.",
            language), language=language, concept="data_cleaning")

    if _has_any(text, [r"\bsql\b", r"اس\s*كيو\s*ال"]):
        if _has_start_intent(text):
            return _output(response_for_language(
                "To start SQL, do this: 1) understand table, row, and column; 2) write one SELECT query; 3) add a WHERE filter; 4) then practice JOINs with two tiny tables.",
                "عشان تبدأ SQL: 1) افهم يعني إيه table و row و column؛ 2) اكتب SELECT بسيط؛ 3) ضيف WHERE filter؛ 4) بعدها اتدرب على JOIN بجدولين صغيرين.",
                language), language=language, concept="sql_start_plan")
        if _has_any(text, [r"\bsql\s+joins?\b", r"\bjoins?\b", r"\bjoin\b", r"جوين", r"ربط\s+جداول"]):
            return _output(response_for_language(
                "A JOIN combines rows from related tables. Example: customers are in one table and orders are in another; a JOIN lets you see each order with the customer who made it.",
                "الـ JOIN بيربط صفوف من جداول بينها علاقة. مثال: جدول للعملاء وجدول للطلبات؛ الـ JOIN يخليك تشوف كل طلب مع العميل اللي عمله.",
                language), language=language, concept="sql_join")
        return _output(response_for_language(
            "SQL is the language used to ask databases for data. You use it to select rows, filter results, join tables, and summarize information.",
            "SQL هي اللغة اللي بنستخدمها عشان نطلب بيانات من قواعد البيانات. بتستخدمها تجيب صفوف، تعمل فلترة، تربط جداول، وتلخص معلومات.",
            language), language=language, concept="sql")

    if _has_any(text, [r"joins?", r"join\b", r"جوين", r"ربط\s+جداول"]):
        return _output(response_for_language(
            "A JOIN is useful when the answer needs data from more than one table. If all the columns you need are already in one table, you usually do not need a JOIN.",
            "الـ JOIN بتستخدمه لما الإجابة محتاجة بيانات من أكتر من جدول. لو كل الأعمدة اللي محتاجها موجودة في جدول واحد، غالبًا مش محتاج JOIN.",
            language), language=language, concept="sql_join")

    if _has_any(text, [r"linear\s+algebra", r"liner\s+algebra", r"vectors?", r"لينير", r"جبر\s+خطي", r"متجهات"]):
        if _has_any(text, [r"machine\s+learning", r"ml", r"تعلم\s+الي"]):
            return _output(response_for_language(
                "Vectors matter in machine learning because models need numbers, not raw ideas. A vector can represent a user, image, product, or sentence as features the model can compare and learn from.",
                "المتجهات مهمة في الـ Machine Learning لأن الموديل بيتعامل مع أرقام. المتجه ممكن يمثل مستخدم، صورة، منتج، أو جملة كخصائص رقمية يتعلم منها الموديل.",
                language), language=language, concept="vectors_ml")
        return _output(response_for_language(
            "Linear algebra is the math of vectors and matrices. In data work, it helps represent many values at once, like a row of features for a user, product, or image.",
            "الجبر الخطي هو رياضيات المتجهات والمصفوفات. في شغل الداتا بيساعدنا نمثل قيم كتير مرة واحدة، زي خصائص مستخدم أو منتج أو صورة.",
            language), language=language, concept="linear_algebra")

    if _has_any(text, [r"power\s*bi", r"bi\s*power", r"باور\s*بي", r"بور\s*بي"]):
        if _has_start_intent(text):
            return _output(response_for_language(
                "To start Power BI, do this: 1) load a small dataset; 2) clean column names; 3) create one chart; 4) add one slicer; 5) avoid advanced DAX at the beginning.",
                "عشان تبدأ Power BI: 1) حمّل dataset صغيرة؛ 2) نظف أسماء الأعمدة؛ 3) اعمل chart واحد؛ 4) ضيف slicer واحد؛ 5) متبدأش بـ DAX المتقدم في الأول.",
                language), language=language, concept="power_bi_start_plan")
        return _output(response_for_language(
            "Power BI is a Microsoft tool for turning data into interactive dashboards and reports that teams can explore and refresh.",
            "Power BI أداة من Microsoft بتحول البيانات لداشبوردات وتقارير تفاعلية يقدر الفريق يستكشفها ويتابع تحديثها.",
            language), language=language, concept="power_bi")

    if _has_any(text, [r"python", r"بايثون"]):
        return _output(response_for_language(
            "Python is popular in data work because it is readable and has strong libraries for cleaning, analysis, visualization, automation, and machine learning.",
            "Python مشهورة في شغل الداتا لأنها سهلة القراءة وفيها مكتبات قوية للتنضيف، التحليل، الرسم، الأتمتة، والـ Machine Learning.",
            language), language=language, concept="python")

    if _has_any(text, [r"training\s+a\s+model", r"testing\s+a\s+model", r"train\s+.*test", r"تدريب\s+الموديل", r"اختبار\s+الموديل"]):
        return _output(response_for_language(
            "Training a model means letting it learn patterns from data. Testing a model means checking those learned patterns on new data it has not seen before, so we know if it generalizes.",
            "تدريب الموديل يعني نخليه يتعلم أنماط من الداتا. اختبار الموديل يعني نشوف أداءه على داتا جديدة مشافهاش قبل كده عشان نعرف هل فهم فعلًا ولا حفظ.",
            language), language=language, concept="train_test_split")

    if _has_any(text, [r"data\s+analyst\s+actually\s+do", r"day\s+to\s+day", r"data\s+analyst\s+do"]):
        return _output(response_for_language(
            "A data analyst cleans data, writes queries, builds dashboards, finds trends, and explains what the numbers mean so teams can make better decisions.",
            "محلل البيانات بينضف الداتا، يكتب استعلامات، يبني داشبوردات، يطلع تريندات، ويشرح الأرقام عشان الفرق تاخد قرارات أحسن.",
            language), language=language, concept="data_analyst_daily_work")


    if _has_any(text, [r"\bjava\b", r"جافا"]):
        return _output(response_for_language(
            "Java is a general-purpose programming language used for backend systems, Android apps, enterprise software, and large applications. It may not be the main focus of your current LearNova path, but the idea is similar to Python: you write instructions that the computer can run.",
            "Java لغة برمجة عامة بتستخدم في الباك إند، تطبيقات Android، وبرامج الشركات الكبيرة. ممكن ما تكونش محور مسارك الحالي في LearNova، لكنها زي Python في الفكرة العامة: بتكتب تعليمات الكمبيوتر ينفذها.",
            language), language=language, concept="java_general")

    return None
