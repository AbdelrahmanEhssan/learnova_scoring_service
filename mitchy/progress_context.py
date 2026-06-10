from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from mitchy.db import fetch_content_context, fetch_student_profile
from mitchy.language_utils import detect_language, normalize_for_intent, response_for_language
from mitchy.user_context import build_user_context
from services.supabase_client import supabase

TRACK_LABELS = {
    "DA": "Data Analytics",
    "DE": "Data Engineering",
    "DS": "Data Science",
    "Foundation": "Foundation",
    "dip_data_analytics": "Data Analytics",
    "dip_data_engineering": "Data Engineering",
    "dip_data_science": "Data Science",
}

TRACK_TO_COURSE_KEYS = {
    "DA": ["DA", "Data Analytics", "dip_data_analytics"],
    "DE": ["DE", "Data Engineering", "dip_data_engineering"],
    "DS": ["DS", "Data Science", "dip_data_science"],
}

TRACK_TO_COURSE_TITLES = {
    "DA": ["Data Analytics", "Analytics"],
    "DE": ["Data Engineering", "Engineering"],
    "DS": ["Data Science", "Science"],
}

CAREER_BY_TRACK = {
    "DA": {
        "label": "Data Analytics",
        "jobs": ["Data Analyst", "Business Intelligence Analyst", "Reporting Analyst", "Product Analyst", "Marketing/Data Insights Analyst"],
        "work": "clean data, analyze trends, build dashboards, explain insights, and help teams make decisions",
        "skills": "SQL, Excel/Power BI, Python, data cleaning, visualization, and storytelling with data",
        "project": "a dashboard/reporting project that cleans a dataset, analyzes trends, and presents insights in Excel, Power BI, or Python",
    },
    "DE": {
        "label": "Data Engineering",
        "jobs": ["Data Engineer", "Analytics Engineer", "ETL/ELT Developer", "Data Platform Engineer", "Pipeline Engineer"],
        "work": "build pipelines, manage databases/warehouses, automate data movement, and make data reliable",
        "skills": "SQL, Python, Linux, data pipelines, databases, ETL/ELT, and cloud/data warehouse basics",
        "project": "an ETL pipeline project that extracts data, cleans it, loads it into a database, and schedules the process",
    },
    "DS": {
        "label": "Data Science",
        "jobs": ["Data Scientist", "Machine Learning Engineer", "ML Analyst", "AI/ML Specialist", "Research/Data Science Analyst"],
        "work": "build models, test hypotheses, evaluate predictions, and turn data into intelligent products or decisions",
        "skills": "statistics, Python, machine learning, model evaluation, visualization, and data storytelling",
        "project": "a machine-learning project that explores a dataset, trains a model, evaluates it, and explains the results",
    },
}


