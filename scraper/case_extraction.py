"""Extracting the detail sections from an individual case's page."""

from config import SECTION_ORDER
from scraper.section_structure import extract_section_structure
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


def extract_case_information_structured(case_page, log=print):
    """Same block as above, read as Label: Value pairs instead of a blob."""
    try:
        link = case_page.locator(
            "xpath=//a[normalize-space(text())='Case Information']"
        ).first
        if link.count() == 0:
            return None
        container = link.locator(
            "xpath=ancestor::nav[1]/following-sibling::div[1]"
        )
        if container.count() == 0:
            return None
        return extract_section_structure(container, log=log)
    except Exception as e:
        log(f"  Could not read Case Information structure: {e}")
        return None


def extract_case_sections(case_page, log=print, included_sections=None):
    """
    Returns a dict: { sheet_name: extracted_text }
    Sections with no real data are simply absent from the dict.
    Kept for the narrative fallback used by the Markdown/PDF exports.

    included_sections: optional set of sheet_names to actually open
    and read; every other section is skipped entirely (no divopen(),
    no wait) -- this is also what makes an excluded section faster to
    scrape, not just absent from the output.
    """
    extracted = {}

    for section_id, sheet_name in SECTION_ORDER:
        if included_sections is not None and sheet_name not in included_sections:
            continue

        section = case_page.locator(f"#{section_id}")

        if section.count() == 0:
            continue

        try:
            case_page.evaluate(f"divopen('{section_id}')")
        except Exception:
            pass

        case_page.wait_for_timeout(700)

        raw_text = section.inner_text().strip()
        if raw_text.lower() in ("please wait...",):
            case_page.wait_for_timeout(1500)
            raw_text = section.inner_text().strip()

        cleaned = clean_text(raw_text)

        if cleaned:
            extracted[sheet_name] = cleaned

    return extracted


def extract_case_sections_structured(case_page, case_ref="", log=print, included_sections=None):
    """
    Returns a dict: { sheet_name: structured_section }
    where structured_section is whatever extract_section_structure()
    returned (a "tables" / "fields" / "narrative" dict), for sections
    that revealed something. Assumes each included section's
    divopen() call and the wait for it have already happened (i.e.
    call this right after extract_case_sections() with the SAME
    included_sections, on the same case_page, so the sections are
    already open rather than re-triggering divopen() a second time).
    """
    structured = {}

    for section_id, sheet_name in SECTION_ORDER:
        if included_sections is not None and sheet_name not in included_sections:
            continue
        section = case_page.locator(f"#{section_id}")
        if section.count() == 0:
            continue
        try:
            result = extract_section_structure(section, case_ref=case_ref, log=log)
        except Exception as e:
            log(f"  Could not read structure for '{sheet_name}': {e}")
            result = None
        if result:
            structured[sheet_name] = result

    return structured
