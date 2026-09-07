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


def sanitize_filename_part(name):
    """Keep user-provided aliases safe for Windows output filenames."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "-", name).strip(" .")
    return cleaned or "Search"


def parse_user_date(value):
    """Parse a user date in DD-MM-YYYY format."""
    return datetime.strptime(value.strip(), "%d-%m-%Y")


def split_date_range(start_date, end_date, max_days=90):
    """Split an inclusive date range into consecutive windows of at most 90 days."""
    ranges = []
    current_start = start_date

    while current_start <= end_date:
        current_end = min(
            current_start + timedelta(days=max_days - 1),
            end_date,
        )
        ranges.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    return ranges


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


# ============================================================
# WRITE ONE CASE'S WORKBOOK
# ============================================================

def split_party_names(value):
    """Split the judgment table's combined petitioner/respondent value."""
    parts = re.split(r"\s+V/S\s+", clean_text(str(value)), maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


def case_sheet_name(base_row, used_names):
    """Create a unique Excel sheet name from case type, number, and year."""
    parts = [
        clean_text(str(base_row.get(field, "")))
        for field in ("Case Type", "Case No", "Case Year")
    ]
    base_name = sanitize_sheet_name("_".join(part for part in parts if part) or "Case")
    sheet_name = base_name
    suffix = 2

    while sheet_name in used_names or sheet_name == "Summary":
        suffix_text = f"_{suffix}"
        sheet_name = f"{base_name[:31 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    used_names.add(sheet_name)
    return sheet_name


def write_combined_workbook(filename, cases):
    """Write one summary sheet and one organized detail sheet per unique case."""
    summary_rows = []
    used_sheet_names = set()

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for case in cases:
            base_row = case["base_row"]
            petitioner, respondent = split_party_names(
                base_row.get("Petitioner V/S Respondent Name", "")
            )
            summary_rows.append(
                {
                    "SlNo": len(summary_rows) + 1,
                    "Case Type": base_row.get("Case Type", ""),
                    "Case No": base_row.get("Case No", ""),
                    "Year": base_row.get("Case Year", ""),
                    "Petitioner": petitioner,
                    "Respondent": respondent,
                }
            )

        summary_df = pd.DataFrame(
            summary_rows,
            columns=["SlNo", "Case Type", "Case No", "Year", "Petitioner", "Respondent"],
        )
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        for case in cases:
            base_row = case["base_row"]
            sheet_name = case_sheet_name(base_row, used_sheet_names)
            detail_rows = [{"Section": "Case Information", DETAILS_COLUMN: case["case_info_text"]}]
            detail_rows.extend(
                {
                    "Section": section_name,
                    DETAILS_COLUMN: case["sections_data"].get(section_name, ""),
                }
                for _section_id, section_name in SECTION_ORDER
            )
            pd.DataFrame(detail_rows, columns=["Section", DETAILS_COLUMN]).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )


# ============================================================
# MAIN PROGRAM
# ============================================================

alias_input = input("Enter entity aliases separated by commas: ")
aliases = [alias.strip() for alias in alias_input.split(",") if alias.strip()]

if not aliases:
    raise SystemExit("No aliases were provided.")

start_input = input("Enter start date (DD-MM-YYYY): ")
end_input = input("Enter end date (DD-MM-YYYY): ")

try:
    overall_start = parse_user_date(start_input)
    overall_end = parse_user_date(end_input)
except ValueError:
    raise SystemExit("Dates must use DD-MM-YYYY format, for example 01-01-2025.")

if overall_start > overall_end:
    raise SystemExit("Start date must be earlier than or equal to the end date.")

bench_options = {
    "1": ("B", "Principal Bench"),
    "2": ("D", "Dharwad Bench"),
    "3": ("K", "Kalaburagi Bench"),
}
print("Select bench:")
print("1. Principal Bench")
print("2. Dharwad Bench")
print("3. Kalaburagi Bench")
bench_choice = input("Enter bench number: ").strip()

if bench_choice not in bench_options:
    raise SystemExit("Bench must be 1, 2, or 3.")

bench_value, bench_name = bench_options[bench_choice]
date_ranges = split_date_range(overall_start, overall_end)
search_jobs = [
    (alias, range_start, range_end)
    for alias in aliases
    for range_start, range_end in date_ranges
]

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False, args=["--start-maximized"])
    context = browser.new_context(no_viewport=True)
    page = context.new_page()

    print("Opening Karnataka Judiciary website...")
    page.goto(URL, wait_until="networkidle")

    print(f"Selecting {bench_name}...")
    page.locator("#db_bench").select_option(bench_value)
    page.wait_for_timeout(2000)

    seen_cases = set()
    duplicates_skipped = 0
    collected_cases = []

    for alias, from_date, to_date in search_jobs:
        safe_alias = sanitize_filename_part(alias)
        range_label = f"{from_date:%Y%m%d}-{to_date:%Y%m%d}"
        print(
            f"\n{'=' * 60}\n"
            f"Searching alias: {alias}\n"
            f"Date window: {from_date:%Y-%m-%d} to {to_date:%Y-%m-%d}\n"
            f"{'=' * 60}"
        )

        respondent = page.locator("#respondname")
        respondent.wait_for(state="visible")
        respondent.fill(alias)
        print(f"Respondent Name entered: {alias}")

        page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
        page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))
        print(f"Date Range: {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")

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
                raise Exception("Judgments table not found")

            except Exception as e:
                print(f"Search attempt failed: {e}")
                try:
                    page.locator("#reload-button").click()
                    page.wait_for_timeout(2000)
                    page.locator("#vercode").fill("")
                except Exception:
                    print("Could not reload CAPTCHA automatically.")

        if success:
            target_table = find_judgments_table(results)

            try:
                print("\nSelecting All entries...")
                page.locator('select[name="example1_length"]').select_option("-1")
                page.wait_for_timeout(2000)
                target_table = find_judgments_table(results)
            except Exception as e:
                print(f"Could not select All entries: {e}")

            row_count = target_table.locator("tbody tr").count()
            print(f"\nTotal case rows found: {row_count}")

            for i in range(row_count):
                print("\n" + "=" * 60)
                print(f"ROW {i + 1} of {row_count}")
                print("=" * 60)

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
                identity = case_identity(base_row)

                if identity in seen_cases:
                    duplicates_skipped += 1
                    print(f"Skipping duplicate case found through alias: {alias}")
                    continue

                seen_cases.add(identity)
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

                collected_cases.append(
                    {
                        "base_row": base_row,
                        "case_info_text": case_info_text,
                        "sections_data": sections_data,
                    }
                )
                print("Collected case for the combined workbook.")

                page.wait_for_timeout(800)

            print("\n" + "=" * 60)
            print(
                f"SUCCESS: Collected results for {alias}. "
                f"Duplicates skipped so far: {duplicates_skipped}."
            )
            print("=" * 60)
        else:
            print(f"\nCould not complete the search for {alias} after {max_attempts} attempts.")
            debug_filename = f"{safe_alias}_{range_label}_debug.html"
            Path(debug_filename).write_text(page.content(), encoding="utf-8")
            print(f"Saved {debug_filename} for inspection.")

    output_filename = "Case_Search_Results.xlsx"
    write_combined_workbook(output_filename, collected_cases)
    print(
        f"\nWrote {output_filename} with {len(collected_cases)} unique case sheet(s). "
        f"Duplicates skipped: {duplicates_skipped}."
    )

    print("\nBrowser is held open.")
    input("Press Enter in this terminal to close the browser...")
    context.close()
    browser.close()