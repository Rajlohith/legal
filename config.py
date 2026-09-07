"""
Central configuration for the Karnataka Judiciary case search tool.

Nothing in this file talks to the browser or the filesystem — it's just
constants, so every other module can import from one place instead of
redefining the same values.
"""

import os
import platform

# ------------------------------------------------------------------
# Target website
# ------------------------------------------------------------------

SEARCH_URL = "https://www.judiciary.karnataka.gov.in/rep_judgment.php"

# ------------------------------------------------------------------
# Case detail sections
# ------------------------------------------------------------------
# Exact sheet order requested, mapped to their div id.
# "Case Information" (div id="H") is handled separately from the rest
# because, unlike every other section, its content div has no id and
# is visible by default rather than hidden behind divopen().
SECTION_ORDER = [
    ("H15", "Prayer Information"),
    ("H1", "Party Information"),
    ("H12", "Caveator/Caveatee Information"),
    ("H2", "Trial/Appellate Information"),
    ("H17", "Supreme Court Appellate Information"),
    ("H3", "Daily Orders Information"),
    ("H4", "Linked Cases"),
    ("H5", "Judgment Information"),
    ("H6", "Certified Copy Information (Final Order)"),
    ("H13", "Certified Copy Information (Interim Order)"),
    ("H7", "Index Sheet Information"),
    ("H8", "Scrutiny Information"),
    ("H9", "Interlocutory Applications (IA) Information"),
    ("H10", "Documents Information"),
    ("H11", "Postal Information"),
    ("H14", "Judicial Deposit"),
    ("H18", "Fees Information"),
]

NO_DATA_MARKERS = {
    "", "record_not_found", "no data found", "please wait...",
}

DETAILS_COLUMN = "Details"

# ------------------------------------------------------------------
# Bench options (shown in the UI, mapped to the site's <select> value)
# ------------------------------------------------------------------

BENCH_OPTIONS = {
    "Principal Bench": "B",
    "Dharwad Bench": "D",
    "Kalaburagi Bench": "K",
}

# ------------------------------------------------------------------
# Search behaviour
# ------------------------------------------------------------------

MAX_DATE_WINDOW_DAYS = 90          # site limits each query to a 90-day window
MAX_CAPTCHA_ATTEMPTS = 5
DEFAULT_OUTPUT_FILENAME = "Case_Search_Results.xlsx"

# ------------------------------------------------------------------
# Tesseract OCR path
# ------------------------------------------------------------------
# The original script hardcoded a Windows path. We try a few sensible
# defaults per OS and otherwise let the user point to it from the UI's
# Settings panel (saved in user_settings.json next to this file).

def default_tesseract_path():
    system = platform.system()
    candidates = []
    if system == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    elif system == "Darwin":
        candidates = ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
    else:
        candidates = ["/usr/bin/tesseract"]

    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0] if candidates else ""


DEFAULT_TESSERACT_PATH = default_tesseract_path()
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")