def _is_uuid(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _matches_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _safe_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _first_row(data: Any) -> Dict[str, Any]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def _output(text: str, metadata: Dict[str, Any], *, language: str = "en", action: str = "none") -> Dict[str, Any]:
    return {
        "response_text": text,
        "learning_state": "progressing",
        "sentiment_score": 0.0,
        "cognitive_load": 0.2,
        "suggested_action": action,
        "recommended_format": "textual",
        "recommended_format_db": "Textual",
        "confidence": 0.9,
        "metadata": {"source": "db_progress_context", "used_gemini": False, "detected_language": language, **metadata},
    }


def _normalize_track(track: Any) -> Optional[str]:
    raw = str(track or "").strip()
    lowered = raw.lower()
    if raw in {"DA", "DE", "DS"}:
        return raw
    if "analytics" in lowered or raw == "dip_data_analytics":
        return "DA"
    if "engineering" in lowered or raw == "dip_data_engineering":
        return "DE"
    if "science" in lowered or raw == "dip_data_science":
        return "DS"
    return None


def _latest_position(user_id: str) -> Dict[str, Any]:
    profile = fetch_student_profile(user_id)
    return {
        "profile": profile,
        "assigned_track": profile.get("assigned_track"),
        "learning_style": profile.get("learning_style"),
        "learning_mode": profile.get("learning_mode"),
        "current_level_index": profile.get("current_level_index"),
        "xp_total": profile.get("xp_total") or profile.get("xp_points") or profile.get("total_xp") or profile.get("xp"),
    }


def _fetch_course_for_track(track_code: Optional[str]) -> Dict[str, Any]:
    if not track_code:
        return {}
    for candidate in TRACK_TO_COURSE_KEYS.get(track_code, [track_code]):
        try:
            row = _first_row(supabase.table("courses").select("id, track, title, description, order_index, is_foundation, is_active").eq("track", candidate).eq("is_active", True).limit(1).execute().data)
            if row.get("id"):
                return row
        except Exception:
            pass
    for title_part in TRACK_TO_COURSE_TITLES.get(track_code, []):
        try:
            row = _first_row(supabase.table("courses").select("id, track, title, description, order_index, is_foundation, is_active").ilike("title", f"%{title_part}%").eq("is_active", True).limit(1).execute().data)
            if row.get("id"):
                return row
        except Exception:
            pass
    return {}


def _fetch_rows(table: str, select: str, column: str, value: str) -> List[Dict[str, Any]]:
    try:
        res = supabase.table(table).select(select).eq(column, value).eq("is_active", True).order("order_index").execute()
        return _safe_rows(res.data)
    except Exception:
        return []


def _fetch_learning_path(track_code: Optional[str]) -> Dict[str, Any]:
    course = _fetch_course_for_track(track_code)
    if not course.get("id"):
        return {"course": course, "levels": [], "modules": [], "topics": []}
    levels = _fetch_rows("levels", "id, course_id, title, order_index, xp_reward, is_active", "course_id", course["id"])
    modules: List[Dict[str, Any]] = []
    topics: List[Dict[str, Any]] = []
    for level in levels:
        level_modules = _fetch_rows("modules", "id, level_id, title, order_index, xp_reward, is_active", "level_id", level.get("id"))
        for module in level_modules:
            module["level_title"] = level.get("title")
            module["level_order_index"] = level.get("order_index")
            modules.append(module)
            module_topics = _fetch_rows("topics", "id, module_id, title, order_index, xp_reward, is_active", "module_id", module.get("id"))
            for topic in module_topics:
                topic["module_title"] = module.get("title")
                topic["module_order_index"] = module.get("order_index")
                topic["level_title"] = level.get("title")
                topic["level_order_index"] = level.get("order_index")
                topics.append(topic)
    return {"course": course, "levels": levels, "modules": modules, "topics": topics}


def _format_topic_list(topics: List[Dict[str, Any]], *, limit: int = 5, language: str = "en") -> str:
    lines: List[str] = []
    for index, topic in enumerate(topics[:limit], start=1):
        module_title = topic.get("module_title") or "module"
        topic_title = topic.get("title") or "Untitled topic"
        lines.append(f"{index}. {topic_title} ({module_title})")
    return "\n".join(lines)


def _track_and_path(user_id: str, text: str) -> tuple[Dict[str, Any], Optional[str], str, Dict[str, Any]]:
    position = _latest_position(user_id)
    track_code = _normalize_track(position.get("assigned_track"))
    if "data analytics" in text or "داتا اناليتكس" in text or "تحليل البيانات" in text:
        track_code = "DA"
    elif "data engineering" in text or "هندسه بيانات" in text or "هندسة بيانات" in text:
        track_code = "DE"
    elif "data science" in text or "علم بيانات" in text:
        track_code = "DS"
    track_label = TRACK_LABELS.get(track_code or "", track_code or "your assigned track")
    return position, track_code, track_label, _fetch_learning_path(track_code)


def _answer_xp_system_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:
    if not _matches_any(text, [
        r"\bhow\s+.*\bxp\b.*\b(calculated|work|earn|system)\b", r"\bxp\s+system\b", r"\bhow\s+is\s+xp\s+calculated\b",
        r"نظام\s+.*xp", r"ازاي\s+.*xp", r"ازاى\s+.*xp", r"بيتم\s+.*(حسب|حساب).*xp", r"xp\s+بيتحسب", r"اكسب\s+xp",
    ]):
        return None
    context = build_user_context(user_id=user_id)
    xp_total = (context.get("gamification") or {}).get("xp_total")
    text_out = response_for_language(
        "XP in LearNova is earned from completed learning actions: finishing resources, quizzes, challenges, and progress activities. Each action has a reward set by the platform, then your total XP is the sum of approved rewards.",
        "الـ XP في LearNova بيتحسب من أنشطة التعلم اللي بتكملها: الموارد، الكويزات، التحديات، وأنشطة التقدم. كل نشاط له مكافأة محددة في النظام، ومجموع المكافآت المعتمدة هو إجمالي الـ XP بتاعك.",
        language,
    )
    if xp_total is not None:
        text_out += response_for_language(f" I can currently see {xp_total} XP on your account.", f" الظاهر عندي حاليًا إن عندك {xp_total} XP.", language)
    return _output(text_out, {"answered_field": "xp_system_explanation", "xp_total_visible": xp_total is not None}, language=language)


def _answer_gamification_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:
    if not _matches_any(text, [r"\brank\b", r"\bxp\b", r"\bpoints?\b", r"\bleaderboard\b", r"\bbadges?\b", r"\bperks?\b", r"\bnext\s+level\b", r"\bnext\s+badge\b", r"رانك", r"ترتيب", r"نقاط", r"بادج", r"شاره", r"شارة", r"مميزات"]):
        return None
    context = build_user_context(user_id=user_id)
    gamification = context.get("gamification") or {}
    xp_total = gamification.get("xp_total")
    rank = gamification.get("rank")
    badges = gamification.get("badges") or []
    perks = gamification.get("perks") or []
    xp_to_next = gamification.get("xp_to_next_level")

    wants_badges = _matches_any(text, [r"badges?", r"next\s+badge", r"بادج", r"شاره", r"شارة"])
    wants_perks = _matches_any(text, [r"perks?", r"hints?", r"مميزات", r"امتياز"])
    wants_next = _matches_any(text, [r"next\s+(level|milestone)", r"close\s+.*next", r"باقي", r"اللي\s+بعد"])
    wants_rank = _matches_any(text, [r"rank", r"leaderboard", r"ترتيب", r"رانك"])
    wants_xp = _matches_any(text, [r"xp", r"points?", r"نقاط"])

    lines: List[str] = []
    if wants_xp or wants_rank or wants_next or not (wants_badges or wants_perks):
        if xp_total is not None:
            lines.append(response_for_language(f"Your visible XP is {xp_total}.", f"الـ XP الظاهر عندي لحسابك هو {xp_total}.", language))
        else:
            lines.append(response_for_language("I cannot see your XP total yet.", "مش قادر أشوف إجمالي الـ XP حاليًا.", language))
    if wants_rank:
        rank_value = None
        if isinstance(rank, dict):
            for key in ("rank", "position", "leaderboard_rank", "current_rank"):
                if rank.get(key) is not None:
                    rank_value = rank.get(key)
                    break
        lines.append(response_for_language(f"Your rank is {rank_value}." if rank_value is not None else "I can see your XP, but I do not see a saved leaderboard rank yet.", f"الرانك بتاعك هو {rank_value}." if rank_value is not None else "شايف الـ XP، لكن مش شايف رانك محفوظ في الليدربورد حاليًا.", language))
    if wants_next:
        lines.append(response_for_language(f"You need {xp_to_next} XP for the next level." if xp_to_next is not None else "I do not see the next-level XP threshold yet, so I should not invent a number.", f"محتاج {xp_to_next} XP للمرحلة اللي بعدها." if xp_to_next is not None else "مش شايف شرط الـ XP للمرحلة اللي بعدها، فمش هخمن رقم.", language))
    if wants_badges:
        if badges:
            lines.append(response_for_language(f"I can see {len(badges)} earned badge(s).", f"شايف عندك {len(badges)} شارة مكتسبة.", language))
        else:
            lines.append(response_for_language("I do not see earned badges or badge-progress rows yet.", "مش شايف شارات مكتسبة أو تقدم شارات محفوظ حاليًا.", language))
    if wants_perks:
        if perks:
            lines.append(response_for_language(f"I can see {len(perks)} available perk(s).", f"شايف عندك {len(perks)} ميزة متاحة.", language))
        else:
            lines.append(response_for_language("I do not see available perks saved for your account right now.", "مش شايف مميزات محفوظة لحسابك حاليًا.", language))

    return _output(" ".join(lines), {"answered_field": "gamification", "gamification_found": True}, language=language)


def _answer_career_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:
    if not _matches_any(text, [
        r"\bcareer\b", r"\bjobs?\b", r"\bwork\b", r"\bhired\b", r"\bemployment\b", r"\bentry\s*level\b", r"\bportfolio\b", r"\bcv\b", r"\bproject\b", r"\buseful\b", r"\bwhat\s+can\s+i\s+do\s+with\s+it\b",
        r"\bafter\s+.*track\b", r"\bfinish\s+.*track\b", r"\bafter\s+(da|data\s+analytics|data\s+engineering|data\s+science)\b", r"\bwhat\s+.*after\s+.*(finish|finishing|complete|completing)\b", r"\bwhere\s+can\s+i\s+work\b", r"\bwhat\s+can\s+i\s+work\s+as\b", r"\bdata\s+analyst\s+job\b", r"\bwhat\s+does\s+a\s+data\s+analyst\s+do\b",
        r"اشتغل", r"وظيفه", r"وظيفة", r"شغل", r"بعد\s+.*track", r"بعد\s+.*تراك", r"بعد\s+.*مسار", r"مسار.*بعد\s+كده", r"مفيد", r"اعمل\s+بيه", r"استخدمه", r"سي\s*في", r"بورتفوليو", r"مشروع",
    ]):
        return None
    _, track_code, track_label, path = _track_and_path(user_id, text)
    career = CAREER_BY_TRACK.get(track_code or "DA", CAREER_BY_TRACK["DA"])
    jobs = ", ".join(career["jobs"][:5])
    if _matches_any(text, [r"\bcv\b", r"سي\s*في"]):
        topics = path.get("topics") or []
        topic_names = ", ".join([str(t.get("title")) for t in topics[:5] if t.get("title")]) or career["skills"]
        out = response_for_language(
            f"On your CV, write beginner skills from the {career['label']} path, such as: {topic_names}. Add one small project that shows {career['project']}.",
            f"في الـ CV اكتب مهارات مبتدئة من مسار {career['label']} زي: {topic_names}. وحط مشروع صغير يوضح إنك عملت {career['project']}.",
            language,
        )
    elif _matches_any(text, [r"project", r"portfolio", r"مشروع", r"بورتفوليو"]):
        out = response_for_language(
            f"A strong project for {career['label']} is {career['project']}. Keep it simple: explain the problem, show the data, show your steps, then summarize the insight.",
            f"مشروع قوي لمسار {career['label']} هو {career['project']}. خليه بسيط: اشرح المشكلة، اعرض الداتا، وضّح خطواتك، ثم لخّص النتيجة.",
            language,
        )
    else:
        out = response_for_language(
            f"After {career['label']}, entry-level roles include: {jobs}. Day to day, you usually {career['work']}. To prepare, focus on {career['skills']} and build 2–3 portfolio projects.",
            f"بعد {career['label']} تقدر تبدأ في وظائف زي: {jobs}. يوميًا غالبًا هتشتغل على إنك {career['work']}. للتحضير، ركز على {career['skills']} وابني 2–3 مشاريع بورتفوليو.",
            language,
        )
    return _output(out, {"answered_field": "career_path", "resolved_track": track_code}, language=language)


def _answer_learning_path_question(*, text: str, user_id: str, topic_id: Optional[str], module_id: Optional[str], language: str) -> Optional[Dict[str, Any]]:
    if not _matches_any(text, [
        r"\bwhat\s+should\s+i\s+(learn|study|start)\b", r"\bwhat\s+should\s+i\s+start\s+with\b", r"\bwhat\s+to\s+(learn|study)\b",
        r"\bstart\s+with\b", r"\bstudy\s+now\b", r"\bshort\s+plan\b", r"\bplan\s+for\s+today\b", r"\broadmap\b",
        r"\bnext\s+(topic|module|step|few\s+steps)\b", r"\b10\s+minutes\b", r"\b20\s+minutes\b", r"\btrack\s+roadmap\b", r"\bdata\s+analytics\s+track\b", r"\bdata\s+engineering\s+track\b", r"\bdata\s+science\s+track\b",
        r"ابدأ", r"اذاكر", r"أذاكر", r"اتعلم", r"أتعلم", r"تايه", r"تراك", r"مسار", r"بعد\s+كده", r"الخطوه", r"الخطة", r"خطة",
    ]):
        return None
    position, track_code, track_label, path = _track_and_path(user_id, text)
    topics = path.get("topics") or []
    metadata = {"answered_field": "learning_path", "assigned_track": position.get("assigned_track"), "resolved_track": track_code, "course_found": bool((path.get("course") or {}).get("id")), "topics_count": len(topics), "modules_count": len(path.get("modules") or [])}
    if not topics:
        return _output(response_for_language("I found your track, but I could not load its topic list yet. Open your track map and ask me again.", "لقيت التراك بتاعك، لكن مش قادر أحمل قائمة الموضوعات حاليًا. افتح خريطة التراك واسألني تاني.", language), metadata, language=language)
    topic_list = _format_topic_list(topics, limit=5, language=language)
    if _matches_any(text, [r"10\s+minutes", r"20\s+minutes", r"one\s+small", r"short\s+plan", r"plan\s+for\s+today", r"خطة", r"النهارده"]):
        first = topics[0].get("title") or "the first topic"
        out = response_for_language(
            f"For today, keep it small: 1) review {first}, 2) write 3 notes in your own words, 3) solve or retry one short exercise. If you only have a few minutes, start with {first} only.",
            f"خطة النهارده بسيطة: 1) راجع {first}، 2) اكتب 3 ملاحظات بأسلوبك، 3) حل أو عيد تمرين قصير. لو وقتك قليل، ابدأ بـ {first} بس.",
            language,
        )
    else:
        out = response_for_language(
            f"For your {track_label} path, start with these next topics:\n{topic_list}\nTake them one at a time, starting with the first one.",
            f"في مسار {track_label}، ابدأ بالموضوعات دي:\n{topic_list}\nامشي عليهم واحدة واحدة وابدأ بأول موضوع.",
            language,
        )
    return _output(out, metadata, language=language, action="recommend_resource")


def _answer_progress_status(*, text: str, user_id: str, topic_id: Optional[str], module_id: Optional[str], language: str) -> Optional[Dict[str, Any]]:
    if not _matches_any(text, [r"\bwhat\s+track\b", r"\bmy\s+track\b", r"\bwhich\s+track\b", r"\bwhat\s+topic\b", r"\bwhich\s+topic\b", r"\bwhat\s+module\b", r"\bwhich\s+module\b", r"\bwhat\s+level\b", r"\bwhich\s+level\b", r"\bmy\s+progress\b", r"\bwhere\s+am\s+i\b", r"فين", r"تراكي", r"التراك", r"الموديول", r"المستوى", r"تقدمي"]):
        return None
    position = _latest_position(user_id)
    context = fetch_content_context(topic_id=topic_id, module_id=module_id)
    topic = context.get("topic") or {}
    module = context.get("module") or {}
    level = context.get("level") or {}
    course = context.get("course") or {}
    metadata = {"topic_id": topic_id, "module_id": module_id, "profile_found": bool(position.get("profile")), "topic_found": bool(topic), "module_found": bool(module), "level_found": bool(level), "course_found": bool(course)}
    if "track" in text or "تراك" in text or "مسار" in text:
        track = position.get("assigned_track") or course.get("track")
        label = TRACK_LABELS.get(str(track), track)
        if label:
            return _output(response_for_language(f"You are currently assigned to the {label} track.", f"أنت حاليًا متسجل في مسار {label}.", language), {**metadata, "answered_field": "assigned_track", "assigned_track": track}, language=language)
    if "topic" in text or "موضوع" in text:
        if topic.get("title"):
            return _output(response_for_language(f"Your current topic is: {topic.get('title')}.", f"موضوعك الحالي هو: {topic.get('title')}.", language), {**metadata, "answered_field": "topic"}, language=language)
        return _output(response_for_language("I do not have current topic context yet. Open a topic page and ask me there.", "معنديش سياق الموضوع الحالي. افتح صفحة موضوع واسألني هناك.", language), {**metadata, "answered_field": "topic_missing"}, language=language)
    if "module" in text or "موديول" in text:
        if module.get("title"):
            return _output(response_for_language(f"Your current module is: {module.get('title')}.", f"الموديول الحالي هو: {module.get('title')}.", language), {**metadata, "answered_field": "module"}, language=language)
        return _output(response_for_language("I do not have current module context yet. Open a module or lesson page and ask me again.", "معنديش سياق الموديول الحالي. افتح صفحة موديول أو درس واسألني تاني.", language), {**metadata, "answered_field": "module_missing"}, language=language)
    return _output(response_for_language(f"Here is what I can see: Track: {TRACK_LABELS.get(str(position.get('assigned_track')), position.get('assigned_track') or 'not found')} | XP: {position.get('xp_total') if position.get('xp_total') is not None else 'not visible'}. ", f"ده اللي أقدر أشوفه: المسار: {TRACK_LABELS.get(str(position.get('assigned_track')), position.get('assigned_track') or 'غير ظاهر')} | XP: {position.get('xp_total') if position.get('xp_total') is not None else 'غير ظاهر'}.", language), {**metadata, "answered_field": "progress_summary"}, language=language)



def _answer_study_plan_question(*, text: str, user_id: str, topic_id: Optional[str], module_id: Optional[str], language: str) -> Optional[Dict[str, Any]]:
    """Purpose-built plan builder. This handles planning intent before generic track/progress logic."""
    if not _matches_any(text, [
        r"\bmake\s+me\s+.*plan\b", r"\bshort\s+plan\b", r"\bplan\s+for\s+today\b", r"\bstudy\s+plan\b", r"\bwhat\s+should\s+i\s+start\s+with\b",
        r"\bwhere\s+should\s+i\s+start\b", r"\bhow\s+should\s+i\s+start\b", r"\bwhat\s+should\s+i\s+(learn|study)\b", r"\bstudy\s+now\b", r"\bstart\s+studying\b",
        r"\b10\s+minutes\b", r"\b20\s+minutes\b", r"\bone\s+small\s+thing\b", r"\bnext\s+topic\b",
        r"خطة", r"ابدأ", r"ابدا", r"اذاكر", r"أذاكر", r"اتعلم", r"أتعلم", r"نبدأ", r"نبدا", r"تايه", r"مش\s+عارف\s+ابدأ", r"مش\s+عارف\s+ابدا", r"النهارده",
    ]):
        return None

    _, track_code, track_label, path = _track_and_path(user_id, text)
    topics = path.get("topics") or []
    metadata = {
        "answered_field": "study_plan",
        "resolved_track": track_code,
        "course_found": bool((path.get("course") or {}).get("id")),
        "topics_count": len(topics),
        "modules_count": len(path.get("modules") or []),
    }

    if not topics:
        return _output(
            response_for_language(
                "I can help you plan, but I cannot see the topic list for your track yet. Start with the first visible lesson in your track map, then ask me inside that lesson for a focused plan.",
                "أقدر أعملك خطة، لكن مش شايف قائمة موضوعات التراك حاليًا. ابدأ بأول درس ظاهر في خريطة التراك، وبعدها اسألني جوه الدرس أعملك خطة مركزة.",
                language,
            ),
            metadata,
            language=language,
            action="recommend_resource",
        )

    first = topics[0].get("title") or "the first topic"
    second = topics[1].get("title") if len(topics) > 1 else None
    third = topics[2].get("title") if len(topics) > 2 else None

    if _matches_any(text, [r"\b10\s+minutes\b", r"\bone\s+small\s+thing\b", r"وقت\s+قليل", r"١٠", r"10"]):
        out = response_for_language(
            f"Use the next 10 minutes for one thing only: open {first}, read the objective, and write 3 bullet notes in your own words. Do not jump to the next topic until you can explain the main idea in one sentence.",
            f"استغل الـ 10 دقايق في حاجة واحدة بس: افتح {first}، اقرأ الهدف، واكتب 3 ملاحظات بأسلوبك. متدخلش على موضوع جديد غير لما تقدر تشرح الفكرة الأساسية في جملة واحدة.",
            language,
        )
    elif _matches_any(text, [r"\b20\s+minutes\b", r"twenty", r"٢٠", r"20"]):
        out = response_for_language(
            f"For 20 minutes: 1) spend 8 minutes on {first}, 2) write a tiny example, 3) if it feels clear, preview {second or 'the next topic'} for 5 minutes. Keep it light; the goal is momentum, not finishing everything.",
            f"في 20 دقيقة: 1) خصص 8 دقايق لـ {first}، 2) اكتب مثال صغير، 3) لو الدنيا واضحة، بص بسرعة على {second or 'الموضوع اللي بعده'} لمدة 5 دقايق. الهدف تحرك بسيط مش إنك تخلص كل حاجة.",
            language,
        )
    else:
        out = response_for_language(
            f"Here’s a simple plan for your {track_label} track: 1) Start with {first}; 2) write one example in your own words; 3) move to {second or 'the next topic'} only after the first idea feels clear. After that, preview {third or 'the next small lesson'}.",
            f"دي خطة بسيطة لمسار {track_label}: 1) ابدأ بـ {first}؛ 2) اكتب مثال واحد بأسلوبك؛ 3) انتقل لـ {second or 'الموضوع اللي بعده'} بس لما أول فكرة تبقى واضحة. بعد كده بص على {third or 'الدرس الصغير اللي بعده'}.",
            language,
        )

    return _output(out, metadata, language=language, action="recommend_resource")


def _answer_topic_start_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:
    """Answers 'how do I start X?' with a practical learning path, not a definition of X."""
    start_intent = _matches_any(text, [
        r"\bhow\s+(do|should|can)\s+i\s+start\b", r"\bwhere\s+(do|should|can)\s+i\s+start\b", r"\bstart\s+(with|learning|studying)\b", r"\bfocus\s+on\b",
        r"\bi\s+want\s+to\s+focus\s+on\b", r"\bnot\s+understand\b", r"\bstuck\b", r"\bمش\s+فاهم\b", r"\bنبدأ\b", r"\bنبدا\b", r"\bأبدأ\b", r"\bابدا\b",
    ])
    if not start_intent:
        return None

    concept = None
    if _matches_any(text, [r"\bsql\b", r"اس\s*كيو\s*ال", r"joins?"]):
        concept = "SQL"
        en_steps = "1) Understand what a table, row, and column are; 2) practice SELECT and WHERE; 3) then learn JOINs with two small tables. Start by writing one SELECT query today."
        ar_steps = "1) افهم يعني إيه جدول وصف وعمود؛ 2) اتدرب على SELECT و WHERE؛ 3) بعدها ادخل على JOINs بجدولين صغيرين. ابدأ النهارده باستعلام SELECT واحد."
    elif _matches_any(text, [r"python", r"بايثون"]):
        concept = "Python"
        en_steps = "1) Start with variables and print; 2) practice if/else and loops; 3) write a tiny script that cleans or prints a small list. Keep the first script very small."
        ar_steps = "1) ابدأ بالمتغيرات و print؛ 2) اتدرب على if/else والـ loops؛ 3) اكتب سكريبت صغير يتعامل مع ليست بسيطة. خلي أول سكريبت صغير جدًا."
    elif _matches_any(text, [r"power\s*bi", r"باور\s*بي", r"بور\s*بي"]):
        concept = "Power BI"
        en_steps = "1) Load a small dataset; 2) clean column names; 3) create one chart; 4) add one slicer. Do not start with advanced DAX yet."
        ar_steps = "1) حمّل داتا صغيرة؛ 2) نظف أسماء الأعمدة؛ 3) اعمل chart واحد؛ 4) ضيف slicer واحد. متبدأش بـ DAX المتقدم دلوقتي."
    elif _matches_any(text, [r"data\s+analysis", r"data\s+analytics", r"تحليل\s+بيانات", r"تحليل\s+البيانات"]):
        concept = "Data Analysis"
        en_steps = "1) Start with a simple question; 2) inspect the dataset; 3) clean obvious errors; 4) summarize one pattern with a chart or table."
        ar_steps = "1) ابدأ بسؤال بسيط؛ 2) بص على الداتا؛ 3) نظف الأخطاء الواضحة؛ 4) لخص نمط واحد في chart أو جدول."

    if not concept:
        return None

    return _output(response_for_language(f"To start {concept}, do this: {en_steps}", f"عشان تبدأ {concept}: {ar_steps}", language), {"answered_field": "topic_start_plan", "concept": concept}, language=language, action="recommend_resource")

def answer_progress_status_question(*, message: str, user_id: str, topic_id: Optional[str], module_id: Optional[str]) -> Optional[Dict[str, Any]]:
    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)
    if not text:
        return None
    # Specific intent handlers first. This prevents generic progress/track logic from
    # stealing questions like “make a plan” or “how do I start SQL?”.
    for handler in (
        _answer_xp_system_question,
        _answer_gamification_question,
        _answer_career_question,
        _answer_study_plan_question,
        _answer_topic_start_question,
        _answer_learning_path_question,
    ):
        if handler in {_answer_learning_path_question, _answer_study_plan_question}:
            out = handler(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)
        else:
            out = handler(text=text, user_id=user_id, language=language)
        if out:
            return out
    return _answer_progress_status(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)

