"""Provider chain for grading/hint generation.

Design goal: no single provider should be a point of failure. Groq/Gemini/
OpenRouter are supported immediately. GitHub Models can be enabled later by
adding GITHUB_MODELS_API_KEY and putting `github` in AI_PROVIDER_ORDER.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    provider: str
    model: str
    text: str


class ProviderChainError(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__(" | ".join(errors))
        self.errors = errors


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


TIMEOUT = _env_int("AI_PROVIDER_TIMEOUT_SECONDS", 25)
MAX_TOKENS = _env_int("AI_PROVIDER_MAX_TOKENS", 1400)
TEMPERATURE = _env_float("AI_PROVIDER_TEMPERATURE", 0.0)


def provider_order() -> list[str]:
    raw = os.getenv("AI_PROVIDER_ORDER", "groq,gemini,openrouter")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def generate_text(system_prompt: str, user_prompt: str, *, json_schema: Optional[dict] = None) -> ProviderResult:
    errors: list[str] = []
    for provider in provider_order():
        try:
            if provider == "groq":
                return _call_openai_compatible(
                    provider="groq",
                    base_url="https://api.groq.com/openai/v1",
                    api_key=os.getenv("GROQ_API_KEY"),
                    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    json_schema=json_schema,
                )
            if provider == "openrouter":
                return _call_openai_compatible(
                    provider="openrouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key=os.getenv("OPENROUTER_API_KEY"),
                    model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    json_schema=json_schema,
                    extra_headers={
                        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://learnova.local"),
                        "X-Title": os.getenv("OPENROUTER_APP_NAME", "LearNova ML-AI"),
                    },
                )
            if provider == "github":
                return _call_openai_compatible(
                    provider="github",
                    base_url=os.getenv("GITHUB_MODELS_BASE_URL", "https://models.github.ai/inference"),
                    api_key=os.getenv("GITHUB_MODELS_API_KEY"),
                    model=os.getenv("GITHUB_MODEL", "openai/gpt-5-mini"),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    json_schema=json_schema,
                )
            if provider == "gemini":
                return _call_gemini(system_prompt, user_prompt, json_schema=json_schema)
            errors.append(f"unknown provider '{provider}'")
        except Exception as exc:  # deliberately broad to continue chain
            logger.warning("Provider %s failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")
    raise ProviderChainError(errors)


def _call_openai_compatible(
    *,
    provider: str,
    base_url: str,
    api_key: Optional[str],
    model: str,
    system_prompt: str,
    user_prompt: str,
    json_schema: Optional[dict],
    extra_headers: Optional[dict[str, str]] = None,
) -> ProviderResult:
    if not api_key:
        raise RuntimeError(f"missing API key for {provider}")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    payload: Dict[str, Any] = {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "learnova_response", "schema": json_schema, "strict": True},
        }
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    text = data["choices"][0]["message"].get("content") or ""
    if not text.strip():
        raise RuntimeError("empty response")
    return ProviderResult(provider=provider, model=model, text=text)


def _call_gemini(system_prompt: str, user_prompt: str, *, json_schema: Optional[dict]) -> ProviderResult:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("missing GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload: Dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": TEMPERATURE, "maxOutputTokens": MAX_TOKENS},
    }
    if json_schema:
        payload["generationConfig"].update(
            {"responseMimeType": "application/json", "responseSchema": json_schema}
        )
    resp = requests.post(f"{url}?key={api_key}", json=payload, timeout=TIMEOUT)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0].get("text") or ""
    if not text.strip():
        raise RuntimeError("empty response")
    return ProviderResult(provider="gemini", model=model, text=text)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise
