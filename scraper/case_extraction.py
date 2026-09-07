"""Extracting the detail sections from an individual case's page."""

from config import SECTION_ORDER
from scraper.text_utils import clean_text


def extract_case_information_text(case_page, log=print):
    """
    The "Case Information" block is visible by default (no divopen()
    click needed) and its wrapping <div> has no id, unlike every other
    section. We locate it via the "Case Information" link's nav
    ancestor, then take that nav's immediate following sibling.
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
        log(f"  Could not extract Case Information: {e}")
        return ""


def extract_case_sections(case_page, log=print):
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
