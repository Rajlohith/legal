"""
Conversational assistant that turns a chat into search parameters.

Each turn sends the whole conversation to the LLM and asks for JSON
back: a short natural-language reply plus the *complete* set of search
fields understood so far. The LLM only interprets language. Everything
that matters is checked here, in Python:

  * every value is validated against config.py (bench, case type code,
    case year, coram, report type, date format)
  * the "enough to search" rule is enforced here, not by the model:
      - bench is always required
      - AND EITHER a Date of Order range (from_date + to_date)
        OR a full case identity (case_type + case_no + case_year)
  * which scraper to run is decided here:
      - "quick"    -> the site's Quick Search by Case No. page, when the
                      request is exactly bench + type + number + year
      - "detailed" -> the full Detailed Search page for everything else

If the model claims it's ready but the rules say otherwise, the rules
win and the missing pieces are appended to the reply as a question.
"""

import json
import re
from datetime import date

from config import (
    BENCH_OPTIONS,
    CASE_TYPES,
    CASE_YEARS,
    CORAM_OPTIONS,
    REPORT_TYPE_OPTIONS,
)

from backend.llm import LlmError, generate

# ----------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------

BENCH_CODES = set(BENCH_OPTIONS.values())                       # {"B","D","K"}
BENCH_NAMES = {v: k for k, v in BENCH_OPTIONS.items()}
CASE_TYPE_CODES = {str(v): label for v, label in CASE_TYPES}
CASE_YEAR_SET = {str(y) for y in CASE_YEARS if y}
CORAM_CODES = set(str(v) for v in CORAM_OPTIONS.values())
CORAM_NAMES = {str(v): k for k, v in CORAM_OPTIONS.items()}
REPORT_CODES = set(str(v) for v in REPORT_TYPE_OPTIONS.values())
REPORT_NAMES = {str(v): k for k, v in REPORT_TYPE_OPTIONS.items()}

TEXT_FIELDS = (
    "petitioner_name",
    "respondent_name",
    "petitioner_adv",
    "respondent_adv",
    "judge",
    "author_judge",
)
ALL_FIELDS = (
    "db_bench",
    "case_type",
    "case_no",
    "case_year",
    "from_date",
    "to_date",
    "coram",
    "report_type",
    "aliases",
    "alias_field",
) + TEXT_FIELDS

DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


# ----------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------


def _case_type_reference():
    return "\n".join(f"  {v} = {label}" for v, label in CASE_TYPES)