# ---------------------------------------------------------------------------
# 2026-06 memory/intent patch: overrides above handlers with stricter intent.
# ---------------------------------------------------------------------------


def _answer_gamification_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    if not _matches_any(text, [r"\brank\b", r"\bxp\b", r"\bpoints?\b", r"\bleaderboard\b", r"\bbadges?\b", r"\bperks?\b", r"\bhints?\b", r"\bnext\s+(level|badge|milestone)\b", r"\bhow\s+close\b", r"رانك", r"ترتيب", r"نقاط", r"بادج", r"شاره", r"شارة", r"مميزات", r"امتياز", r"تلميح"]):
        return None
    context = build_user_context(user_id=user_id)
    gamification = context.get("gamification") or {}
    xp_total = gamification.get("xp_total")
    rank = gamification.get("rank")
    badges = gamification.get("badges") or []
    perks = gamification.get("perks") or []
    xp_to_next = gamification.get("xp_to_next_level") or gamification.get("xp_to_next_badge")

    wants_badges = _matches_any(text, [r"badges?", r"next\s+badge", r"closest\s+.*badge", r"بادج", r"شاره", r"شارة"])
    wants_perks = _matches_any(text, [r"perks?", r"hints?", r"hint", r"مميزات", r"امتياز", r"تلميح"])
    wants_next = _matches_any(text, [r"next\s+(level|milestone)", r"close\s+.*next", r"xp\s+milestone", r"باقي", r"اللي\s+بعد", r"المستوى\s+اللي\s+بعد"])
    wants_rank = _matches_any(text, [r"rank", r"leaderboard", r"ترتيب", r"رانك"])
    wants_xp = _matches_any(text, [r"xp", r"points?", r"نقاط"])

    lines: List[str] = []
    if wants_rank:
        rank_value = None
        if isinstance(rank, dict):
            for key in ("rank", "position", "leaderboard_rank", "current_rank"):
                if rank.get(key) is not None:
                    rank_value = rank.get(key)
                    break
        elif rank is not None:
            rank_value = rank
        if rank_value is not None:
            lines.append(response_for_language(f"Your current rank is {rank_value}.", f"الرانك الحالي بتاعك هو {rank_value}.", language))
        else:
            lines.append(response_for_language("I can see your progress, but I do not see a saved leaderboard rank yet.", "شايف تقدمك، لكن مش شايف رانك محفوظ في الليدربورد حاليًا.", language))
    if wants_next:
        if xp_total is not None and xp_to_next is not None:
            lines.append(response_for_language(f"You currently have {xp_total} XP, and you need {xp_to_next} more XP for the next visible milestone.", f"عندك حاليًا {xp_total} XP، ومحتاج {xp_to_next} XP كمان لأقرب milestone ظاهر عندي.", language))
        elif xp_total is not None:
            lines.append(response_for_language(f"You currently have {xp_total} XP, but I cannot see the next-milestone threshold yet, so I should not invent a number.", f"عندك حاليًا {xp_total} XP، لكن مش شايف شرط الـ milestone اللي بعده، فمش هخمن رقم.", language))
        else:
            lines.append(response_for_language("I cannot see your XP or next milestone yet.", "مش قادر أشوف الـ XP أو الـ milestone اللي بعده حاليًا.", language))
    if wants_badges:
        if badges:
            lines.append(response_for_language(f"I can see {len(badges)} earned badge(s).", f"شايف عندك {len(badges)} شارة مكتسبة.", language))
        else:
            lines.append(response_for_language("I do not see earned badges or badge-progress rules yet. Keep completing lessons and challenges, and I can track them once the app saves badge progress.", "مش شايف شارات مكتسبة أو قواعد تقدم الشارات حاليًا. كمّل الدروس والتحديات، ولما التطبيق يحفظ تقدم الشارات هقدر أتابعها معاك.", language))
    if wants_perks:
        if perks:
            lines.append(response_for_language(f"I can see {len(perks)} available perk(s).", f"شايف عندك {len(perks)} ميزة متاحة.", language))
        else:
            lines.append(response_for_language("I do not see saved perks or hints available for your account right now.", "مش شايف مميزات أو تلميحات محفوظة لحسابك حاليًا.", language))
    if not lines and wants_xp:
        if xp_total is not None:
            lines.append(response_for_language(f"Your visible XP is {xp_total}.", f"الـ XP الظاهر عندي لحسابك هو {xp_total}.", language))
        else:
            lines.append(response_for_language("I cannot see your XP total yet.", "مش قادر أشوف إجمالي الـ XP حاليًا.", language))
    if not lines:
        return None
    return _output(" ".join(lines), {"answered_field": "gamification", "gamification_found": True}, language=language)


