import io
import re
import threading
from datetime import datetime, timedelta

import pytesseract
from PIL import Image
from playwright.sync_api import sync_playwright


URL = "https://www.judiciary.karnataka.gov.in/rep_judgment.php"
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
NO_DATA_MARKERS = {"", "record_not_found", "no data found", "please wait..."}


def clean_text(value):
    normalized = " ".join(str(value or "").split())
    return "" if normalized.lower() in NO_DATA_MARKERS else normalized


def parse_date(value):
    return datetime.strptime(value.strip(), "%d-%m-%Y")


def split_date_range(start_date, end_date, max_days=90):
    ranges = []
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=max_days - 1), end_date)
        ranges.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return ranges


def case_identity(row):
    return tuple(clean_text(row.get(field, "")).lower() for field in ("Case Type", "Case No", "Case Year"))


def solve_captcha(page):
    image_bytes = page.locator("#captcha").screenshot()
    image = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(
        image,
        config=r"--psm 8 -c tessedit_char_whitelist=0123456789",
    )
    return re.sub(r"\D", "", text)


def find_judgments_table(results):
    tables = results.locator("table")
    for index in range(tables.count()):
        table = tables.nth(index)
        headers = [clean_text(value.replace("\n", " ")) for value in table.locator("thead th").all_inner_texts()]
        if "Sl. No." in headers and "Case Type" in headers and "Case No" in headers:
            return table
    return None


def extract_case_information(page):
    link = page.locator("xpath=//a[normalize-space(text())='Case Information']").first
    if link.count() == 0:
        return ""
    container = link.locator("xpath=ancestor::nav[1]/following-sibling::div[1]")
    return clean_text(container.inner_text()) if container.count() else ""


def extract_case_sections(page):
    sections = {}
    for section_id, section_name in SECTION_ORDER:
        section = page.locator(f"#{section_id}")
        if section.count() == 0:
            continue
        try:
            page.evaluate(f"divopen('{section_id}')")
        except Exception:
            pass
        page.wait_for_timeout(700)
        text = section.inner_text().strip()
        if text.lower() == "please wait...":
            page.wait_for_timeout(1500)
            text = section.inner_text().strip()
        text = clean_text(text)
        if text:
            sections[section_name] = text
    return sections