def _system_prompt():
    today = date.today().strftime("%d-%m-%Y")
    return f"""You are the search assistant inside a Karnataka High Court case-search tool.
Your ONLY job is to understand what the person wants to search for and turn it
into values for the court website's search form. You never run the search and
you never invent case data -- a separate scraper does the searching once the
person confirms.

Today's date is {today} (DD-MM-YYYY). Use it to resolve relative dates like
"last 6 months", "this year", "since January".

RULES FOR A SEARCH TO BE POSSIBLE (the tool enforces these; you must too):
  1. Bench is ALWAYS required: "B" Principal Bench (Bengaluru), "D" Dharwad, "K" Kalaburagi.
  2. AND at least ONE of:
       a) a Date of Order range: from_date AND to_date, DD-MM-YYYY
       b) a full case identity: case_type AND case_no AND case_year
If any of these is missing, ask for it -- one clear question at a time,
plain language, no jargon. If the person gives a single date, ask what
range they want. If they name a case type in words (e.g. "writ petition"),
map it to the code from the list below. If they say "Bangalore" or
"Bengaluru" that is the Principal Bench "B".

Keep replies short (1-3 sentences). Do not list the fields back to them --
the interface shows a parameter card automatically. When everything needed
is present, say so briefly and tell them to press Run search.

Also answer general questions about how to use the tool (Detailed Search,
Quick Search, the Excel export) if asked, but steer back to the search.

ALWAYS respond with ONLY a JSON object of this exact shape (no markdown):
{{
  "reply": "<your short message to the person>",
  "fields": {{ ...every field you are confident about, accumulated across the WHOLE conversation... }}
}}

"fields" must contain the full current state, not just what changed this
turn. Only include a key if you are confident of its value; never guess.
Allowed keys:
  "db_bench": "B" | "D" | "K"
  "case_type": case-type CODE as a string from the list below
  "case_no": digits only, max 6
  "case_year": 4-digit year as a string
  "from_date": "DD-MM-YYYY"
  "to_date": "DD-MM-YYYY"
  "petitioner_name": free text
  "respondent_name": free text
  "petitioner_adv": advocate name, free text
  "respondent_adv": advocate name, free text
  "judge": judge name, free text (only if explicitly given)
  "author_judge": judge name, free text (only if explicitly given)
  "coram": "1" Single Bench | "2" Division Bench | "3" Full Bench | "99" Subject Roaster
  "report_type": "Y" Reported | "N" Non-Reported | "none"
  "aliases": array of strings -- ONLY when the person wants several different
             parties/entities searched one after another in one run
  "alias_field": "respondname" | "petname" -- which side the aliases are on

When a person mentions ONE party ("cases against X", "X vs State") put it in
petitioner_name / respondent_name, not aliases. "against X" / "vs X" usually
means X is the respondent. Use aliases only for lists like "search for
Infosys, Wipro and TCS".

Case Type codes:
{_case_type_reference()}

Valid case years: {', '.join(sorted(CASE_YEAR_SET, reverse=True))}
"""


# ----------------------------------------------------------------------
# Validation / normalisation
# ----------------------------------------------------------------------


def _clean(v):
    if v is None:
        return ""
    return " ".join(str(v).split()).strip()


def _valid_date(s):
    if not DATE_RE.match(s):
        return False
    try:
        d, m, y = (int(p) for p in s.split("-"))
        date(y, m, d)
        return True
    except ValueError:
        return False


def _date_key(s):
    d, m, y = (int(p) for p in s.split("-"))
    return (y, m, d)


def _match_case_type(text):
    t = text.strip().lower()
    for code, label in CASE_TYPES:
        l = label.lower()
        if t == l:
            return str(code)
        if " - " in l:
            abbr, desc = l.split(" - ", 1)
            if t == abbr.strip() or t == desc.strip():
                return str(code)
    return None


def normalise_fields(raw):
    """Keep only known fields with valid values. Returns (fields, warnings)."""
    fields = {}
    warnings = []
    if not isinstance(raw, dict):
        return fields, warnings

    bench = _clean(raw.get("db_bench")).upper()
    if bench in BENCH_CODES:
        fields["db_bench"] = bench
    elif bench:
        warnings.append(f"Ignored unknown bench '{bench}'.")

    ct = _clean(raw.get("case_type"))
    if ct:
        if ct in CASE_TYPE_CODES:
            fields["case_type"] = ct
        else:
            # Model may have returned the label ("WP - Writ Petition"),
            # the abbreviation ("WP") or the description ("Writ Petition").
            match = _match_case_type(ct)
            if match:
                fields["case_type"] = match
            else:
                warnings.append(f"Ignored unknown case type '{ct}'.")

    cn = re.sub(r"\D", "", _clean(raw.get("case_no")))
    if cn:
        if len(cn) <= 6:
            fields["case_no"] = cn
        else:
            warnings.append("Case number must be at most 6 digits.")

    cy = _clean(raw.get("case_year"))
    if cy:
        if cy in CASE_YEAR_SET:
            fields["case_year"] = cy
        else:
            warnings.append(f"Ignored case year '{cy}' (not in the site's list).")

    for key in ("from_date", "to_date"):
        v = _clean(raw.get(key)).replace("/", "-")
        if v:
            if _valid_date(v):
                fields[key] = v
            else:
                warnings.append(f"Ignored {key.replace('_', ' ')} '{v}' -- needs DD-MM-YYYY.")

    if "from_date" in fields and "to_date" in fields:
        if _date_key(fields["from_date"]) > _date_key(fields["to_date"]):
            fields["from_date"], fields["to_date"] = fields["to_date"], fields["from_date"]
            warnings.append("Swapped the dates so the range runs forwards.")

    coram = _clean(raw.get("coram"))
    if coram:
        if coram in CORAM_CODES:
            fields["coram"] = coram
        else:
            warnings.append(f"Ignored unknown coram '{coram}'.")

    rt = _clean(raw.get("report_type"))
    if rt:
        if rt in REPORT_CODES:
            fields["report_type"] = rt
        else:
            warnings.append(f"Ignored unknown report type '{rt}'.")

    for key in TEXT_FIELDS:
        v = _clean(raw.get(key))
        if v:
            fields[key] = v[:200]

    aliases = raw.get("aliases")
    if isinstance(aliases, list):
        cleaned = [_clean(a)[:200] for a in aliases if _clean(a)]
        if cleaned:
            fields["aliases"] = cleaned
            af = _clean(raw.get("alias_field"))
            fields["alias_field"] = af if af in ("respondname", "petname") else "respondname"

    return fields, warnings


