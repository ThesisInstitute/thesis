"""Shared LLM client for experiments.

Supports both Anthropic (Claude) and OpenAI (GPT) models.
Provider is auto-detected from the model name.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

# Lazy imports — populated on first use
_anthropic_client: Optional[object] = None
_openai_client: Optional[object] = None

MAX_RETRIES = 4
INITIAL_RETRY_DELAY_SECONDS = 2.0


def _is_openai_model(model: str) -> bool:
    """Detect whether a model ID is OpenAI vs Anthropic."""
    prefixes = ("gpt-", "o1", "o3", "o4")
    return any(model.startswith(p) for p in prefixes)


def _load_key_from_keychain(name: str) -> Optional[str]:
    """Load a secret through the `agent-secret` CLI (a dedicated macOS keychain).

    The login keychain's "claude-env" items this used to read were retired into
    that keychain; `agent-secret` unlocks it without a password dialog.
    """
    try:
        result = subprocess.run(
            ["agent-secret", "get", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _load_anthropic_key() -> str:
    """Load Anthropic API key from env, then agent-secret."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    key = _load_key_from_keychain("ANTHROPIC_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "ANTHROPIC_API_KEY not found. Set it as an environment variable "
        "or store it with `agent-secret set ANTHROPIC_API_KEY`."
    )


def _load_openai_key() -> str:
    """Load OpenAI API key from env, then agent-secret."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    key = _load_key_from_keychain("OPENAI_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "OPENAI_API_KEY not found. Set it as an environment variable "
        "or store it with `agent-secret set OPENAI_API_KEY`."
    )


def _get_anthropic_client():
    """Get or create cached Anthropic client."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=_load_anthropic_key())
    return _anthropic_client


def _get_openai_client():
    """Get or create cached OpenAI client."""
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.OpenAI(api_key=_load_openai_key())
    return _openai_client


def call_llm(
    prompt: str,
    model: str = "claude-opus-4-6",
    max_tokens: int = 4096,
    temperature: float = 1.0,
    timeout: float = 180.0,
    max_retries: int = MAX_RETRIES,
) -> tuple[str, float]:
    """Call an LLM and return (response_text, duration_seconds).

    Provider is auto-detected from the model name:
    - gpt-*, o1*, o3*, o4* -> OpenAI
    - everything else -> Anthropic

    Args:
        prompt: The user message to send
        model: Model ID (e.g. "claude-opus-4-6", "gpt-5.2")
        max_tokens: Max response tokens
        temperature: Sampling temperature (1.0 = default, good for experiment variance)
        timeout: Request timeout in seconds

    Returns:
        Tuple of (response_text, duration_seconds)
    """
    start = time.time()

    provider_call = (
        _call_openai if _is_openai_model(model) else _call_anthropic
    )
    response = ""
    for attempt in range(max_retries + 1):
        response = provider_call(prompt, model, max_tokens, temperature, timeout)
        if not _is_retryable_error(response) or attempt == max_retries:
            break
        delay = min(INITIAL_RETRY_DELAY_SECONDS * (2 ** attempt), 20.0)
        time.sleep(delay)

    duration = time.time() - start
    return response, duration


def _is_retryable_error(response: str) -> bool:
    """Return whether an API error string should be retried."""
    if not response.startswith("ERROR:"):
        return False

    normalized = response.lower()
    retryable_markers = (
        "timeout",
        "timed out",
        "overloaded",
        "rate limit",
        "429",
        "529",
        "service unavailable",
        "temporarily unavailable",
        "internal server error",
        "connection reset",
    )
    return any(marker in normalized for marker in retryable_markers)


def _call_anthropic(
    prompt: str, model: str, max_tokens: int, temperature: float, timeout: float
) -> str:
    """Call the Anthropic API."""
    import anthropic

    client = _get_anthropic_client()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=timeout,
        )
        return message.content[0].text
    except anthropic.APITimeoutError:
        return "ERROR: Timeout"
    except anthropic.APIError as e:
        return f"ERROR: {e}"


def _call_openai(
    prompt: str, model: str, max_tokens: int, temperature: float, timeout: float
) -> str:
    """Call the OpenAI API."""
    import openai

    client = _get_openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            timeout=timeout,
        )
        return response.choices[0].message.content
    except openai.APITimeoutError:
        return "ERROR: Timeout"
    except openai.APIError as e:
        return f"ERROR: {e}"


def model_short_name(model: str) -> str:
    """Convert a model ID to a filesystem-safe short name.

    Examples:
        "claude-opus-4-6" -> "claude-opus-4-6"
        "gpt-5.2" -> "gpt-5.2"
    """
    # Already filesystem-safe for our purposes
    return model
