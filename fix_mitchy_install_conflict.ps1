Set-Content -Path "requirements.txt" -Encoding UTF8 -Value @'
fastapi==0.111.0
uvicorn==0.29.0
supabase==2.4.6
python-dotenv==1.0.1
pandas==2.2.3
openpyxl==3.1.2
'@

Set-Content -Path "mitchy/gemini_client.py" -Encoding UTF8 -Value @'
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional, Tuple


def generate_mitchy_json(prompt: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Calls Gemini using the official REST API instead of google-genai.

    Why REST?
    - supabase==2.4.6 requires httpx<0.28
    - google-genai requires httpx>=0.28.1
    - using urllib avoids the dependency conflict completely
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    if not api_key:
        return None, "GEMINI_API_KEY is not configured", model_name

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
            return None, f"Gemini returned no candidates: {response_body}", model_name

        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []

        if not parts:
            return None, f"Gemini returned no content parts: {response_body}", model_name

        text = parts[0].get("text")

        if not text:
            return None, f"Gemini returned empty text: {response_body}", model_name

        return text, None, model_name

    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)

        return None, f"Gemini HTTP error {exc.code}: {error_body}", model_name

    except Exception as exc:
        return None, str(exc), model_name
'@

Write-Host "Fixed requirements.txt and switched Gemini client to REST urllib."