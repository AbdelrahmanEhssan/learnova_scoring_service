def score_diagnostic(test_number: int, raw_answers: dict) -> dict:
    answers = raw_answers.get("answers", [])

    if test_number == 1:
        return score_ipip(answers)

    if test_number == 2:
        return score_soft_skills(answers)

    if test_number == 3:
        return score_vark(answers)

    if test_number == 4:
        return score_career_onet(answers)

    if test_number == 5:
        return score_iq(answers)

    return {
        "status": "error",
        "message": "Unknown diagnostic test number",
        "test_number": test_number
    }


def score_ipip(answers: list) -> dict:
    return {
        "exam": "personality_ipip",
        "status": "placeholder_scored",
        "answer_count": len(answers)
    }


def score_soft_skills(answers: list) -> dict:
    return {
        "exam": "soft_skills",
        "status": "placeholder_scored",
        "answer_count": len(answers)
    }


def score_vark(answers: list) -> dict:
    return {
        "exam": "vark",
        "status": "placeholder_scored",
        "answer_count": len(answers)
    }


def score_career_onet(answers: list) -> dict:
    return {
        "exam": "career_interest_onet",
        "status": "placeholder_scored",
        "answer_count": len(answers)
    }


def score_iq(answers: list) -> dict:
    return {
        "exam": "iq",
        "status": "placeholder_scored",
        "answer_count": len(answers)
    }