def _answer_career_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    if not _matches_any(text, [
        r"\bcareer\b", r"\bjobs?\b", r"\bwork\b", r"\bhired\b", r"\bemployment\b", r"\bentry\s*level\b", r"\bportfolio\b", r"\bcv\b", r"\bproject\b", r"\buseful\b", r"\bwhat\s+can\s+i\s+do\s+with\s+it\b",
        r"\bafter\s+.*track\b", r"\bfinish\s+.*track\b", r"\bfinishing\s+.*track\b", r"\bcomplete\s+.*track\b", r"\bafter\s+(da|data\s+analytics|data\s+engineering|data\s+science)\b",
        r"\bwhat\s+.*after\s+.*(finish|finishing|complete|completing)\b", r"\bwhere\s+can\s+i\s+work\b", r"\bwhat\s+can\s+i\s+work\s+as\b", r"\bwhat\s+can\s+i\s+do\s+with\s+(it|data|analytics|data\s+analytics)\b",
        r"\bis\s+.*useful\b", r"\bdata\s+analyst\s+job\b", r"\bwhat\s+does\s+a\s+data\s+analyst\s+do\b",
        r"اشتغل", r"وظيفه", r"وظيفة", r"شغل", r"بعد\s+.*track", r"بعد\s+.*التراك", r"بعد\s+.*المسار", r"بعد\s+.*تراك", r"بعد\s+.*مسار", r"مسار.*بعد\s+كده", r"تراك.*بعد\s+كده", r"مفيد", r"اعمل\s+بيه", r"استفيد", r"سي\s*في", r"بورتفوليو", r"مشروع", r"اعمل\s+ايه\s+بعد", r"اقدر\s+اعمل\s+ايه",
    ]):
        return None
    _, track_code, track_label, path = _track_and_path(user_id, text)
    career = CAREER_BY_TRACK.get(track_code or "DA", CAREER_BY_TRACK["DA"])
    jobs = ", ".join(career["jobs"][:5])
    topics = path.get("topics") or []
    if _matches_any(text, [r"\bcv\b", r"سي\s*في"]):
        topic_names = ", ".join([str(t.get("title")) for t in topics[:5] if t.get("title")]) or career["skills"]
        out = response_for_language(
            f"For your CV after the first level, write skills you actually practiced: {topic_names}. Add one beginner project line, for example: built a small {career['label']} project to clean data, analyze results, and present insights.",
            f"في الـ CV بعد أول Level، اكتب المهارات اللي اتدربت عليها فعلًا: {topic_names}. وضيف سطر مشروع بسيط مثل: عملت مشروع {career['label']} صغير لتنضيف الداتا وتحليل النتائج وعرض insight.",
            language,
        )
    elif _matches_any(text, [r"\bproject\b", r"portfolio", r"مشروع", r"بورتفوليو"]):
        out = response_for_language(
            f"Build a small {career['label']} portfolio project: choose a simple dataset, clean it, answer 3 business questions, create 2–3 visuals, and write a short conclusion. A good target is {career['project']}.",
            f"اعمل مشروع بورتفوليو صغير في {career['label']}: اختار dataset بسيطة، نظفها، جاوب 3 أسئلة business، اعمل 2–3 visuals، واكتب conclusion قصير. مثال مناسب: {career['project']}.",
            language,
        )
    else:
        out = response_for_language(
            f"After {career['label']}, you can aim for roles like: {jobs}. In those roles, you usually {career['work']}. So after the track, build 2–3 portfolio projects and practice interviews around {career['skills']}.",
            f"بعد {career['label']} تقدر تستهدف وظائف زي: {jobs}. في الشغل ده غالبًا هتعمل إنك {career['work']}. بعد التراك، اعمل 2–3 مشاريع بورتفوليو واتدرب على مقابلات في {career['skills']}.",
            language,
        )
    return _output(out, {"answered_field": "career_path", "resolved_track": track_code}, language=language)


