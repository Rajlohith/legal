"""
The orchestration engine: drives the browser through the search form,
CAPTCHA, results table, and each case's detail page, then hands the
collected cases to the Excel writer.

This is the same sequence as the original script, restructured into a
class so a caller (the GUI, a future CLI, tests, etc.) can:
  - receive progress/log updates via callbacks instead of print()
  - request an early stop between rows/aliases
  - get back a summary it can display, instead of only a saved file
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

from config import (
    SEARCH_URL,
    MAX_CAPTCHA_ATTEMPTS,
    DEFAULT_OUTPUT_FILENAME,
)
from scraper.captcha import solve_captcha
from scraper.table_utils import find_judgments_table
from scraper.text_utils import sanitize_filename_part, case_identity
from scraper.date_utils import split_date_range
from scraper.case_extraction import extract_case_information_text, extract_case_sections
from excel.writer import write_combined_workbook


class SearchCancelled(Exception):
    """Raised internally when the user requests a stop mid-run."""


class SearchEngine:
    def __init__(self, log=print, on_progress=None, tesseract_cmd=None, headless=False):
        """
        log(str)                -- called with human-readable status lines
        on_progress(done, total)-- called as case rows are processed
        tesseract_cmd            -- path to tesseract.exe/binary, or None for default
        headless                 -- run the browser without a visible window
        """
        self.log = log
        self.on_progress = on_progress or (lambda done, total: None)
        self.tesseract_cmd = tesseract_cmd
        self.headless = headless
        self._stop_requested = False

    def request_stop(self):
        """Called from the GUI thread to ask the run loop to wind down."""
        self._stop_requested = True

    def _check_stop(self):
        if self._stop_requested:
            raise SearchCancelled()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, aliases, overall_start, overall_end, bench_value, bench_name,
            output_path=None):
        """
        aliases: list[str]
        overall_start/overall_end: datetime
        bench_value: "B" | "D" | "K"
        output_path: full path to the .xlsx to write; defaults to
                     DEFAULT_OUTPUT_FILENAME in the current directory.

        Returns a dict summary: {output_path, case_count, duplicates_skipped, cancelled}
        """
        self._stop_requested = False
        output_path = output_path or DEFAULT_OUTPUT_FILENAME

        date_ranges = split_date_range(overall_start, overall_end)
        search_jobs = [
            (alias, range_start, range_end)
            for alias in aliases
            for range_start, range_end in date_ranges
        ]

        seen_cases = set()
        duplicates_skipped = 0
        collected_cases = []
        cancelled = False

        total_jobs = len(search_jobs)
        jobs_done = 0

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=["--start-maximized"])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()

            try:
                self.log("Opening Karnataka Judiciary website...")
                page.goto(SEARCH_URL, wait_until="networkidle")

                self.log(f"Selecting {bench_name}...")
                page.locator("#db_bench").select_option(bench_value)
                page.wait_for_timeout(2000)

                for alias, from_date, to_date in search_jobs:
                    self._check_stop()

                    safe_alias = sanitize_filename_part(alias)
                    range_label = f"{from_date:%Y%m%d}-{to_date:%Y%m%d}"
                    self.log(
                        f"Searching alias '{alias}' "
                        f"({from_date:%Y-%m-%d} to {to_date:%Y-%m-%d})"
                    )

                    self._run_one_job(
                        page, context, alias, from_date, to_date,
                        seen_cases, collected_cases,
                        safe_alias, range_label,
                        results_holder := {"duplicates": 0},
                    )
                    duplicates_skipped += results_holder["duplicates"]

                    jobs_done += 1
                    self.on_progress(jobs_done, total_jobs)

            except SearchCancelled:
                cancelled = True
                self.log("Stop requested -- finishing up and saving what was collected so far.")
            finally:
                context.close()
                browser.close()

        write_combined_workbook(output_path, collected_cases)
        self.log(
            f"Wrote {output_path} with {len(collected_cases)} unique case sheet(s). "
            f"Duplicates skipped: {duplicates_skipped}."
        )

        return {
            "output_path": output_path,
            "case_count": len(collected_cases),
            "duplicates_skipped": duplicates_skipped,
            "cancelled": cancelled,
        }

    # ------------------------------------------------------------------
    # One (alias, date-window) search job
    # ------------------------------------------------------------------

    def _run_one_job(self, page, context, alias, from_date, to_date,
                      seen_cases, collected_cases, safe_alias, range_label,
                      results_holder):
        respondent = page.locator("#respondname")
        respondent.wait_for(state="visible")
        respondent.fill(alias)

        page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
        page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))

        success, results = self._solve_and_search(page)

        if not success:
            self.log(f"Could not complete the search for '{alias}' after {MAX_CAPTCHA_ATTEMPTS} attempts.")
            debug_filename = f"{safe_alias}_{range_label}_debug.html"
            Path(debug_filename).write_text(page.content(), encoding="utf-8")
            self.log(f"Saved {debug_filename} for inspection.")
            return

        target_table = find_judgments_table(results)

        try:
            page.locator('select[name="example1_length"]').select_option("-1")
            page.wait_for_timeout(2000)
            target_table = find_judgments_table(results)
        except Exception as e:
            self.log(f"Could not select All entries: {e}")

        row_count = target_table.locator("tbody tr").count()
        self.log(f"Found {row_count} case row(s) for '{alias}'.")

        for i in range(row_count):
            self._check_stop()

            target_table = find_judgments_table(results)
            case_row_el = target_table.locator("tbody tr").nth(i)
            cells = [
                c.strip().replace("\n", " ")
                for c in case_row_el.locator("td").all_inner_texts()
            ]

            if len(cells) < 2:
                continue

            headers = [
                h.strip().replace("\n", " ")
                for h in target_table.locator("thead th").all_inner_texts()
            ]
            base_row = dict(zip(headers, cells))
            identity = case_identity(base_row)

            if identity in seen_cases:
                results_holder["duplicates"] += 1
                continue

            seen_cases.add(identity)
            case_info_text = ""
            sections_data = {}
            case_button = case_row_el.locator('button[onclick*="casedetails"]').first

            if case_button.count() > 0:
                try:
                    with context.expect_page(timeout=15000) as new_page_info:
                        case_button.click()

                    case_page = new_page_info.value
                    case_page.wait_for_load_state("domcontentloaded")
                    case_page.wait_for_timeout(1500)
                    case_info_text = extract_case_information_text(case_page, log=self.log)
                    sections_data = extract_case_sections(case_page, log=self.log)
                    case_page.close()
                except Exception as e:
                    self.log(f"Could not open/parse case details for row {i + 1}: {e}")

            collected_cases.append(
                {
                    "base_row": base_row,
                    "case_info_text": case_info_text,
                    "sections_data": sections_data,
                }
            )

            page.wait_for_timeout(800)

        self.log(
            f"Collected results for '{alias}'. "
            f"Duplicates skipped so far: {results_holder['duplicates']}."
        )

    # ------------------------------------------------------------------
    # CAPTCHA loop
    # ------------------------------------------------------------------

    def _solve_and_search(self, page):
        """Attempts the CAPTCHA + search click up to MAX_CAPTCHA_ATTEMPTS times."""
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

                if find_judgments_table(results) is not None:
                    self.log("Search successful.")
                    return True, results
                raise Exception("Judgments table not found")

            except Exception as e:
                self.log(f"Search attempt failed: {e}")
                try:
                    page.locator("#reload-button").click()
                    page.wait_for_timeout(2000)
                    page.locator("#vercode").fill("")
                except Exception:
                    self.log("Could not reload CAPTCHA automatically.")

        return False, results