def missing_requirements(fields):
    """Human-readable list of what still has to be provided."""
    missing = []
    if "db_bench" not in fields:
        missing.append("bench (Principal/Bengaluru, Dharwad or Kalaburagi)")

    has_dates = "from_date" in fields and "to_date" in fields
    has_identity = all(k in fields for k in ("case_type", "case_no", "case_year"))

    if not has_dates and not has_identity:
        # Tell them the nearest path to completeness.
        partial_identity = [k for k in ("case_type", "case_no", "case_year") if k in fields]
        partial_dates = [k for k in ("from_date", "to_date") if k in fields]
        if partial_identity and not partial_dates:
            need = [k.replace("_", " ") for k in ("case_type", "case_no", "case_year") if k not in fields]
            missing.append("the rest of the case identity: " + ", ".join(need) + " (or a date range instead)")
        elif partial_dates:
            need = "end date" if "from_date" in fields else "start date"
            missing.append(f"the {need} of the Date of Order range")
        else:
            missing.append("a Date of Order range (from and to), or the full Case Type + Number + Year")
    return missing


def choose_mode(fields):
    """'quick' when the request is exactly bench + case identity and nothing
    else; 'detailed' for everything that needs the full form."""
    has_identity = all(k in fields for k in ("case_type", "case_no", "case_year"))
    extras = [
        k for k in fields
        if k not in ("db_bench", "case_type", "case_no", "case_year")
    ]
    if has_identity and not extras:
        return "quick"
    return "detailed"


def describe_fields(fields):
    """Labelled view for the UI's parameter card."""
    out = []

    def add(label, value):
        out.append({"key": label, "value": value})

    if "db_bench" in fields:
        add("Bench", BENCH_NAMES.get(fields["db_bench"], fields["db_bench"]))
    if "case_type" in fields:
        add("Case type", f'{CASE_TYPE_CODES.get(fields["case_type"], "?")} ({fields["case_type"]})')
    if "case_no" in fields:
        add("Case number", fields["case_no"])
    if "case_year" in fields:
        add("Case year", fields["case_year"])
    if "from_date" in fields or "to_date" in fields:
        add("Date of order", f'{fields.get("from_date", "…")} → {fields.get("to_date", "…")}')
    if "petitioner_name" in fields:
        add("Petitioner", fields["petitioner_name"])
    if "respondent_name" in fields:
        add("Respondent", fields["respondent_name"])
    if "petitioner_adv" in fields:
        add("Petitioner's advocate", fields["petitioner_adv"])
    if "respondent_adv" in fields:
        add("Respondent's advocate", fields["respondent_adv"])
    if "judge" in fields:
        add("Judge", fields["judge"])
    if "author_judge" in fields:
        add("Author judge", fields["author_judge"])
    if "coram" in fields:
        add("Coram", CORAM_NAMES.get(fields["coram"], fields["coram"]))
    if "report_type" in fields:
        add("Report type", REPORT_NAMES.get(fields["report_type"], fields["report_type"]))
    if "aliases" in fields:
        side = "respondent" if fields.get("alias_field", "respondname") == "respondname" else "petitioner"
        add(f"Aliases ({side})", ", ".join(fields["aliases"]))
    return out