class ScraperService:
    def __init__(self, log=None, progress=None, tesseract_cmd=None, headless=True):
        self.log = log or (lambda _message: None)
        self.progress = progress or (lambda _done, _total: None)
        self.stop_event = threading.Event()
        self.tesseract_cmd = tesseract_cmd
        self.headless = headless

    def request_stop(self):
        self.stop_event.set()

    def run(
        self,
        respondent_aliases,
        petitioner_aliases,
        filters,
        start_date,
        end_date,
        bench_value,
    ):
        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        respondent_aliases = [alias.strip() for alias in respondent_aliases if alias.strip()]
        petitioner_aliases = [alias.strip() for alias in petitioner_aliases if alias.strip()]
        search_aliases = (
            [("respondent", alias) for alias in respondent_aliases]
            + [("petitioner", alias) for alias in petitioner_aliases]
        ) or [("all", "")]
        jobs = [
            (search_field, alias, window_start, window_end)
            for search_field, alias in search_aliases
            for window_start, window_end in split_date_range(start_date, end_date)
        ]
        seen = set()
        cases = []
        duplicates = 0

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(URL, wait_until="networkidle")
                page.locator("#db_bench").select_option(bench_value)
                page.wait_for_timeout(2000)

                for job_index, (search_field, alias, from_date, to_date) in enumerate(jobs, 1):
                    if self.stop_event.is_set():
                        break
                    search_label = alias or "all cases"
                    self.log(f"Searching {search_label}: {from_date:%d-%m-%Y} to {to_date:%d-%m-%Y}")
                    self._fill_search_name(page, search_field, alias)
                    self._apply_filters(page, filters)
                    page.locator("#dp1").fill(from_date.strftime("%Y-%m-%d"))
                    page.locator("#dp2").fill(to_date.strftime("%Y-%m-%d"))
                    results = self._submit_search(page)
                    if results is None:
                        self.log(f"No results after CAPTCHA attempts for {alias}")
                        self.progress(job_index, len(jobs))
                        continue

                    table = find_judgments_table(results)
                    try:
                        page.locator('select[name="example1_length"]').select_option("-1")
                        page.wait_for_timeout(1500)
                        table = find_judgments_table(results)
                    except Exception:
                        pass

                    for row_index in range(table.locator("tbody tr").count()):
                        if self.stop_event.is_set():
                            break
                        row_element = find_judgments_table(results).locator("tbody tr").nth(row_index)
                        headers = [clean_text(value.replace("\n", " ")) for value in table.locator("thead th").all_inner_texts()]
                        values = [clean_text(value.replace("\n", " ")) for value in row_element.locator("td").all_inner_texts()]
                        row = dict(zip(headers, values))
                        identity = case_identity(row)
                        if identity in seen:
                            duplicates += 1
                            continue
                        seen.add(identity)
                        cases.append(self._extract_case(page, context, row_element, row))
                    self.progress(job_index, len(jobs))
            finally:
                context.close()
                browser.close()

        return {
            "cases": cases,
            "case_count": len(cases),
            "duplicates_skipped": duplicates,
            "cancelled": self.stop_event.is_set(),
        }

    def _fill_search_name(self, page, search_field, alias):
        selectors = {
            "respondent": "#respondname",
            "petitioner": ("#petitname", "#petname", "#petitionername"),
        }
        for field, selector in selectors.items():
            candidates = selector if isinstance(selector, tuple) else (selector,)
            for candidate in candidates:
                locator = page.locator(candidate)
                if locator.count() > 0:
                    locator.first.fill(alias if field == search_field else "")
                    break
            else:
                if field == search_field:
                    raise RuntimeError(f"Could not find the {field} search field")

    def _apply_filters(self, page, filters):
        selectors = {
            "judge": ("#judge", "#judge_name", '[name="judge"]'),
            "author_judge": ("#authorjudge", "#author_judge", '[name="authorjudge"]'),
            "coram": ("#coram", '[name="coram"]'),
            "case_type": ("#casetype", "#case_type", '[name="casetype"]'),
            "case_number": ("#caseno", "#case_no", '[name="caseno"]'),
            "case_year": ("#caseyear", "#case_year", '[name="caseyear"]'),
            "petitioner_advocate": ("#petitadv", "#petitioner_advocate", '[name="petitadv"]'),
            "respondent_advocate": ("#respondadv", "#respondent_advocate", '[name="respondadv"]'),
        }
        for field, value in filters.items():
            if not value:
                continue
            candidates = selectors[field]
            for candidate in candidates:
                locator = page.locator(candidate)
                if locator.count() == 0:
                    continue
                try:
                    if locator.first.evaluate("element => element.tagName === 'SELECT'"):
                        locator.first.select_option(label=value)
                    else:
                        locator.first.fill(value)
                except Exception as error:
                    raise RuntimeError(f"Could not set {field}: {error}") from error
                break
            else:
                raise RuntimeError(f"Could not find the {field} search field")

    def _submit_search(self, page):
        for attempt in range(1, 6):
            if self.stop_event.is_set():
                return None
            captcha = solve_captcha(page)
            self.log(f"CAPTCHA attempt {attempt}: {captcha}")
            if len(captcha) != 6:
                page.locator("#reload-button").click()
                page.wait_for_timeout(1500)
                continue
            page.locator("#vercode").fill(captcha)
            page.locator("#generate").click()
            try:
                results = page.locator("#dynamic-content-year")
                results.wait_for(state="visible", timeout=10000)
                page.wait_for_timeout(1500)
                if find_judgments_table(results) is not None:
                    return results
            except Exception:
                pass
            page.locator("#reload-button").click()
            page.wait_for_timeout(1500)
        return None

    def _extract_case(self, page, context, row_element, row):
        case = {"summary": row, "case_information": "", "sections": {}}
        button = row_element.locator('button[onclick*="casedetails"]').first
        if button.count() == 0:
            return case
        try:
            with context.expect_page(timeout=15000) as page_info:
                button.click()
            detail_page = page_info.value
            detail_page.wait_for_load_state("domcontentloaded")
            detail_page.wait_for_timeout(1500)
            case["case_information"] = extract_case_information(detail_page)
            case["sections"] = extract_case_sections(detail_page)
            detail_page.close()
        except Exception as error:
            self.log(f"Could not extract case details: {error}")
        return case