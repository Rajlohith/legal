import re
import io
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright
import pytesseract
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

URL = "https://www.judiciary.karnataka.gov.in/rep_judgment.php"

# Used to build output filenames: BBMP_Case1.xlsx, BBMP_Case2.xlsx, ...
SEARCH_NAME = "BBMP"

# Exact sheet order requested, mapped to their div id.
# "H" (Case Information) is handled separately below since, unlike
# every other section, its content div has no id and is visible by
# default rather than hidden behind divopen().
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


# ============================================================
# CAPTCHA
# ============================================================

def solve_captcha(page):
    captcha_img = page.locator("#captcha")
    captcha_img.wait_for(state="visible")

    image_bytes = captcha_img.screenshot()
    image = Image.open(io.BytesIO(image_bytes))

    custom_config = r"--psm 8 -c tessedit_char_whitelist=0123456789"
    captcha_text = pytesseract.image_to_string(image, config=custom_config)
    return re.sub(r"\D", "", captcha_text)


# ============================================================
# FIND THE JUDGMENTS TABLE
# ============================================================

def find_judgments_table(results):
    tables = results.locator("table")

    for i in range(tables.count()):
        table = tables.nth(i)
        headers = [
            h.strip().replace("\n", " ")
            for h in table.locator("thead th").all_inner_texts()
        ]
        if "Sl. No." in headers and "Case Type" in headers and "Case No" in headers:
            return table

    return None


# ============================================================
# CLEAN A SECTION'S TEXT
# ============================================================

def clean_text(text):
    """Collapse whitespace, normalize 'no data' variants to empty string."""
    if text is None:
        return ""

    normalized = " ".join(text.split())

    if normalized.strip().lower() in NO_DATA_MARKERS:
        return ""

    return normalized


# ============================================================
# EXTRACT "CASE INFORMATION" (div id="H" has no id -- special-cased)
# ============================================================

def extract_case_information_text(case_page):
    """
    The Case Information block is visible by default (no divopen()
    click needed) and its wrapping <div> has no id, unlike every
    other section. We locate it via the "Case Information" link's
    nav ancestor, then take that nav's immediate following sibling.
    """

    try:
        link = case_page.locator(
            "xpath=//a[normalize-space(text())='Case Information']"
        ).first

        if link.count() == 0:
            return ""

        container = link.locator(
            "xpath=ancestor::nav[1]/following-sibling::div[1]"
        )

        if container.count() == 0:
            return ""

        raw_text = container.inner_text().strip()
        return clean_text(raw_text)

    except Exception as e:
        print(f"  Could not extract Case Information: {e}")
        return ""


# ============================================================
# EXTRACT ONE CASE'S SECTIONS (all the divopen()-hidden ones)
# ============================================================

def extract_case_sections(case_page):
    """
    Returns a dict: { sheet_name: extracted_text }
    Sections with no real data are simply absent from the dict.
    """

    extracted = {}

    for section_id, sheet_name in SECTION_ORDER:

        section = case_page.locator(f"#{section_id}")

        if section.count() == 0:
            continue

        # Reveal the section via the page's own JS function
        try:
            case_page.evaluate(f"divopen('{section_id}')")
        except Exception:
            pass

        case_page.wait_for_timeout(700)

        # A couple of sections load via a slower AJAX call --
        # give them one extra beat and re-read.
        raw_text = section.inner_text().strip()
        if raw_text.lower() in ("please wait...",):
            case_page.wait_for_timeout(1500)
            raw_text = section.inner_text().strip()

        cleaned = clean_text(raw_text)

        if cleaned:
            extracted[sheet_name] = cleaned

    return extracted


# ============================================================
# SANITIZE SHEET NAMES
# ============================================================

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


# ============================================================
# WRITE ONE CASE'S WORKBOOK
# ============================================================

def write_case_workbook(filename, base_row, case_info_text, sections_data):
    """
    Writes a single .xlsx with sheets in this exact order:
        Summary, Case Information, Prayer Information, Party Information,
        Caveator/Caveatee Information, Trial/Appellate Information,
        Supreme Court Appellate Information, Daily Orders Information,
        Linked Cases, Judgment Information,
        Certified Copy Information (Final Order),
        Certified Copy Information (Interim Order),
        Index Sheet Information, Scrutiny Information,
        Interlocutory Applications (IA) Information,
        Documents Information, Postal Information,
        Judicial Deposit, Fees Information
    Every sheet is created even when there's no data for it.
    """

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:

        # --- Sheet 1: Summary (original judgment table row) ---
        summary_df = pd.DataFrame([base_row]) if base_row else pd.DataFrame()
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # --- Sheet 2: Case Information ---
        if case_info_text:
            case_info_df = pd.DataFrame([{DETAILS_COLUMN: case_info_text}])
        else:
            case_info_df = pd.DataFrame(columns=[DETAILS_COLUMN])
        case_info_df.to_excel(writer, sheet_name=sanitize_sheet_name("Case Information"), index=False)

        # --- Sheets 3-19: the 17 remaining sections, in exact order ---
        for _section_id, sheet_name in SECTION_ORDER:

            text = sections_data.get(sheet_name)

            if text:
                section_df = pd.DataFrame([{DETAILS_COLUMN: text}])
            else:
                section_df = pd.DataFrame(columns=[DETAILS_COLUMN])

            section_df.to_excel(
                writer,
                sheet_name=sanitize_sheet_name(sheet_name),
                index=False,
            )


