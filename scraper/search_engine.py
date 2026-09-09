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
    REPORT_TYPE_RADIO_IDS,
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
    def __init__(self, log=print, on_progress=None, on_row_progress=None,tesseract_cmd=None, headless=False):
        """
    log(str)                -- called with human-readable status lines
    on_progress(done, total)-- called once per finished search job
                                (one job = one alias x one date window)
    on_row_progress(done, total, label)
                             -- called as each individual case row within
                                the *current* job is processed, so a long
                                single job (hundreds of rows) still gives
                                live feedback instead of going quiet
                                until the whole job finishes
    tesseract_cmd            -- path to tesseract.exe/binary, or None for default
    headless                 -- run the browser without a visible window
    """
        self.log = log
        self.on_progress = on_progress or (lambda done, total: None)
        self.on_row_progress = on_row_progress or (lambda done, total, label: None)
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
            output_path=None, *, alias_field="respondname",
            case_type=None, case_no=None, case_year=None,
            petitioner_name=None, respondent_name=None,
            petitioner_adv=None, respondent_adv=None,
            judge=None, author_judge=None, coram=None, report_type=None):
        """
        aliases: list[str] -- entity names to loop the search over, one
                 job per alias per date window. Each alias is placed
                 into `alias_field` ("respondname" or "petname"); every
                 other field below stays constant across the loop.
                 May be empty/None, in which case a single job runs
                 using petitioner_name/respondent_name as given.
        overall_start/overall_end: datetime, or both None to search by
                 Case Type + Case Number + Case Year only (matches the
                 site's own rule: dates are only required when a case
                 number search isn't fully specified).
        bench_value: "B" | "D" | "K"  (the registry/#db_bench bench)
        output_path: full path to the .xlsx to write; defaults to
                     DEFAULT_OUTPUT_FILENAME in the current directory.

        case_type/case_no/case_year, petitioner_name/respondent_name,
        petitioner_adv/respondent_adv, judge/author_judge, coram,
        report_type -- all optional, all map 1:1 onto the site's own
        search fields (see config.py's field-mapping notes). Every one
        of these is left untouched on the page when not supplied, same
        as a person leaving that field blank.

        Returns a dict summary: {output_path, case_count,
        duplicates_skipped, cancelled, cases}. `cases` is the raw
        collected-case list (base_row + case_info_text + sections_data
        per case), useful for a caller that wants to display results
        beyond the Excel file.
        """
        self._stop_requested = False
        output_path = output_path or DEFAULT_OUTPUT_FILENAME

        static_fields = {
            "case_type": case_type,
            "case_no": case_no,
            "case_year": case_year,
            "petitioner_name": petitioner_name,
            "respondent_name": respondent_name,
            "petitioner_adv": petitioner_adv,
            "respondent_adv": respondent_adv,
            "judge": judge,
            "author_judge": author_judge,
            "coram": coram,
            "report_type": report_type,
        }

        if overall_start and overall_end:
            date_ranges = split_date_range(overall_start, overall_end)
        else:
            date_ranges = [(None, None)]

        alias_list = list(aliases) if aliases else [None]

        search_jobs = [
            (alias, range_start, range_end)
            for alias in alias_list
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

                    safe_alias = sanitize_filename_part(
                        alias or static_fields.get("respondent_name")
                        or static_fields.get("petitioner_name")
                        or static_fields.get("case_no") or "Search"
                    )
                    range_label = (
                        f"{from_date:%Y%m%d}-{to_date:%Y%m%d}" if from_date else "nodate"
                    )

                    if alias:
                        self.log(f"Searching '{alias}'" + (
                            f" ({from_date:%Y-%m-%d} to {to_date:%Y-%m-%d})" if from_date else ""
                        ))
                    else:
                        self.log("Running search" + (
                            f" ({from_date:%Y-%m-%d} to {to_date:%Y-%m-%d})" if from_date else ""
                        ))

                    self._run_one_job(
                        page, context, alias, alias_field, static_fields,
                        from_date, to_date,
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
            "cases": collected_cases,
        }

    # ------------------------------------------------------------------
    # One (alias, date-window) search job
    # ------------------------------------------------------------------

    def _run_one_job(self, page, context, alias, alias_field, static_fields,
                      from_date, to_date,
                      seen_cases, collected_cases, safe_alias, range_label,
                      results_holder):
        respondent = page.locator("#respondname")
        respondent.wait_for(state="visible")

        self._fill_search_form(page, alias, alias_field, static_fields, from_date, to_date)

        success, results = self._solve_and_search(page)

        job_label = alias or safe_alias

        if not success:
            self.log(f"Could not complete the search for '{job_label}' after {MAX_CAPTCHA_ATTEMPTS} attempts.")
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
        self.log(f"Found {row_count} case row(s) for '{job_label}'.")

        for i in range(row_count):
            self._check_stop()
            self.on_row_progress(i + 1, row_count, job_label)

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
            f"Collected results for '{job_label}'. "
            f"Duplicates skipped so far: {results_holder['duplicates']}."
        )

    # ------------------------------------------------------------------
    # Filling every optional field the site's own form exposes
    # ------------------------------------------------------------------

    def _fill_search_form(self, page, alias, alias_field, static_fields, from_date, to_date):
        """
        Fills in every field the site's #form1 exposes, leaving each
        one blank/untouched (i.e. exactly as a person left it) when no
        value was supplied. `alias`, when given, overrides whichever
        of petitioner/respondent name `alias_field` points at for this
        one job, so a multi-entity search can loop the alias while
        keeping every other field constant.
        """
        if static_fields.get("judge"):
            page.locator("#cmbjudge").select_option(static_fields["judge"])
        if static_fields.get("author_judge"):
            page.locator("#cmbauthjudge").select_option(static_fields["author_judge"])
        if static_fields.get("coram"):
            page.locator("#cmbbench").select_option(static_fields["coram"])
        if static_fields.get("case_type"):
            page.locator("#cmbcasetype").select_option(static_fields["case_type"])
        if static_fields.get("case_no"):
            page.locator("#caseno").fill(str(static_fields["case_no"]))
        if static_fields.get("case_year"):
            page.locator("#caseyear").select_option(str(static_fields["case_year"]))

        petitioner_name = static_fields.get("petitioner_name") or ""
        respondent_name = static_fields.get("respondent_name") or ""
        if alias:
            if alias_field == "petname":
                petitioner_name = alias
            else:
                respondent_name = alias

        if petitioner_name:
            page.locator("#petname").fill(petitioner_name)
        if respondent_name:
            page.locator("#respondname").fill(respondent_name)
        if static_fields.get("petitioner_adv"):
            page.locator("#petadv").fill(static_fields["petitioner_adv"])
        if static_fields.get("respondent_adv"):
            page.locator("#respondadv").fill(static_fields["respondent_adv"])

        if from_date and to_date:
            page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
            page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))

        report_value = static_fields.get("report_type") or "none"
        radio_id = REPORT_TYPE_RADIO_IDS.get(report_value, "r3")
        page.locator(f"#{radio_id}").check()

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
