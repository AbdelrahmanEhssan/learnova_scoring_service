import os
from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("SCORING_API_KEY")

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="SCORING_API_KEY is not configured"
        )

    if x_api_key != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )