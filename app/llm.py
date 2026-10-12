"""Model backends: cloud, private cloud, local, and an offline placeholder.

Chain order comes from `LLM_CHAIN` (comma list of `anthropic`, `local`), so a
laptop falls back from the cloud model to a local one when the network drops.
With nothing configured the app uses `offline`, which returns a clearly
labelled placeholder instead of pretending to write.

  anthropic  ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_BASE_URL (gateway or
             private-cloud endpoint that speaks the Messages API)
  local      LLM_BASE_URL (OpenAI-compatible: Ollama, LM Studio, vLLM, llama.cpp),
             LLM_MODEL, LLM_API_KEY (optional)
"""
from __future__ import annotations

import os
from typing import Optional

import requests

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))


class LLMError(RuntimeError):
    pass


def chain() -> list[str]:
    explicit = os.getenv("LLM_CHAIN", "").strip()
    if explicit:
        return [p.strip() for p in explicit.split(",") if p.strip()]
    out = []
    if os.getenv("ANTHROPIC_API_KEY"):
        out.append("anthropic")
    if os.getenv("LLM_BASE_URL"):
        out.append("local")
    return out or ["offline"]


def _anthropic(system: str, user: str, max_tokens: int) -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    r = requests.post(
        f"{base}/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise LLMError(f"anthropic {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


def _local(system: str, user: str, max_tokens: int) -> str:
    base = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['LLM_API_KEY']}"} if os.getenv("LLM_API_KEY") else {}
    r = requests.post(
        f"{base}/chat/completions",
        headers=headers,
        json={
            "model": os.getenv("LLM_MODEL", "llama3.1"),
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise LLMError(f"local {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _offline(system: str, user: str, max_tokens: int) -> str:
    head = user.strip().splitlines()[0][:120] if user.strip() else ""
    return (
        "[OFFLINE PLACEHOLDER: no model configured]\n"
        f"Task received: {head}\n"
        "Set ANTHROPIC_API_KEY, or LLM_BASE_URL for a local model (Ollama, LM Studio), "
        "to get real output."
    )


BACKENDS = {"anthropic": _anthropic, "local": _local, "offline": _offline}


def complete(system: str, user: str, *, max_tokens: int = 4096) -> tuple[str, str]:
    """Return (text, backend_used). Tries the chain in order."""
    errors = []
    for name in chain():
        fn = BACKENDS.get(name)
        if not fn:
            errors.append(f"{name}: unknown backend")
            continue
        try:
            return fn(system, user, max_tokens), name
        except (requests.RequestException, LLMError, KeyError) as e:
            errors.append(f"{name}: {e}")
    raise LLMError("; ".join(errors) or "no backend available")


def describe() -> dict:
    return {
        "chain": chain(),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
        "local_model": os.getenv("LLM_MODEL", "llama3.1") if os.getenv("LLM_BASE_URL") else None,
    }
