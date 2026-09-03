import re
import io
import csv
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright
import pytesseract
from PIL import Image


# ============================================================
# CONFIGURATION
# ============================================================

# Path to Tesseract on Windows
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

URL = "https://www.judiciary.karnataka.gov.in/rep_judgment.php"

OUTPUT_FILE = "bbmp_judgments.csv"


# ============================================================
# CAPTCHA FUNCTION
# ============================================================

def solve_captcha(page):
    """
    Gets a screenshot of the CAPTCHA image and returns
    only the digits recognized by OCR.
    """

    captcha_img = page.locator("#captcha")
    captcha_img.wait_for(state="visible")

    image_bytes = captcha_img.screenshot()
    image = Image.open(io.BytesIO(image_bytes))

    custom_config = (
        r"--psm 8 "
        r"-c tessedit_char_whitelist=0123456789"
    )

    captcha_text = pytesseract.image_to_string(
        image,
        config=custom_config
    )

    # Keep digits only
    captcha_text = re.sub(r"\D", "", captcha_text)

    return captcha_text


# ============================================================
# FIND THE ACTUAL JUDGMENTS TABLE
# ============================================================

def find_judgments_table(results):
    """
    Finds the table containing the actual judgment data.

    We do NOT simply use .first because the results popup may
    contain other layout tables.

    The correct table is identified using its expected headers.
    """

    tables = results.locator("table")

    print(f"\nFound {tables.count()} table(s) inside results.")

    for i in range(tables.count()):

        table = tables.nth(i)

        headers = [
            header.strip().replace("\n", " ")
            for header in table.locator("thead th").all_inner_texts()
        ]

        print(f"Table {i} headers: {headers}")

        # Identify the actual judgment table
        if (
            "Sl. No." in headers
            and "Case Type" in headers
            and "Case No" in headers
        ):
            print(f"\nActual judgments table found: Table {i}")
            return table

    return None


# ============================================================
# EXPORT TABLE TO CSV
# ============================================================

def export_table_to_csv(table, filename):
    """
    Exports ONLY:
        - table column headers
        - table body rows

    It does NOT export:
        - popup title
        - date period text
        - Show 10/25/50/All
        - Search box
        - pagination
        - First/Previous/Next/Last
    """

    # --------------------------------------------------------
    # GET COLUMN HEADERS
    # --------------------------------------------------------

    headers = [
        header.strip().replace("\n", " ")
        for header in table.locator("thead th").all_inner_texts()
    ]

    print("\nCSV COLUMN HEADERS:")
    print(headers)

    # --------------------------------------------------------
    # GET TABLE ROWS
    # --------------------------------------------------------

    rows = table.locator("tbody tr")

    print(f"\nFound {rows.count()} table rows.")

    # --------------------------------------------------------
    # WRITE CSV
    # --------------------------------------------------------

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        # Write the table column names as CSV headers
        writer.writerow(headers)

        rows_written = 0

        # Write every actual table row
        for i in range(rows.count()):

            cells = [
                cell.strip().replace("\n", " ")
                for cell in rows.nth(i).locator("td").all_inner_texts()
            ]

            # Skip empty rows
            if not cells:
                continue

            # Skip rows that don't look like actual data rows
            if len(cells) < 2:
                continue

            writer.writerow(cells)
            rows_written += 1

    print("\n" + "=" * 60)
    print(f"SUCCESS: Saved {rows_written} judgments")
    print(f"CSV file: {filename}")
    print("=" * 60)

    return rows_written


# ============================================================
# MAIN PROGRAM
# ============================================================

