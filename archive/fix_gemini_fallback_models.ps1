Set-Content -Path "mitchy/gemini_client.py" -Encoding UTF8 -Value @'
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional, Tuple


def _call_gemini_once(prompt: str, model_name: str, api_key: str) -> Tuple[Optional[str], Optional[str]]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )

    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }

    data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")

        parsed = json.loads(response_body)

        candidates = parsed.get("candidates") or []
        if not candidates:
            return None, f"Gemini returned no candidates: {response_body}"

        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []

        if not parts:
            return None, f"Gemini returned no content parts: {response_body}"

        text = parts[0].get("text")

        if not text:
            return None, f"Gemini returned empty text: {response_body}"

        return text, None

    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)

        return None, f"Gemini HTTP error {exc.code}: {error_body}"

    except Exception as exc:
        return None, str(exc)


def _build_model_list(primary_model: str) -> list[str]:
    models = [
        primary_model,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]

    deduped: list[str] = []

    for model in models:
        if model and model not in deduped:
            deduped.append(model)

    return deduped


def generate_mitchy_json(prompt: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Calls Gemini using the official REST API.

    It tries the configured model first, then fallback models.
    This protects Mitchy from temporary 503/high-demand failures.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    primary_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    if not api_key:
        return None, "GEMINI_API_KEY is not configured", primary_model

    errors: list[str] = []

    for model_name in _build_model_list(primary_model):
        text, error = _call_gemini_once(
            prompt=prompt,
            model_name=model_name,
            api_key=api_key,
        )

        if text:
            return text, None, model_name

        errors.append(f"{model_name}: {error}")

    return None, " | ".join(errors), primary_model
'@

Write-Host "Gemini client now tries fallback models automatically."