"""
One-shot natural language -> structured search-form values.

Kept for the /api/ai-fill route. The conversational assistant
(backend/assistant.py) supersedes this for the AI Assistant page, but
the route is still useful for a "fill this form from a sentence"
button. Both use the same validation in backend/assistant.py, so a
value that reaches the scraper has always been checked against
config.py.
"""

from backend.assistant import assistant_turn, missing_requirements
from backend.llm import LlmError

AiFillError = LlmError  # backwards-compatible name


async def ai_fill_form(nl_text):
    """
    Returns (fields: dict, notes: str | None).
    Raises AiFillError on any configuration or upstream problem.
    """
    result = await assistant_turn([{"role": "user", "content": nl_text}])
    fields = result["fields"]
    notes = []
    missing = missing_requirements(fields)
    if missing:
        notes.append("Still needed: " + "; ".join(missing) + ".")
    notes.extend(result.get("warnings") or [])
    return fields, (" ".join(notes) if notes else None)