with sync_playwright() as p:

    # --------------------------------------------------------
    # 1. OPEN BROWSER MAXIMIZED
    # --------------------------------------------------------

    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized"]
    )

    context = browser.new_context(
        no_viewport=True
    )

    page = context.new_page()

    print("Opening Karnataka Judiciary website...")

    page.goto(
        URL,
        wait_until="networkidle"
    )


    # --------------------------------------------------------
    # 2. SELECT PRINCIPAL BENCH AT BENGALURU
    # --------------------------------------------------------

    print("Selecting Principal Bench At Bengaluru...")

    page.locator("#db_bench").select_option("B")

    # Wait for the website's bench-selection request
    page.wait_for_timeout(2000)


    # --------------------------------------------------------
    # 3. ENTER BBMP AS RESPONDENT NAME ONLY
    # --------------------------------------------------------

    respondent = page.locator("#respondname")

    respondent.wait_for(state="visible")

    respondent.fill("BBMP")

    print("Respondent Name entered: BBMP")


    # --------------------------------------------------------
    # 4. SET DATE RANGE
    # --------------------------------------------------------

    to_date = datetime.now()

    # Website allows approximately 3 months
    from_date = to_date - timedelta(days=90)

    from_date_text = from_date.strftime("%Y-%m-%d")
    to_date_text = to_date.strftime("%Y-%m-%d")

    page.locator("#dp1").fill(from_date_text)
    page.locator("#dp2").fill(to_date_text)

    print(
        f"Date Range: {from_date_text} to {to_date_text}"
    )


    # --------------------------------------------------------
    # 5. CAPTCHA ATTEMPTS
    # --------------------------------------------------------

    max_attempts = 5

    success = False
    results = None

    for attempt in range(1, max_attempts + 1):

        print("\n" + "-" * 60)
        print(
            f"CAPTCHA Attempt {attempt} of {max_attempts}"
        )
        print("-" * 60)

        captcha_text = solve_captcha(page)

        print(
            f"OCR detected CAPTCHA: '{captcha_text}'"
        )

        # Continue only if exactly 6 digits were detected
        if len(captcha_text) != 6:

            print(
                "OCR did not detect exactly 6 digits."
            )
            print("Reloading CAPTCHA...")

            page.locator("#reload-button").click()

            page.wait_for_timeout(2000)

            continue


        # ----------------------------------------------------
        # ENTER CAPTCHA
        # ----------------------------------------------------

        page.locator("#vercode").fill(captcha_text)

        print(
            f"Entered CAPTCHA: {captcha_text}"
        )


        # ----------------------------------------------------
        # CLICK SEARCH
        # ----------------------------------------------------

        print("Clicking Search...")

        page.locator("#generate").click()


        # ----------------------------------------------------
        # WAIT FOR RESULTS
        # ----------------------------------------------------

        try:

            results = page.locator(
                "#dynamic-content-year"
            )

            results.wait_for(
                state="visible",
                timeout=10000
            )

            # Give DataTables/results JavaScript time to render
            page.wait_for_timeout(2000)


            # Check whether an actual judgment table exists
            target_table = find_judgments_table(results)

            if target_table is not None:

                success = True

                print(
                    "\nSearch successful!"
                )

                break

            else:

                print(
                    "Results appeared, but the judgments "
                    "table was not found."
                )

                raise Exception(
                    "Judgments table not found"
                )


        except Exception as e:

            print(
                f"Search attempt failed: {e}"
            )

            # Reload CAPTCHA for next attempt
            try:

                page.locator(
                    "#reload-button"
                ).click()

                page.wait_for_timeout(2000)

                # Clear previous CAPTCHA
                page.locator(
                    "#vercode"
                ).fill("")

            except Exception:

                print(
                    "Could not reload CAPTCHA automatically."
                )


    # ========================================================
    # 6. EXPORT ONLY THE ACTUAL TABLE TO CSV
    # ========================================================

    if success:

        print("\nPreparing CSV export...")

        # Find the actual table again
        target_table = find_judgments_table(results)

        if target_table is not None:

            # Try to select "All" entries first
            #
            # This is optional because the exact DataTables
            # dropdown structure may vary.
            #

            try:

                length_selects = results.locator("select")

                for i in range(length_selects.count()):

                    select = length_selects.nth(i)

                    options = select.locator(
                        "option"
                    ).all_inner_texts()

                    if "All" in options:

                        print(
                            "\nSelecting 'All' entries..."
                        )

                        select.select_option(
                            label="All"
                        )

                        page.wait_for_timeout(1500)

                        break

            except Exception as e:

                print(
                    f"Could not select All entries: {e}"
                )

                print(
                    "Exporting currently available rows."
                )


            # Export ONLY the table
            rows_written = export_table_to_csv(
                target_table,
                OUTPUT_FILE
            )

        else:

            print(
                "\nERROR: Could not locate the judgments table."
            )

            # Save HTML only for debugging
            Path(
                "bbmp_debug.html"
            ).write_text(
                page.content(),
                encoding="utf-8"
            )


    else:

        print(
            "\nCould not complete the search after "
            f"{max_attempts} attempts."
        )

        # Save the full page only for debugging
        Path(
            "bbmp_debug.html"
        ).write_text(
            page.content(),
            encoding="utf-8"
        )

        print(
            "Saved bbmp_debug.html for inspection."
        )


    # ========================================================
    # 7. KEEP BROWSER OPEN
    # ========================================================

    print("\n" + "=" * 60)
    print("Browser is held open.")
    print("=" * 60)

    input(
        "Press Enter in this terminal to close the browser..."
    )

    context.close()
    browser.close()