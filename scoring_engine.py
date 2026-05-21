# ============================================================
# scoring_engine.py — Railway HTTP Service (FastAPI wrapper)
# ============================================================
#
# This file is the Railway HTTP service. It wraps Ehssan's
# scoring logic (score_user() from learnova_scoring.py) in a
# FastAPI endpoint so the Supabase Edge Function can call it.
#
# FILE LAYOUT expected in the Railway repo root:
#
#   scoring_engine.py       ← this file (FastAPI app)
#   learnova_scoring.py     ← Ehssan's scoring logic (score_user)
#   scoring_config.py       ← Ehssan's config (TRACKS, FEATURE_RANGES, etc.)
#   track_weights.csv       ← the weights CSV
#   Procfile
#   requirements.txt
#
# Environment variables (set in Railway → your service → Variables):
#   SUPABASE_URL             — your Supabase project URL
#   SUPABASE_SERVICE_KEY     — service role key (bypasses RLS)
#   SCORING_SERVICE_API_KEY  — must match what the Edge Function sends
#   WEIGHTS_PATH             — path to track_weights.csv (default: "track_weights.csv")
#
# ============================================================

import os
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client, Client

# Import Ehssan's scoring logic.
# His file is called scoring_engine.py in his repo — rename it to
# learnova_scoring.py so it doesn't conflict with this file's name.
from learnova_scoring import score_user, ScoringResult

# ---------- Environment ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SCORING_SERVICE_API_KEY = os.environ.get("SCORING_SERVICE_API_KEY")
WEIGHTS_PATH = os.environ.get("WEIGHTS_PATH", "track_weights.csv")

# ---------- Supabase client (service role — bypasses RLS) ----------
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ---------- FastAPI app ----------
app = FastAPI()


# ---------- API key check ----------
def verify_api_key(request: Request):
    """
    Rejects any request that does not carry the correct x-api-key header.
    This is the only thing preventing the public Railway URL from being
    called by anyone other than the Supabase Edge Function.
    """
    incoming_key = request.headers.get("x-api-key")
    if not incoming_key or incoming_key != SCORING_SERVICE_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: invalid API key")