def _answer_study_plan_question(*, text: str, user_id: str, topic_id: Optional[str], module_id: Optional[str], language: str) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    if not _matches_any(text, [
        r"\bmake\s+me\s+.*plan\b", r"\bshort\s+plan\b", r"\bplan\s+for\s+today\b", r"\bstudy\s+plan\b", r"\bwhat\s+should\s+i\s+start\s+with\b",
        r"\bwhere\s+should\s+i\s+start\b", r"\bhow\s+should\s+i\s+start\b", r"\bwhat\s+should\s+i\s+(learn|study)\b", r"\bstudy\s+now\b", r"\bstart\s+studying\b",
        r"\b10\s+minutes\b", r"\b20\s+minutes\b", r"\bone\s+small\s+thing\b", r"\bnext\s+topic\b", r"\bnot\s+sure\s+what\s+i\s+should\s+do\b",
        r"خطة", r"ابدأ", r"ابدا", r"اذاكر", r"أذاكر", r"اتعلم", r"أتعلم", r"نبدأ", r"نبدا", r"تايه", r"مش\s+عارف\s+ابدأ", r"مش\s+عارف\s+ابدا", r"النهارده",
    ]):
        return None
    # If a concrete concept is present, topic-start planning is more relevant.
    if _matches_any(text, [r"\bsql\b", r"python", r"power\s*bi", r"excel", r"joins?", r"بايثون", r"بور\s*بي", r"باور\s*بي", r"اس\s*كيو\s*ال"]):
        return None

    _, track_code, track_label, path = _track_and_path(user_id, text)
    topics = path.get("topics") or []
    metadata = {"answered_field": "study_plan", "resolved_track": track_code, "course_found": bool((path.get("course") or {}).get("id")), "topics_count": len(topics), "modules_count": len(path.get("modules") or [])}
    if not topics:
        return _output(response_for_language("I can build a plan, but I cannot see your track topics yet. Start with the first visible lesson, then ask me inside that lesson for a focused plan.", "أقدر أعمل خطة، لكن مش شايف موضوعات التراك حاليًا. ابدأ بأول درس ظاهر، وبعدها اسألني جوه الدرس أعملك خطة مركزة.", language), metadata, language=language, action="recommend_resource")

    first = topics[0].get("title") or "the first topic"
    second = topics[1].get("title") if len(topics) > 1 else "the next topic"
    third = topics[2].get("title") if len(topics) > 2 else "one small practice task"
    if _matches_any(text, [r"\b10\s+minutes\b", r"\bone\s+small\s+thing\b", r"وقت\s+قليل", r"١٠", r"10"]):
        out = response_for_language(
            f"Do one small thing: open {first}, read only the objective, then write 3 bullet points in your own words. Stop there; the goal is momentum, not finishing a whole module.",
            f"اعمل حاجة واحدة صغيرة: افتح {first}، اقرأ الهدف بس، واكتب 3 نقاط بأسلوبك. وقف هنا؛ الهدف إنك تتحرك مش تخلص موديول كامل.",
            language,
        )
    else:
        out = response_for_language(
            f"Here’s a practical plan: 1) Start with {first}; 2) spend 10 minutes understanding the main idea; 3) write one tiny example in your own words; 4) do one quick exercise; 5) only then preview {second}. If {first} feels hard, ask me to break it into a simpler example before moving on.",
            f"دي خطة عملية: 1) ابدأ بـ {first}؛ 2) خُد 10 دقايق تفهم الفكرة الأساسية؛ 3) اكتب مثال صغير بأسلوبك؛ 4) حل تمرين سريع؛ 5) بعدها بس بص على {second}. لو {first} صعب، اسألني أبسطه بمثال قبل ما تكمل.",
            language,
        )
    return _output(out, metadata, language=language, action="recommend_resource")


