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
        r"\bcareer\b", r"\bjobs?\b", r"\bwork\b", r"\bhired\b", r"\bemployment\b", r"\bentry\s*level\b", r"\bportfolio\b", r"\bcv\b", r"\bproject\b",
        r"\bafter\s+.*track\b", r"\bfinish\s+.*track\b", r"\bdata\s+analyst\s+job\b", r"\bwhat\s+does\s+a\s+data\s+analyst\s+do\b",
        r"اشتغل", r"وظيفه", r"وظيفة", r"شغل", r"بعد\s+.*track", r"سي\s*في", r"بورتفوليو", r"مشروع",
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


def answer_progress_status_question(*, message: str, user_id: str, topic_id: Optional[str], module_id: Optional[str]) -> Optional[Dict[str, Any]]:
    original = str(message or "").strip()
    text = normalize_for_intent(original)
    language = detect_language(original)
    if not text:
        return None
    for handler in (
        _answer_xp_system_question,
        _answer_gamification_question,
        _answer_career_question,
        _answer_learning_path_question,
    ):
        if handler is _answer_learning_path_question:
            out = handler(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)
        else:
            out = handler(text=text, user_id=user_id, language=language)
        if out:
            return out
    return _answer_progress_status(text=text, user_id=user_id, topic_id=topic_id, module_id=module_id, language=language)
