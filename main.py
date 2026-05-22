from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from mitchy.core import process_mitchy_message
from scoring.challenge import compute_challenge_score
from scoring.diagnostics import score_diagnostic
from scoring.level_written import grade_level_written_attempt
from scoring.module_exam import compute_module_score
from services.auth import require_api_key, require_mitchy_api_key
from services.supabase_client import supabase


app = FastAPI(title="LearNova Scoring Service")


class DiagnosticScoreRequest(BaseModel):
    result_id: str


class LevelAttemptScoreRequest(BaseModel):
    attempt_id: str


class ModuleAttemptScoreRequest(BaseModel):
    user_id: str
    assessment_id: str
    answers: dict


class ChallengeAttemptScoreRequest(BaseModel):
    user_id: str
    challenge_id: str
    answers: dict


class MitchyChatRequest(BaseModel):
    user_id: str
    message: str
    user_email: str | None = None
    full_name: str | None = None
    topic_id: str | None = None
    module_id: str | None = None
    screen_context: str | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "learnova-scoring-service",
    }


@app.post("/score/diagnostic-result")
def score_diagnostic_result(
    payload: DiagnosticScoreRequest,
    _=Depends(require_api_key),
):
    result_response = (
        supabase.table("diagnostic_test_results")
        .select("*")
        .eq("id", payload.result_id)
        .single()
        .execute()
    )

    result = result_response.data

    if not result:
        raise HTTPException(status_code=404, detail="Diagnostic result not found")

    computed_scores = score_diagnostic(
        test_number=result["test_number"],
        raw_answers=result["raw_answers"],
    )

    update_response = (
        supabase.table("diagnostic_test_results")
        .update({"computed_scores": computed_scores})
        .eq("id", payload.result_id)
        .execute()
    )

    return {
        "ok": True,
        "result_id": payload.result_id,
        "test_number": result["test_number"],
        "computed_scores": computed_scores,
        "updated": update_response.data,
    }


@app.post("/score/level-attempt")
def score_level_attempt(
    payload: LevelAttemptScoreRequest,
    _=Depends(require_api_key),
):
    attempt_response = (
        supabase.table("student_level_attempts")
        .select("*")
        .eq("id", payload.attempt_id)
        .single()
        .execute()
    )

    attempt = attempt_response.data

    if not attempt:
        raise HTTPException(status_code=404, detail="Level attempt not found")

    questions_response = (
        supabase.table("level_assessment_questions")
        .select(
            "id, question_text, ai_grading_rubric, mitchy_hint, "
            "mitchy_explanation, order_index"
        )
        .eq("assessment_id", attempt["assessment_id"])
        .order("order_index")
        .execute()
    )

    questions = questions_response.data or []

    grading_result = grade_level_written_attempt(
        answers=attempt["answers"],
        questions=questions,
    )

    update_response = (
        supabase.table("student_level_attempts")
        .update(
            {
                "score": grading_result["score"],
                "passed": grading_result["passed"],
                "mitchy_feedback": grading_result["mitchy_feedback"],
            }
        )
        .eq("id", payload.attempt_id)
        .execute()
    )

    return {
        "ok": True,
        "attempt_id": payload.attempt_id,
        "grading_result": grading_result,
        "updated": update_response.data,
    }


@app.post("/score/module-attempt")
def score_module_attempt(
    payload: ModuleAttemptScoreRequest,
    _=Depends(require_api_key),
):
    assessment_response = (
        supabase.table("module_assessments")
        .select("*")
        .eq("id", payload.assessment_id)
        .single()
        .execute()
    )

    assessment = assessment_response.data

    if not assessment:
        raise HTTPException(status_code=404, detail="Module assessment not found")

    if not assessment["is_active"]:
        raise HTTPException(status_code=400, detail="Module assessment is inactive")

    questions_response = (
        supabase.table("module_assessment_questions")
        .select("id, correct_answer")
        .eq("assessment_id", payload.assessment_id)
        .execute()
    )

    questions = questions_response.data or []

    scoring_result = compute_module_score(
        answers=payload.answers,
        questions=questions,
        passing_score=assessment["passing_score"],
    )

    insert_response = (
        supabase.table("student_module_attempts")
        .insert(
            {
                "user_id": payload.user_id,
                "assessment_id": payload.assessment_id,
                "answers": payload.answers,
                "score": scoring_result["score"],
                "passed": scoring_result["passed"],
            }
        )
        .execute()
    )

    if scoring_result["passed"]:
        supabase.rpc(
            "increment_xp",
            {
                "user_id_input": payload.user_id,
                "xp_amount": assessment["xp_reward"],
            },
        ).execute()

    return {
        "ok": True,
        "assessment_id": payload.assessment_id,
        "user_id": payload.user_id,
        "scoring_result": scoring_result,
        "inserted": insert_response.data,
    }


@app.post("/score/challenge-attempt")
def score_challenge_attempt(
    payload: ChallengeAttemptScoreRequest,
    _=Depends(require_api_key),
):
    challenge_response = (
        supabase.table("weekly_challenges")
        .select("*")
        .eq("id", payload.challenge_id)
        .single()
        .execute()
    )

    challenge = challenge_response.data

    if not challenge:
        raise HTTPException(status_code=404, detail="Weekly challenge not found")

    if not challenge["is_active"]:
        raise HTTPException(status_code=400, detail="Weekly challenge is inactive")

    questions_response = (
        supabase.table("challenge_questions")
        .select("id, correct_answer")
        .eq("challenge_id", payload.challenge_id)
        .execute()
    )

    questions = questions_response.data or []

    scoring_result = compute_challenge_score(
        answers=payload.answers,
        questions=questions,
    )

    insert_response = (
        supabase.table("student_challenge_attempts")
        .insert(
            {
                "user_id": payload.user_id,
                "challenge_id": payload.challenge_id,
                "answers": payload.answers,
                "score": scoring_result["score"],
                "completed": scoring_result["completed"],
            }
        )
        .execute()
    )

    supabase.rpc(
        "increment_xp",
        {
            "user_id_input": payload.user_id,
            "xp_amount": challenge["xp_reward"],
        },
    ).execute()

    return {
        "ok": True,
        "challenge_id": payload.challenge_id,
        "user_id": payload.user_id,
        "scoring_result": scoring_result,
        "inserted": insert_response.data,
    }


@app.post("/mitchy/chat")
def mitchy_chat(
    payload: MitchyChatRequest,
    _=Depends(require_mitchy_api_key),
):
    message = payload.message.strip() if payload.message else ""

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        result = process_mitchy_message(
            user_id=payload.user_id,
            user_email=payload.user_email,
            full_name=payload.full_name,
            message=message,
            topic_id=payload.topic_id,
            module_id=payload.module_id,
            screen_context=payload.screen_context,
        )

        return {
            "ok": True,
            **result,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Mitchy failed safely: {str(exc)}",
        ) from exc
