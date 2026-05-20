def compute_module_score(answers: dict, questions: list, passing_score: int) -> dict:
    total_questions = len(questions)
    correct_count = 0

    for question in questions:
        question_id = str(question["id"])
        correct_answer = str(question["correct_answer"]).strip()
        selected_answer = str(answers.get(question_id, "")).strip()

        if selected_answer == correct_answer:
            correct_count += 1

    score = round((correct_count / total_questions) * 100, 2) if total_questions else 0
    passed = score >= passing_score

    return {
        "score": score,
        "passed": passed,
        "correct_count": correct_count,
        "total_questions": total_questions
    }