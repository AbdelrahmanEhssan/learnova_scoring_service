from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


DEFAULT_TIMEOUT_SECONDS = 12


def _timeout_seconds() -> int:
    try:
        return max(3, min(int(os.getenv("MITCHY_PROVIDER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)), 30))
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def _provider_order() -> list[str]:
    raw = os.getenv("MITCHY_PROVIDER_ORDER", "groq,openrouter,xai")
    providers = []

    for item in raw.split(","):
        provider = item.strip().lower()
        if not provider:
            continue

        # Accept common spelling confusion.
        if provider == "grok":
            provider = "xai"

        if provider not in providers:
            providers.append(provider)

    return providers


def _http_json_post(
    *,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_seconds: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers=headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body), None
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)
        return None, f"HTTP {exc.code}: {error_body}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)}"


def _extract_openai_compatible_text(data: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    choices = data.get("choices") or []
    if not choices:
        return None

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str) and content.strip():
        return content.strip()

    return None


def _call_openai_compatible(
    *,
    provider: str,
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Mitchy, LearNova's friendly learning agent. "
                    "Answer clearly, briefly, and supportively. Avoid medical/legal/financial certainty."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.4,
        "max_tokens": 700,
    }

    data, error = _http_json_post(
        url=url,
        headers=headers,
        payload=payload,
        timeout_seconds=_timeout_seconds(),
    )

    if error:
        return None, f"{provider}: {error}"

    text = _extract_openai_compatible_text(data)

    if not text:
        return None, f"{provider}: empty response"

    return text, None


def _call_groq(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None, "groq: GROQ_API_KEY is not configured"

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    return _call_openai_compatible(
        provider="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        api_key=api_key,
        model=model,
        prompt=prompt,
    )


def _call_openrouter(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None, "openrouter: OPENROUTER_API_KEY is not configured"

    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    headers = {}

    site_url = os.getenv("OPENROUTER_SITE_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME", "LearNova Mitchy")

    if site_url:
        headers["HTTP-Referer"] = site_url

    if app_name:
        headers["X-Title"] = app_name

    return _call_openai_compatible(
        provider="openrouter",
        url="https://openrouter.ai/api/v1/chat/completions",
        api_key=api_key,
        model=model,
        prompt=prompt,
        extra_headers=headers,
    )


def _call_xai(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    """
    xAI/Grok OpenAI-compatible fallback.

    Provider names accepted in MITCHY_PROVIDER_ORDER:
    - xai
    - grok
    """

    api_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not api_key:
        return None, "xai: XAI_API_KEY/GROK_API_KEY is not configured"

    model = os.getenv("XAI_MODEL", os.getenv("GROK_MODEL", "grok-3-mini"))

    return _call_openai_compatible(
        provider="xai",
        url=os.getenv("XAI_API_URL", "https://api.x.ai/v1/chat/completions"),
        api_key=api_key,
        model=model,
        prompt=prompt,
    )


def call_backup_provider(prompt: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Tries configured providers after Gemini fails.

    Returns:
      (text, provider_name, error_string)
    """

    errors: list[str] = []

    for provider in _provider_order():
        if provider == "groq":
            text, error = _call_groq(prompt)
        elif provider == "openrouter":
            text, error = _call_openrouter(prompt)
        elif provider in {"xai", "grok"}:
            text, error = _call_xai(prompt)
            provider = "xai"
        else:
            errors.append(f"{provider}: unsupported provider")
            continue

        if text:
            return text, provider, None

        if error:
            errors.append(error)

    return None, None, " | ".join(errors) if errors else "No backup providers configured"