def _answer_topic_start_question(*, text: str, user_id: str, language: str) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    start_intent = _matches_any(text, [
        r"\bhow\s+(do|should|can)\s+i\s+start\b", r"\bwhere\s+(do|should|can)\s+i\s+start\b", r"\bstart\s+(with|learning|studying)\b", r"\bfocus\s+on\b",
        r"\bi\s+want\s+to\s+focus\s+on\b", r"\bnot\s+understand\b", r"\bstuck\b", r"\bمش\s+فاهم\b", r"\bنبدأ\b", r"\bنبدا\b", r"\bأبدأ\b", r"\bابدا\b",
    ])
    if not start_intent:
        return None

    concept = None
    in_track_note_en = ""
    in_track_note_ar = ""
    if _matches_any(text, [r"\bsql\b", r"اس\s*كيو\s*ال", r"joins?"]):
        concept = "SQL"
        en_steps = "1) Learn what a table, row, and column are; 2) write SELECT * FROM table; 3) add WHERE filters; 4) then practice JOIN with two tiny tables."
        ar_steps = "1) افهم يعني إيه table و row و column؛ 2) اكتب SELECT بسيط؛ 3) ضيف WHERE؛ 4) بعدها اتدرب على JOIN بجدولين صغيرين."
    elif _matches_any(text, [r"python", r"بايثون"]):
        concept = "Python"
        en_steps = "1) Start with variables and print; 2) practice if/else; 3) write a tiny loop; 4) make a small script that cleans or prints a list."
        ar_steps = "1) ابدأ بالمتغيرات و print؛ 2) اتدرب على if/else؛ 3) اكتب loop صغير؛ 4) اعمل سكريبت بسيط يتعامل مع list."
    elif _matches_any(text, [r"power\s*bi", r"bi\s*power", r"باور\s*بي", r"بور\s*بي"]):
        concept = "Power BI"
        en_steps = "1) Load a small dataset; 2) clean column names; 3) make one chart; 4) add one slicer; 5) avoid advanced DAX at the start."
        ar_steps = "1) حمّل dataset صغيرة؛ 2) نظف أسماء الأعمدة؛ 3) اعمل chart واحد؛ 4) ضيف slicer واحد؛ 5) متبدأش بـ DAX المتقدم."
    elif _matches_any(text, [r"java", r"جافا"]):
        concept = "Java"
        en_steps = "1) Learn variables and types; 2) write a small main method; 3) practice if/else and loops; 4) build one console program. This may be outside your current LearNova Data Analytics path, but I can still guide you."
        ar_steps = "1) ابدأ بالمتغيرات والأنواع؛ 2) اكتب main method صغيرة؛ 3) اتدرب على if/else و loops؛ 4) اعمل console program بسيط. ده ممكن يكون خارج مسارك الحالي في LearNova، لكن أقدر أساعدك فيه."
    elif _matches_any(text, [r"data\s+analysis", r"data\s+analytics", r"تحليل\s+بيانات", r"تحليل\s+البيانات"]):
        concept = "Data Analysis"
        en_steps = "1) Start with one question; 2) inspect the dataset; 3) clean obvious errors; 4) summarize one pattern with a chart or table."
        ar_steps = "1) ابدأ بسؤال واحد؛ 2) افحص الداتا؛ 3) نظف الأخطاء الواضحة؛ 4) لخص pattern واحد في chart أو جدول."
    if not concept:
        return None
    return _output(response_for_language(f"To start {concept}, follow this path: {en_steps}{in_track_note_en}", f"عشان تبدأ {concept}: {ar_steps}{in_track_note_ar}", language), {"answered_field": "topic_start_plan", "concept": concept}, language=language, action="recommend_resource")