# ----------------------------------------------------------------------
# Turn handling
# ----------------------------------------------------------------------


def _strip_code_fences(raw):
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_model_json(raw):
    cleaned = _strip_code_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Salvage: find the outermost {...}
        m = re.search(r"\{.*\}", cleaned, re.S)
        if not m:
            return {"reply": cleaned, "fields": {}}
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"reply": cleaned, "fields": {}}
    if not isinstance(parsed, dict):
        return {"reply": cleaned, "fields": {}}
    return parsed


def _fields_state_note(fields):
    """Reminds the model of the validated state so it accumulates correctly."""
    if not fields:
        return ""
    return "\n\n[Current validated search fields, keep these unless the person changes them: " \
        + json.dumps(fields, ensure_ascii=False) + "]"


async def assistant_turn(messages, known_fields=None):
    """
    messages: [{"role": "user"|"assistant", "content": str}, ...] oldest first.
    known_fields: the fields the UI already holds (validated on a previous
                  turn), so the model doesn't drop them.

    Returns a dict:
      reply, fields, display, missing, ready, mode, warnings
    Raises LlmError if the model is unreachable/misconfigured.
    """
    known, _ = normalise_fields(known_fields or {})

    # Only the last user message gets the state note appended; earlier
    # turns are passed verbatim.
    convo = [dict(m) for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if convo and convo[-1]["role"] == "user":
        convo[-1]["content"] = convo[-1]["content"] + _fields_state_note(known)

    raw = await generate(convo, system=_system_prompt(), json_mode=True, temperature=0.2)
    parsed = _parse_model_json(raw)

    reply = _clean(parsed.get("reply")) or "Okay."
    model_fields = parsed.get("fields") or {}

    # The model returns the full state; merge on top of what we knew so a
    # forgetful reply can't silently erase a confirmed value.
    merged = dict(known)
    merged.update(model_fields if isinstance(model_fields, dict) else {})
    fields, warnings = normalise_fields(merged)

    missing = missing_requirements(fields)
    ready = not missing
    mode = choose_mode(fields) if ready else None

    # Guardrail: the tool decides readiness, not the model.
    if missing and not re.search(r"\?", reply):
        reply = reply.rstrip(".") + ". I still need " + missing[0] + " — could you give me that?"

    return {
        "reply": reply,
        "fields": fields,
        "display": describe_fields(fields),
        "missing": missing,
        "ready": ready,
        "mode": mode,
        "warnings": warnings,
    }


def build_search_payloads(fields):
    """Translate validated assistant fields into the exact request body
    for /api/search or /api/case-number-search."""
    mode = choose_mode(fields)
    if mode == "quick":
        return mode, {
            "db_bench": fields["db_bench"],
            "case_type": fields["case_type"],
            "case_no": fields["case_no"],
            "case_year": fields["case_year"],
        }
    body = {"db_bench": fields["db_bench"]}
    for k in ALL_FIELDS:
        if k in fields and k != "db_bench":
            body[k] = fields[k]
    body.setdefault("aliases", [])
    body.setdefault("alias_field", "respondname")
    return mode, body


__all__ = [
    "LlmError",
    "assistant_turn",
    "build_search_payloads",
    "choose_mode",
    "missing_requirements",
    "normalise_fields",
]
