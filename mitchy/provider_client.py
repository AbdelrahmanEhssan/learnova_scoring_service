from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from mitchy.gemini_client import generate_mitchy_json

DEFAULT_TIMEOUT_SECONDS = 20


def _timeout_seconds() -> int:
    try:
        return max(5, min(int(os.getenv("MITCHY_PROVIDER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)), 45))
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def _provider_order() -> list[str]:
    raw = os.getenv("MITCHY_PROVIDER_ORDER", "groq,gemini,openrouter,xai")
    providers: list[str] = []
    for item in raw.split(","):
        provider = item.strip().lower()
        if not provider:
            continue
        if provider == "grok":
            provider = "xai"
        if provider not in providers:
            providers.append(provider)
    return providers


def _http_json_post(*, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_seconds: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    default_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": os.getenv("MITCHY_HTTP_USER_AGENT", "LearNova-Mitchy/1.0"),
    }
    default_headers.update(headers)
    request = urllib.request.Request(url=url, data=data, method="POST", headers=default_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = str(exc)
        return None, f"HTTP {exc.code}: {error_body[:800]}"
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


def _call_openai_compatible(*, provider: str, url: str, api_key: str, model: str, prompt: str, extra_headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are Mitchy, LearNova's virtual Learning Assistant. Follow the user-context and output-contract inside the user prompt. Answer directly when the user's question is clear. Do not greet unless the user only greeted you."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(os.getenv("MITCHY_PROVIDER_TEMPERATURE", "0.25")),
        "max_tokens": int(os.getenv("MITCHY_PROVIDER_MAX_TOKENS", "900")),
    }
    data, error = _http_json_post(url=url, headers=headers, payload=payload, timeout_seconds=_timeout_seconds())
    if error:
        return None, f"{provider}: {error}"
    text = _extract_openai_compatible_text(data)
    if not text:
        return None, f"{provider}: empty response"
    return text, None


def _call_generic_openai(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    """Generic OpenAI-compatible provider. Lets you switch providers via env only."""
    base_url = os.getenv("AI_BASE_URL")
    api_key = os.getenv("AI_API_KEY")
    model = os.getenv("AI_MODEL")
    if not (base_url and api_key and model):
        return None, "primary: AI_BASE_URL/AI_API_KEY/AI_MODEL not fully configured"
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    return _call_openai_compatible(provider="primary", url=url, api_key=api_key, model=model, prompt=prompt)


def _call_groq(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None, "groq: GROQ_API_KEY is not configured"
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    return _call_openai_compatible(provider="groq", url="https://api.groq.com/openai/v1/chat/completions", api_key=api_key, model=model, prompt=prompt)


def _call_openrouter(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None, "openrouter: OPENROUTER_API_KEY is not configured"
    model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    headers: Dict[str, str] = {}
    site_url = os.getenv("OPENROUTER_SITE_URL")
    app_name = os.getenv("OPENROUTER_APP_NAME", "LearNova Mitchy")
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name
    return _call_openai_compatible(provider="openrouter", url="https://openrouter.ai/api/v1/chat/completions", api_key=api_key, model=model, prompt=prompt, extra_headers=headers)


def _call_xai(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not api_key:
        return None, "xai: XAI_API_KEY/GROK_API_KEY is not configured"
    model = os.getenv("XAI_MODEL", os.getenv("GROK_MODEL", "grok-3-mini"))
    return _call_openai_compatible(provider="xai", url=os.getenv("XAI_API_URL", "https://api.x.ai/v1/chat/completions"), api_key=api_key, model=model, prompt=prompt)


def _call_gemini(prompt: str) -> Tuple[Optional[str], Optional[str]]:
    text, error, model = generate_mitchy_json(prompt)
    if text:
        return text, None
    return None, f"gemini: {error or 'empty response'}"


def call_backup_provider(prompt: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Tries all configured providers in order. Fallback text is only used after every provider fails."""
    errors: list[str] = []
    for provider in _provider_order():
        if provider in {"primary", "generic"}:
            text, error = _call_generic_openai(prompt)
            provider_name = "primary"
        elif provider == "groq":
            text, error = _call_groq(prompt)
            provider_name = "groq"
        elif provider == "gemini":
            text, error = _call_gemini(prompt)
            provider_name = "gemini"
        elif provider == "openrouter":
            text, error = _call_openrouter(prompt)
            provider_name = "openrouter"
        elif provider in {"xai", "grok"}:
            text, error = _call_xai(prompt)
            provider_name = "xai"
        else:
            errors.append(f"{provider}: unsupported provider")
            continue
        if text:
            return text, provider_name, None
        if error:
            errors.append(error)
    return None, None, " | ".join(errors) if errors else "No providers configured"