def _answer_learning_path_question(*, text: str, user_id: str, topic_id: Optional[str], module_id: Optional[str], language: str) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    # Do not treat career-after-track questions as a curriculum roadmap.
    if _matches_any(text, [r"after\s+.*track", r"finish\s+.*track", r"finishing\s+.*track", r"jobs?", r"career", r"work", r"cv", r"portfolio", r"project", r"useful", r"what\s+can\s+i\s+do\s+with\s+it", r"بعد\s+.*التراك", r"بعد\s+.*تراك", r"بعد\s+.*مسار", r"مسار.*بعد\s+كده", r"اشتغل", r"وظيفة", r"شغل", r"مفيد", r"اعمل\s+بيه", r"استخدمه"]):
        return None
    if not _matches_any(text, [
        r"\bwhat\s+should\s+i\s+(learn|study|start)\b", r"\bwhat\s+should\s+i\s+start\s+with\b", r"\bwhat\s+to\s+(learn|study)\b",
        r"\broadmap\b", r"\bnext\s+(topic|module|step|few\s+steps)\b", r"\btrack\s+roadmap\b", r"\bdata\s+analytics\s+track\b", r"\bdata\s+engineering\s+track\b", r"\bdata\s+science\s+track\b",
        r"اتعلم", r"أتعلم", r"تراك", r"مسار", r"بعد\s+كده", r"الخطوه", r"الخطوة",
    ]):
        return None
    position, track_code, track_label, path = _track_and_path(user_id, text)
    topics = path.get("topics") or []
    metadata = {"answered_field": "learning_path", "assigned_track": position.get("assigned_track"), "resolved_track": track_code, "course_found": bool((path.get("course") or {}).get("id")), "topics_count": len(topics), "modules_count": len(path.get("modules") or [])}
    if not topics:
        return _output(response_for_language("I found your track, but I could not load its topic list yet. Open your track map and ask me again.", "لقيت التراك بتاعك، لكن مش قادر أحمل قائمة الموضوعات حاليًا. افتح خريطة التراك واسألني تاني.", language), metadata, language=language)
    topic_list = _format_topic_list(topics, limit=5, language=language)
    out = response_for_language(
        f"For your {track_label} path, the next visible topics are:\n{topic_list}\nStart with the first one, then ask me for a mini-plan inside that topic.",
        f"في مسار {track_label}، الموضوعات الجاية الظاهرة هي:\n{topic_list}\nابدأ بأول واحد، وبعدها اسألني أعملك mini-plan جوه الموضوع.",
        language,
    )
    return _output(out, metadata, language=language, action="recommend_resource")


def answer_progress_status_question(*, message: str, user_id: str, topic_id: Optional[str], module_id: Optional[str]) -> Optional[Dict[str, Any]]:  # type: ignore[override]
    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)
    if not text:
        return None
    for handler in (
        _answer_xp_system_question,
        _answer_gamification_question,
        _answer_career_question,
        _answer_topic_start_question,
        _answer_study_plan_question,
        _answer_learning_path_question,
    ):
        if handler in {_answer_learning_path_question, _answer_study_plan_question}:
            out = handler(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)
        else:
            out = handler(text=text, user_id=user_id, language=language)
        if out:
            return out
    return _answer_progress_status(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)
