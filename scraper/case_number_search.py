"""
Orchestration engine for the site's *other* judgment lookup: the
"Quick Search by Case No." page (rep_judgmentcasebc.php), as opposed
to the Detailed Search page (rep_judgment.php) that search_engine.py
already drives.

Same underlying site and CAPTCHA mechanics, but a different results
shape: instead of a multi-row results <table>, a successful search
renders a *single* case's summary block directly into
#dynamic-content-year (Status / Case Number / Petitioner Name / ...),
with a "Case Number:" button that opens the same casedetails() detail
popup Detailed Search's per-row button opens. So this module reads
that summary block's own label/value rows rather than reusing
table_utils.find_judgments_table (which only matches a <table> with
"Sl. No./Case Type/Case No" headers -- there isn't one here).
"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import (
    CASE_NUMBER_SEARCH_URL,
    MAX_CAPTCHA_ATTEMPTS,
    DEFAULT_OUTPUT_FILENAME,
)
from scraper.captcha import solve_captcha
from scraper.text_utils import sanitize_filename_part, clean_text
from scraper.case_extraction import extract_case_information_text, extract_case_sections
from scraper.pdf_capture import fetch_judgment_pdf
from excel.writer import write_combined_workbook

# "WP 123/2022" -> ("WP", "123", "2022")
_CASE_NO_RE = re.compile(r"^(.*?)\s+(\d+)\s*/\s*(\d+)$")


class SearchCancelled(Exception):
    """Raised internally when the user requests a stop mid-run."""


class CaseNumberSearchEngine:
    def __init__(self, log=print, on_progress=None, tesseract_cmd=None, headless=False):
        self.log = log
        self.on_progress = on_progress or (lambda done, total: None)
        self.tesseract_cmd = tesseract_cmd
        self.headless = headless
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def _check_stop(self):
        if self._stop_requested:
            raise SearchCancelled()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, bench_value, bench_name, case_type, case_no, case_year, output_path=None, pdf_dir=None):
        """
        bench_value: "B" | "D" | "K"
        case_type/case_no/case_year: all required -- this page has no
                 other fields to fall back on.

        Returns the same summary shape SearchEngine.run() does:
        {output_path, case_count, duplicates_skipped, cancelled, cases}
        so the web UI's existing results renderer works unchanged.
        """
        self._stop_requested = False
        output_path = output_path or DEFAULT_OUTPUT_FILENAME

        collected_cases = []
        cancelled = False

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--start-maximized"])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()

            try:
                self.log("Opening Karnataka Judiciary website (Quick Search by Case No.)...")
                page.goto(CASE_NUMBER_SEARCH_URL, wait_until="networkidle")

                self.log(f"Selecting {bench_name}...")
                page.locator("#db_bench").select_option(bench_value)
                page.wait_for_timeout(1000)

                self.log(f"Searching Case {case_type} No. {case_no}/{case_year}...")
                page.locator("#cmbcasetype").select_option(str(case_type))
                page.locator("#caseno").fill(str(case_no))
                page.locator("#caseyear").select_option(str(case_year))

                self._check_stop()
                success, results = self._solve_and_search(page)

                if not success:
                    self.log(f"Could not complete the search after {MAX_CAPTCHA_ATTEMPTS} attempts.")
                    safe_label = sanitize_filename_part(f"{case_type}_{case_no}_{case_year}")
                    debug_filename = f"{safe_label}_debug.html"
                    Path(debug_filename).write_text(page.content(), encoding="utf-8")
                    self.log(f"Saved {debug_filename} for inspection.")
                else:
                    collected_cases = self._collect_results(page, context, results, pdf_dir)
                    if collected_cases:
                        self.log("Found the case -- pulling full details...")
                    else:
                        self.log("No matching case found for that Case Type/Number/Year.")

                self.on_progress(1, 1)

            except SearchCancelled:
                cancelled = True
                self.log("Stop requested.")
            finally:
                context.close()
                browser.close()

        write_combined_workbook(output_path, collected_cases)
        self.log(f"Wrote {output_path} with {len(collected_cases)} case sheet(s).")

        return {
            "output_path": output_path,
            "case_count": len(collected_cases),
            "duplicates_skipped": 0,
            "cancelled": cancelled,
            "cases": collected_cases,
        }

    # ------------------------------------------------------------------
    # Reading the single-case summary block + its detail popup
    # ------------------------------------------------------------------

    def _collect_results(self, page, context, results, pdf_dir=None):
        """
        A successful search renders one case's summary directly into
        #dynamic-content-year: a heading, then a series of
        `<div class="row">` blocks each holding a label (e.g. "Status:")
        in a .col-md-3 and its value in a .col-md-8, and a "Case Number:"
        row whose value is a <button onclick="casedetails(this.id)">
        instead of plain text. No case-number button at all means the
        site found nothing for that Case Type/Number/Year.
        """
        case_button = results.locator('button[onclick*="casedetails"]').first

        if case_button.count() == 0:
            return []

        case_no_text = clean_text(case_button.inner_text())  # e.g. "WP 123/2022"
        match = _CASE_NO_RE.match(case_no_text)
        if match:
            case_type_abbrev, parsed_no, parsed_year = match.groups()
        else:
            case_type_abbrev, parsed_no, parsed_year = case_no_text, "", ""

        fields = self._extract_summary_fields(results)
        petitioner = fields.get("Petitioner Name", "")
        respondent = fields.get("Respondent Name", "")

        base_row = {
            "Case Type": case_type_abbrev,
            "Case No": parsed_no,
            "Case Year": parsed_year,
            "Petitioner V/S Respondent Name": f"{petitioner} V/S {respondent}",
        }
        base_row.update(fields)

        # Fallback text if the detail popup can't be opened/parsed --
        # at least the summary block's own fields are preserved.
        case_info_text = "\n".join(f"{label}: {value}" for label, value in fields.items() if value)
        sections_data = {}
        judgment_pdf = None
        case_ref = sanitize_filename_part(
            f"{case_type_abbrev}_{parsed_no}_{parsed_year}".strip("_") or "case"
        )

        try:
            with context.expect_page(timeout=15000) as new_page_info:
                case_button.click()

            case_page = new_page_info.value
            case_page.wait_for_load_state("domcontentloaded")
            case_page.wait_for_timeout(1500)
            detail_text = extract_case_information_text(case_page, log=self.log)
            if detail_text:
                case_info_text = detail_text
            sections_data = extract_case_sections(case_page, log=self.log)
            if pdf_dir is not None:
                judgment_pdf = fetch_judgment_pdf(
                    context, case_page, pdf_dir, case_ref, log=self.log
                )
            case_page.close()
        except Exception as e:
            self.log(f"Could not open/parse the full case details popup: {e}")

        return [
            {
                "base_row": base_row,
                "case_info_text": case_info_text,
                "sections_data": sections_data,
                "judgment_pdf": judgment_pdf,
            }
        ]

    def _extract_summary_fields(self, results):
        """Reads every label/value row pair from the summary block
        (Status, Case Number, Main Case Number, Petitioner Name,
        Respondent Name, Petitioner/Respondent Advocate, Judge(s) Name,
        Date of Decision, Disposal Nature, Appeal, Trial Court,
        Reported In, Provision of Law, Date Upload)."""
        fields = {}
        rows = results.locator("div.row")

        for i in range(rows.count()):
            row = rows.nth(i)
            label_el = row.locator(".col-md-3").first
            value_el = row.locator(".col-md-8").first

            if label_el.count() == 0 or value_el.count() == 0:
                continue

            label = clean_text(label_el.inner_text()).rstrip(":").strip("*").strip()
            if not label:
                continue

            value = clean_text(value_el.inner_text())
            fields[label] = value

        return fields

    # ------------------------------------------------------------------
    # CAPTCHA loop -- identical mechanics to the Detailed Search page
    # ------------------------------------------------------------------

    def _solve_and_search(self, page):
        results = None

        for attempt in range(1, MAX_CAPTCHA_ATTEMPTS + 1):
            self._check_stop()
            self.log(f"CAPTCHA attempt {attempt} of {MAX_CAPTCHA_ATTEMPTS}")

            captcha_text = solve_captcha(page, tesseract_cmd=self.tesseract_cmd)

            if len(captcha_text) != 6:
                self.log("OCR did not detect exactly 6 digits. Reloading CAPTCHA...")
                page.locator("#reload-button").click()
                page.wait_for_timeout(2000)
                continue

            page.locator("#vercode").fill(captcha_text)
            page.locator("#generate").click()

            try:
                results = page.locator("#dynamic-content-year")
                results.wait_for(state="visible", timeout=10000)
                page.wait_for_timeout(2000)
                self.log("Search successful.")
                return True, results

            except Exception as e:
                self.log(f"Search attempt failed: {e}")
                try:
                    page.locator("#reload-button").click()
                    page.wait_for_timeout(2000)
                    page.locator("#vercode").fill("")
                except Exception:
                    self.log("Could not reload CAPTCHA automatically.")

        return False, results
