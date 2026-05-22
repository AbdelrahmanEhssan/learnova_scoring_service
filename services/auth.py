import os

from fastapi import Header, HTTPException


def _require_key_from_env(
    x_api_key: str | None,
    env_var_name: str,
    missing_message: str,
) -> None:
    expected = os.environ.get(env_var_name)

    if not expected:
        raise HTTPException(
            status_code=500,
            detail=missing_message,
        )

    if x_api_key != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """
    Existing scoring-service API key checker.

    Keep this for the already-working scoring Edge Functions.
    """
    _require_key_from_env(
        x_api_key=x_api_key,
        env_var_name="SCORING_API_KEY",
        missing_message="SCORING_API_KEY is not configured",
    )


def require_mitchy_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """
    Separate internal API key checker for Mitchy.

    Supabase Edge Function mitchy-chat will call Railway with this key.
    Flutter must never see this key.
    """
    _require_key_from_env(
        x_api_key=x_api_key,
        env_var_name="MITCHY_SERVICE_API_KEY",
        missing_message="MITCHY_SERVICE_API_KEY is not configured",
    )
