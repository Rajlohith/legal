"""
Plain text/string helpers used while parsing scraped case data.
No Playwright or pandas dependencies here on purpose -- keeps this
module trivial to unit test.
"""

import re

from config import NO_DATA_MARKERS


def clean_text(text):
    """Collapse whitespace, normalize 'no data' variants to empty string."""
    if text is None:
        return ""

    normalized = " ".join(text.split())

    if normalized.strip().lower() in NO_DATA_MARKERS:
        return ""

    return normalized


def sanitize_sheet_name(name):
    """
    Excel sheet names cannot contain: \\ / * ? : [ ]
    and must be 31 characters or fewer.
    """
    invalid_chars = ['\\', '/', '*', '?', ':', '[', ']']
    cleaned = name
    for ch in invalid_chars:
        cleaned = cleaned.replace(ch, "-")
    return cleaned[:31]


def sanitize_filename_part(name):
    """Keep user-provided aliases safe for use in output filenames."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", name).strip(" .")
    return cleaned or "Search"


def split_party_names(value):
    """Split the judgment table's combined petitioner/respondent value."""
    parts = re.split(r"\s+V/S\s+", clean_text(str(value)), maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


def case_identity(base_row):
    """Return a stable key for recognizing the same case across aliases."""
    identifier = tuple(
        clean_text(str(base_row.get(field, ""))).lower()
        for field in ("Case Type", "Case No", "Case Year")
    )

    if all(identifier):
        return identifier

    return tuple(
        sorted(
            (str(key).lower(), clean_text(str(value)).lower())
            for key, value in base_row.items()
        )
    )
