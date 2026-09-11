"""
One thin transport layer for the configured LLM. Everything that talks
to Gemini / an OpenAI-compatible endpoint goes through here, so the
assistant (backend/assistant.py) and the one-shot form filler
(backend/ai_fill.py) share the same key handling, timeouts and error
messages.

The LLM is only ever used for natural-language understanding. It never
touches the court website; the Playwright + Tesseract scraper does that.
"""

import os

import httpx

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


class LlmError(RuntimeError):
    """The configured LLM isn't set up, unreachable, or returned junk."""


def _check_provider():
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise LlmError("GEMINI_API_KEY is not set. Add it to your .env file.")
    elif LLM_PROVIDER in ("openai", "openai_compatible"):
        if not OPENAI_API_KEY:
            raise LlmError("OPENAI_API_KEY is not set. Add it to your .env file.")
    else:
        raise LlmError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Set it to 'gemini' or 'openai' in your .env file."
        )


async def generate(messages, system=None, json_mode=False, temperature=0.2):
    """
    messages: list of {"role": "user"|"assistant", "content": str}, oldest first.
    Returns the model's text. Raises LlmError on any problem.
    """
    _check_provider()
    if LLM_PROVIDER == "gemini":
        return await _gemini(messages, system, json_mode, temperature)
    return await _openai(messages, system, json_mode, temperature)


async def _post(url, payload, headers=None):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers or {})
    except httpx.TimeoutException as e:
        raise LlmError("The AI model took too long to respond. Please try again.") from e
    except httpx.HTTPError as e:
        raise LlmError(f"Could not reach the AI model: {e}") from e

    if resp.status_code != 200:
        raise LlmError(f"AI API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


async def _gemini(messages, system, json_mode, temperature):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    data = await _post(url, payload, headers={"x-goog-api-key": GEMINI_API_KEY})
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise LlmError(f"Unexpected Gemini response shape: {str(data)[:500]}")


async def _openai(messages, system, json_mode, temperature):
    url = f"{OPENAI_BASE_URL}/chat/completions"
    chat = []
    if system:
        chat.append({"role": "system", "content": system})
    chat.extend({"role": m["role"], "content": m["content"]} for m in messages)
    payload = {"model": OPENAI_MODEL, "messages": chat, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = await _post(url, payload, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"})
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError(f"Unexpected chat-completions response shape: {str(data)[:500]}")
