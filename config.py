"""
Central configuration for the Iudicium case search tool.

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

# The site's own "Quick Search by Case No." page (separate from the
# Detailed Search above) -- linked from the site's Judgments menu as
# rep_judgmentcasebc.php. Same site codebase, so it reuses the same
# element ids (#db_bench, #cmbcasetype, #caseno, #caseyear, #vercode,
# #generate, #reload-button, #dynamic-content-year) but exposes only
# Bench + Case Type + Case Number + Case Year -- no dates, no judge,
# no party names.
CASE_NUMBER_SEARCH_URL = "https://www.judiciary.karnataka.gov.in/rep_judgmentcasebc.php"

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
# All other search-form fields on rep_judgment.php
# ------------------------------------------------------------------
# These were read directly out of the page's HTML/JS (see #form1 and
# benchfunction()/required() in the page source) rather than guessed,
# so the values below are exactly what the site's own <select> tags
# and AJAX calls use.
#
#   #db_bench      -- "Select Bench" dropdown above the form. Same
#                      values as BENCH_OPTIONS above; picking one
#                      triggers connect(), which AJAX-loads the judge
#                      lists below and reveals the rest of the form.
#   #cmbjudge       -- "Judge" (optional). Populated dynamically by
#                      connect() via rep_getjud_name.php for the
#                      chosen bench -- see scraper/judge_lookup.py.
#   #cmbauthjudge   -- "Author Judge" (optional). Same option list as
#                      #cmbjudge, loaded by the same call.
#   #cmbbench       -- "Coram" (optional). Static options below.
#   #cmbcasetype    -- "Case Type" (optional). Static options below.
#   #caseno         -- "Case Number" (optional). Free text, digits
#                      only, max length 6 (enforced client-side).
#   #caseyear       -- "CaseYear" (optional). Static options below.
#   #petname        -- "Petitioner Name" (optional). Free text.
#   #respondname    -- "Respondent Name" (optional). Free text.
#   #petadv         -- "Petitioner Advocate" (optional). Free text.
#   #respondadv     -- "Respondent Advocate" (optional). Free text.
#   #dp1 / #dp2     -- "Date of Order" From/To. Required *unless*
#                      Case Type + Case Number + Case Year are all
#                      filled in (the page's own benchfunction() logic).
#   #r1/#r2/#r3     -- "Reported" / "Non-Reported" / "None" radio
#                      group (name="rate"); #r3 ("none") is the
#                      page's own default.
#   #vercode        -- CAPTCHA text, handled entirely by
#                      scraper/captcha.py already.


# NOTE: the site's own <select> also has a "--Select--" placeholder
# option with value "4" (its way of saying "no coram filter"). We
# don't include it here because the UI already has its own blank
# placeholder for "not set" -- so a coram value is only ever sent to
# the site when the person actually picked one of the four below.
CORAM_OPTIONS = {
    "Single Bench": "1",
    "Division Bench": "2",
    "Full Bench": "3",
    "Subject Roaster": "99",
}

REPORT_TYPE_OPTIONS = {
    "None": "none",
    "Reported": "Y",
    "Non-Reported": "N",
}
REPORT_TYPE_RADIO_IDS = {"Y": "r1", "N": "r2", "none": "r3"}

# "value" -> "Code - Description", exactly as listed in the
# #cmbcasetype <select>, sorted the same way the site presents them.
CASE_TYPES = [
    ("156", "AC - Arbitration Case"),
    ("170", "AP.EFA - Arbitration Petition(Enforcement of Foreign Arbitral Award)"),
    ("168", "AP.IM - Arbitration Petition-Interim Measure"),
    ("101", "CA - Company Application"),
    ("157", "CAV_RSA - CAVEAT IN RSA"),
    ("158", "CAV_WP - Caveat Writ Petition"),
    ("143", "CCC - Civil Contempt Petition"),
    ("169", "CC(CIA) - Criminal Complaint (Commissions of Inquiry Act)"),
    ("104", "CEA - Central Excise Appeal"),
    ("105", "CMP - CIVIL MISC. PETITION"),
    ("155", "COA - U/s 10(f) of the Companies Act"),
    ("171", "COMAP - Commercial Appeals"),
    ("176", "COMAP.CR - Commercial Appeals Cross Objection"),
    ("173", "COM.APLN - Commercial Application"),
    ("178", "COM.OS - COM.OS"),
    ("103", "COMPA - Company Appeal"),
    ("177", "COM.S - Commercial Suit"),
    ("102", "COP - Company Petition"),
    ("106", "CP - Civil Petition"),
    ("159", "CP.KLRA - CP On Karnataka Land Reforms Act"),
    ("160", "CRA - CROSS APPEALS"),
    ("107", "CRC - Civil Referred Case"),
    ("110", "CRL.A - Criminal Appeal"),
    ("111", "CRL.CCC - Criminal Contempt Petition"),
    ("112", "CRL.P - Criminal Petition"),
    ("113", "CRL.RC - Criminal Referred Case"),
    ("114", "CRL.RP - Criminal Revision Petition"),
    ("161", "CROB - Cross Objection"),
    ("108", "CRP - Civil Revision Petition"),
    ("115", "CSTA - Customs Appeal"),
    ("116", "EP - Election Petition"),
    ("117", "EX.FA - EXECUTION FIRST APPEAL"),
    ("118", "EX.SA - EXECUTION SECOND APPEAL"),
    ("148", "GTA - Gift Tax Appeal"),
    ("119", "HRRP - House Rent Rev. Petition"),
    ("120", "ITA - Income Tax Appeal"),
    ("162", "ITA.CROB - I.T Appeal CROSS Objection"),
    ("121", "ITRC - Income-tax referred case"),
    ("122", "LRRP - Land Reforms Revision Petition"),
    ("123", "LTRP - LUXURY TAX REVISION PETN."),
    ("124", "MFA - Miscellaneous First Appeal"),
    ("125", "MFA.CROB - MFA Cross Objection"),
    ("175", "MISC - MISC"),
    ("164", "MISC.CRL - Miscellaneous Case for Crml"),
    ("165", "MISC.CVL - Miscellaneous Case for Civil"),
    ("166", "MISC.P - Misc Petition"),
    ("167", "MISC.W - Miscellaneous Case for Writ"),
    ("126", "MSA - Miscellaneous Second Appeal"),
    ("127", "MSA.CROB - MSA Cross Objection"),
    ("128", "OLR - Official Liquidator Report"),
    ("154", "OS - Original Suit"),
    ("129", "OSA - Original Side Appeal"),
    ("130", "OSA.CROB - OSA Cross Objection"),
    ("131", "PROB.CP - Probate Civil Petition"),
    ("153", "RA - Regular Appeal"),
    ("172", "RERA.A - RERA APPEALS"),
    ("179", "RERA.CRB - RERA Appeals cross-objection"),
    ("132", "RFA - Regular First Appeal"),
    ("133", "RFA.CROB - RFA Cross Objection"),
    ("134", "RP - Review Petition"),
    ("135", "RPFC - Rev.Pet Family Court"),
    ("136", "RSA - Regular Second Appeal"),
    ("137", "RSA.CROB - RSA Cross Objection"),
    ("174", "SA - Second Appeal"),
    ("152", "SCLAP - SUPREME COURT LEAVE APPLICATION"),
    ("138", "STA - Sales Tax Appeal"),
    ("139", "STRP - Sales Tax Revision Petition"),
    ("151", "TAET - Tax Appeal on Entry Tax"),
    ("141", "TOS - Testamentory Original Suit"),
    ("142", "TRC - Tax referred cases"),
    ("145", "WA - Writ Appeal"),
    ("147", "WA.CROB - WA Cross Objection"),
    ("144", "WP - Writ Petition"),
    ("150", "WPCP - Civil Pet in Writ Side"),
    ("146", "WPHC - Habeas Corpus"),
    ("149", "WTA - Wealth Tax Appeal"),
]

# The #caseyear <select> on the site. It is a static list (not tied to
# the current year), copied verbatim; kept oldest-last to match the
# page's own order.
CASE_YEARS = [
    2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016,
    2015, 2014, 2013, 2012, 2011, 2010, 2009, 2008, 2007, 2006, 2005,
    2004, 2003, 2002, 2001, 2000, 1999, 1998, 1997, 1996, 1995, 1994,
    1993, 1992, 1991, 1990, 1989, 1988, 1987, 1986, 1985, 1984, 1983,
    1982, 1981, 1980, 1979, 1978, 1977, 1976, 1975, 1974, 1973, 1972,
    1971, 1970, 1969, 1968, 1965, 1964, 1963, 1962, 1958, 1956, 0,
]

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

# ------------------------------------------------------------------
# AJAX endpoint the site itself uses to populate #cmbjudge /
# #cmbauthjudge once a registry bench is chosen (see connect() in
# rep_judgment.php's JS). Used by scraper/judge_lookup.py.
# ------------------------------------------------------------------

JUDGE_LOOKUP_URL = "https://www.judiciary.karnataka.gov.in/rep_getjud_name.php"
