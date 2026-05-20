def grade_level_written_attempt(answers: dict, questions: list) -> dict:
    total_questions = len(questions)

    answered_count = 0

    for answer in answers.values():
        if str(answer).strip():
            answered_count += 1

    score = 80.0 if answered_count == total_questions else 50.0
    passed = score >= 70

    return {
        "score": score,
        "passed": passed,
        "mitchy_feedback": "Placeholder feedback. Replace with Mitchy/RAG grading.",
        "answered_count": answered_count,
        "total_questions": total_questions
    }