# ============================================================
# MAIN PROGRAM
# ============================================================

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False, args=["--start-maximized"])
    context = browser.new_context(no_viewport=True)
    page = context.new_page()

    print("Opening Karnataka Judiciary website...")
    page.goto(URL, wait_until="networkidle")

    print("Selecting Principal Bench At Bengaluru...")
    page.locator("#db_bench").select_option("B")
    page.wait_for_timeout(2000)

    respondent = page.locator("#respondname")
    respondent.wait_for(state="visible")
    respondent.fill("B.B.M.P")
    print("Respondent Name entered: BBMP")

    to_date = datetime.now()
    from_date = to_date - timedelta(days=90)
    page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
    page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))
    print(f"Date Range: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")

    # --------------------------------------------------------
    # CAPTCHA ATTEMPTS
    # --------------------------------------------------------

    max_attempts = 5
    success = False
    results = None

    for attempt in range(1, max_attempts + 1):

        print(f"\nCAPTCHA Attempt {attempt} of {max_attempts}")

        captcha_text = solve_captcha(page)
        print(f"OCR detected CAPTCHA: '{captcha_text}'")

        if len(captcha_text) != 6:
            print("OCR did not detect exactly 6 digits. Reloading CAPTCHA...")
            page.locator("#reload-button").click()
            page.wait_for_timeout(2000)
            continue

        page.locator("#vercode").fill(captcha_text)
        print("Clicking Search...")
        page.locator("#generate").click()

        try:
            results = page.locator("#dynamic-content-year")
            results.wait_for(state="visible", timeout=10000)
            page.wait_for_timeout(2000)

            target_table = find_judgments_table(results)

            if target_table is not None:
                success = True
                print("Search successful!")
                break
            else:
                raise Exception("Judgments table not found")

        except Exception as e:
            print(f"Search attempt failed: {e}")
            try:
                page.locator("#reload-button").click()
                page.wait_for_timeout(2000)
                page.locator("#vercode").fill("")
            except Exception:
                print("Could not reload CAPTCHA automatically.")

    # ========================================================
    # LOOP OVER EVERY CASE ROW -- ONE WORKBOOK PER CASE
    # ========================================================

    files_written = 0

    if success:

        target_table = find_judgments_table(results)

        # Select "All" entries so we don't miss rows past page 1
        try:
            print("\nSelecting All entries...")
            page.locator('select[name="example1_length"]').select_option("-1")
            page.wait_for_timeout(2000)
            target_table = find_judgments_table(results)
        except Exception as e:
            print(f"Could not select All entries: {e}")

        row_count = target_table.locator("tbody tr").count()
        print(f"\nTotal case rows found: {row_count}")

        case_num = 0

        for i in range(row_count):

            print("\n" + "=" * 60)
            print(f"ROW {i + 1} of {row_count}")
            print("=" * 60)

            # Re-fetch the table + row fresh each loop, since the
            # page can re-render after a popup closes
            target_table = find_judgments_table(results)
            case_row_el = target_table.locator("tbody tr").nth(i)

            cells = [
                c.strip().replace("\n", " ")
                for c in case_row_el.locator("td").all_inner_texts()
            ]

            if len(cells) < 2:
                print("Skipping malformed row.")
                continue

            headers = [
                h.strip().replace("\n", " ")
                for h in target_table.locator("thead th").all_inner_texts()
            ]
            base_row = dict(zip(headers, cells))

            case_num += 1
            output_filename = f"{SEARCH_NAME}_Case{case_num}.xlsx"

            case_info_text = ""
            sections_data = {}

            case_button = case_row_el.locator('button[onclick*="casedetails"]').first

            if case_button.count() == 0:
                print("No case details button in this row -- Summary sheet only.")

            else:
                try:
                    with context.expect_page(timeout=15000) as new_page_info:
                        case_button.click()

                    case_page = new_page_info.value
                    case_page.wait_for_load_state("domcontentloaded")
                    case_page.wait_for_timeout(1500)

                    print(f"Case details opened: {case_page.url}")

                    case_info_text = extract_case_information_text(case_page)
                    sections_data = extract_case_sections(case_page)

                    case_page.close()

                except Exception as e:
                    print(f"Could not open/parse case details: {e}")

            write_success = False
            for save_attempt in range(3):
                try:
                    write_case_workbook(output_filename, base_row, case_info_text, sections_data)
                    write_success = True
                    break
                except PermissionError as e:
                    print(f"  File locked ({output_filename}), retrying in 2s... ({e})")
                    page.wait_for_timeout(2000)

            if write_success:
                files_written += 1
            else:
                print(f"  FAILED to save {output_filename} after 3 attempts -- skipping.")

            print(f"Saved: {output_filename}")

            # Be polite to the server between cases
            page.wait_for_timeout(800)

        print("\n" + "=" * 60)
        print(f"SUCCESS: Wrote {files_written} case workbook(s).")
        print("=" * 60)

    else:
        print(f"\nCould not complete the search after {max_attempts} attempts.")
        Path("bbmp_debug.html").write_text(page.content(), encoding="utf-8")
        print("Saved bbmp_debug.html for inspection.")

    print("\nBrowser is held open.")
    input("Press Enter in this terminal to close the browser...")

    context.close()
    browser.close()