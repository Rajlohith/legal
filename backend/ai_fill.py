"""
Natural language -> structured search-form values, via a configurable
LLM. The model is only ever asked to *interpret* the person's request
into values that already exist on the real form (see config.py) -- it
never touches the browser or the site itself. The Playwright +
Tesseract scraper in scraper/search_engine.py is what actually runs
the search, exactly as before.

Provider is chosen with the LLM_PROVIDER environment variable:
  LLM_PROVIDER=gemini   (default) -- uses GEMINI_API_KEY / GEMINI_MODEL
  LLM_PROVIDER=openai            -- uses OPENAI_API_KEY / OPENAI_MODEL
                                     / OPENAI_BASE_URL (OpenAI-compatible,
                                     so this also works with Groq, a local
                                     Ollama/vLLM server, etc.)
"""

import json
import os
import re

import httpx

from config import CASE_TYPES, CASE_YEARS

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# Gemini can sometimes take longer than the default 30-second timeout.
GEMINI_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=120.0,
    write=30.0,
    pool=10.0,
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


class AiFillError(RuntimeError):
    """The configured LLM isn't set up, unreachable, or returned junk."""


FIELD_SCHEMA_DOC = """\
Return ONLY a JSON object (no prose, no markdown fences) with any of these
keys you are confident about. Omit a key entirely if the request doesn't
support it -- never guess a value.

  "db_bench": one of "B" (Principal Bench, Bengaluru), "D" (Dharwad Bench), "K" (Kalaburagi Bench)
  "case_type": the numeric code (as a string) from the Case Type list below
  "case_no": digits only, up to 6 digits
  "case_year": a 4-digit year (as a string) from the Case Year list below
  "petitioner_name": free text
  "respondent_name": free text
  "petitioner_adv": free text (advocate name)
  "respondent_adv": free text (advocate name)
  "coram": one of "1" (Single Bench), "2" (Division Bench), "3" (Full Bench), "99" (Subject Roaster)
  "report_type": one of "Y" (Reported), "N" (Non-Reported), "none"
  "from_date": "DD-MM-YYYY"
  "to_date": "DD-MM-YYYY"
  "aliases": a JSON array of strings, only if the person wants to search
             several different people/companies/entities in one run
  "alias_field": "respondname" or "petname" -- which name field the
             "aliases" list should be searched under (default respondname)
  "notes": one short plain-English sentence about anything ambiguous or
             left out, or null if there's nothing to flag
"""


def _case_type_reference():
    return "\n".join(f"{value} = {label}" for value, label in CASE_TYPES)


def _build_prompt(nl_text):
    return (
        "You convert a person's plain-English description of a court case "
        "search into structured values for the Karnataka High Court's "
        "public case-search form. Only use values that are valid for that "
        "form; when unsure, leave the field out rather than guessing.\n\n"
        f"{FIELD_SCHEMA_DOC}\n"
        "Valid Case Type codes:\n"
        f"{_case_type_reference()}\n\n"
        f"Valid Case Years: {', '.join(str(y) for y in CASE_YEARS if y)}\n\n"
        f'Person\'s request:\n"""{nl_text}"""\n\n'
        "JSON:"
    )


def _strip_code_fences(raw):
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


async def _call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise AiFillError("GEMINI_API_KEY is not set. Add it to your .env file.")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }

    try:
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException as e:
        raise AiFillError(
            "Gemini took too long to respond. Please try again."
        ) from e

    if resp.status_code != 200:
        raise AiFillError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise AiFillError(f"Unexpected Gemini response shape: {data}")


async def _call_openai_compatible(prompt):
    if not OPENAI_API_KEY:
        raise AiFillError("OPENAI_API_KEY is not set. Add it to your .env file.")

    url = f"{OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "You output only valid JSON, nothing else."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        raise AiFillError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AiFillError(f"Unexpected chat-completions response shape: {data}")


CHAT_SYSTEM_PROMPT = (
    "You are the assistant embedded in the Karnataka Judiciary Case Search "
    "tool. Be concise and helpful. You cannot run searches yourself -- if "
    "the person wants to actually find a case, point them to 'Detailed "
    "Search' (for broad/exploratory searches, judge, party names, date "
    "ranges, multiple aliases) or 'Quick Search' (when they already know "
    "the exact Bench, Case Type, Case Number and Case Year) in the sidebar. "
    "You can also help them think through what to type into those forms."
)


async def _call_gemini_chat(messages):
    if not GEMINI_API_KEY:
        raise AiFillError("GEMINI_API_KEY is not set. Add it to your .env file.")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
    ]
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": CHAT_SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.4},
    }

    try:
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException as e:
        raise AiFillError(
            "Gemini took too long to respond. Please try again."
        ) from e

    if resp.status_code != 200:
        raise AiFillError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise AiFillError(f"Unexpected Gemini response shape: {data}")


async def _call_openai_compatible_chat(messages):
    if not OPENAI_API_KEY:
        raise AiFillError("OPENAI_API_KEY is not set. Add it to your .env file.")

    url = f"{OPENAI_BASE_URL}/chat/completions"
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + list(messages),
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if resp.status_code != 200:
        raise AiFillError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AiFillError(f"Unexpected chat-completions response shape: {data}")


async def chat_reply(messages):
    """
    messages: list of {"role": "user"|"assistant", "content": str}, oldest first.
    Returns the assistant's reply text. Raises AiFillError on any
    configuration or upstream problem.
    """
    if LLM_PROVIDER == "gemini":
        raw = await _call_gemini_chat(messages)
    elif LLM_PROVIDER in ("openai", "openai_compatible"):
        raw = await _call_openai_compatible_chat(messages)
    else:
        raise AiFillError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Set it to 'gemini' or 'openai' in your .env file."
        )

    return raw.strip()


async def ai_fill_form(nl_text):
    """
    Returns (fields: dict, notes: str | None).
    Raises AiFillError on any configuration or parsing problem.
    """
    prompt = _build_prompt(nl_text)

    if LLM_PROVIDER == "gemini":
        raw = await _call_gemini(prompt)
    elif LLM_PROVIDER in ("openai", "openai_compatible"):
        raw = await _call_openai_compatible(prompt)
    else:
        raise AiFillError(
            f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Set it to 'gemini' or 'openai' in your .env file."
        )

    cleaned = _strip_code_fences(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise AiFillError(f"The model didn't return valid JSON ({e}). Raw output: {cleaned[:500]}")

    if not isinstance(parsed, dict):
        raise AiFillError("The model's JSON output wasn't an object.")

    notes = parsed.pop("notes", None)
    return parsed, notes