# ============================================================
# POST /score/diagnostic
# ============================================================
@app.post("/score/diagnostic")
async def score_diagnostic(request: Request):
    """
    Called by the Supabase Edge Function `run-scoring-engine`
    after a student completes all 5 diagnostic tests.

    Request body (sent by Edge Function):
        { "user_id": "uuid-of-the-student" }

    What this function does:
        1.  Validates the API key.
        2.  Fetches the student's diagnostic_test_results from Supabase.
        3.  Assembles a flat raw_payload dict that score_user() expects.
        4.  Calls score_user(raw_payload, WEIGHTS_PATH) — Ehssan's engine.
        5.  Writes assigned_track + learning_style + onboarding_complete
            back to student_profiles in Supabase.
        6.  Returns the result to the Edge Function → Flutter.

    Response:
        {
            "assigned_track": "DA",
            "learning_style": "Visual",
            "fallback_triggered": false,
            "message": "Based on your strong ...",
            "final_track_scores": { "DA": 0.72, "DE": 0.51, "DS": 0.48 }
        }
    """

    # 1. Verify API key
    verify_api_key(request)

    # 2. Parse request body
    body = await request.json()
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    # 3. Fetch all diagnostic_test_results for this student
    results_response = supabase \
        .from_("diagnostic_test_results") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    diagnostic_results = results_response.data

    if not diagnostic_results or len(diagnostic_results) < 5:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected 5 diagnostic results, "
                f"found {len(diagnostic_results) if diagnostic_results else 0}. "
                f"Student has not completed all diagnostic tests."
            )
        )

    # 4. Assemble the flat raw_payload that score_user() expects.
    #
    #    Ehssan's score_user() takes ONE flat dict with all feature keys,
    #    e.g. { "logical_reasoning": 11, "openness": 3.8, "visual": 12, ... }
    #
    #    Each diagnostic_test_results row has a raw_answers JSONB column.
    #    Each row covers one test (IQ, IPIP, Soft Skills, VARK, O*NET).
    #    We merge all raw_answers dicts together into one flat payload.
    #
    #    External results (result_source == 'external'):
    #    The student took the official test externally and typed in their score.
    #    raw_answers is empty ({}) for these rows. We skip merging raw_answers
    #    and instead inject the external_score under the test's primary feature key.
    #    See the EXTERNAL_SCORE_FEATURE_MAP below.
    #
    #    If Ehssan's DB schema stores raw_answers differently (e.g. nested),
    #    adjust the merge logic here — score_user() itself does not change.

    # Maps a test name/type to the single feature key that represents its score
    # when the student submitted it externally. Adjust these keys to match
    # whatever your diagnostic_test_results rows use to identify the test type.
    EXTERNAL_SCORE_FEATURE_MAP = {
        "iq":         "logical_reasoning",   # external IQ score → logical_reasoning
        "ipip":       "openness",            # external IPIP → openness (primary trait)
        "soft_skills": "problem_solving",    # external soft skills → problem_solving
        "vark":       "visual",              # external VARK → visual (primary style)
        "onet":       "investigative",       # external O*NET → investigative
    }

    raw_payload: dict = {}

    for result in diagnostic_results:
        if result.get("result_source") == "external":
            # External submission: use external_score directly.
            # Map it to the primary feature for this test type.
            test_type = result.get("test_type", "")  # adjust field name if different
            feature_key = EXTERNAL_SCORE_FEATURE_MAP.get(test_type)
            if feature_key and result.get("external_score") is not None:
                raw_payload[feature_key] = result["external_score"]
        else:
            # Normal in-app submission: merge raw_answers into the flat payload.
            # raw_answers is a JSONB dict: { "feature_key": numeric_value, ... }
            answers = result.get("raw_answers", {})
            if isinstance(answers, dict):
                raw_payload.update(answers)

    # 5. Call Ehssan's scoring engine
    try:
        result: ScoringResult = score_user(raw_payload, WEIGHTS_PATH)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scoring engine error: {str(e)}"
        )

    # 6. Determine learning style from VARK scores in normalized_features.
    #    VARK keys: visual, auditory, read_write, kinesthetic
    #    We map read_write → "Textual" and kinesthetic → "Textual" (closest match
    #    to LearNova's three styles: Visual, Auditory, Textual).
    #    Adjust this mapping if your learning style definitions differ.
    vark_map = {
        "visual":      "Visual",
        "auditory":    "Auditory",
        "read_write":  "Textual",
        "kinesthetic": "Textual",
    }
    vark_scores = {
        style: result.normalized_features.get(feature, 0.0)
        for feature, style in vark_map.items()
    }
    # If both read_write and kinesthetic map to Textual, their values are summed
    # when comparing — pick the style with the highest normalized score.
    aggregated_vark: dict[str, float] = {}
    for feature, style in vark_map.items():
        aggregated_vark[style] = aggregated_vark.get(style, 0.0) + \
                                  result.normalized_features.get(feature, 0.0)

    learning_style = max(aggregated_vark, key=aggregated_vark.get)

    # 7. Determine the assigned_track value to write to student_profiles.
    #    student_profiles.assigned_track CHECK constraint:
    #    CHECK (assigned_track IN ('Foundation', 'DA', 'DE', 'DS'))
    #    If fallback was triggered → write 'Foundation', otherwise write the track code.
    assigned_track = "Foundation" if result.fallback_triggered else \
                     _label_to_code(result.projected_specialization)

    # 8. Write to Supabase student_profiles
    update_response = supabase \
        .from_("student_profiles") \
        .update({
            "assigned_track":   assigned_track,
            "learning_style":   learning_style,
            "onboarding_complete": True,
        }) \
        .eq("user_id", user_id) \
        .execute()

    if not update_response.data:
        raise HTTPException(
            status_code=500,
            detail="Scoring succeeded but failed to update student_profiles in Supabase."
        )

    # 9. Return result to the Edge Function → Flutter
    return {
        "assigned_track":     assigned_track,
        "learning_style":     learning_style,
        "fallback_triggered": result.fallback_triggered,
        "message":            result.message,
        "final_track_scores": result.final_track_scores,
    }


def _label_to_code(projected_specialization: str) -> str:
    """
    Converts the human-readable label from ScoringResult back to the
    track code that student_profiles.assigned_track expects.

    TRACK_LABELS = { "DA": "Data Analytics", "DE": "Data Engineering", "DS": "Data Science" }
    """
    label_to_code = {
        "Data Analytics":   "DA",
        "Data Engineering": "DE",
        "Data Science":     "DS",
    }
    return label_to_code.get(projected_specialization, "Foundation")


# ============================================================
# Health check — Railway uses this to verify the service is alive
# ============================================================
@app.get("/health")
async def health():
    return {"status": "ok"}
