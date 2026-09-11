"""
Reading a case detail section's actual HTML structure instead of its
flattened inner_text().

The court site renders every section in one of three real shapes:
  - a <table> (or several, e.g. Party Information has one table for
    petitioners and one for respondents) -- headers come from <th>
    cells or the table's own first row; every <tr> after that is a
    data row.
  - a block of "Label: Value" lines (Case Information's own div.row /
    col-sm layout) -- read as field/value pairs.
  - plain narrative text with neither shape (Prayer Information,
    Linked Cases when it's just a note, etc.)

Nothing here is hardcoded to a specific section's name or column
names -- whatever headers/labels the page actually has are what get
used, so a section we've never seen data for still comes out
structured instead of as one flattened blob.
"""

import re

from scraper.text_utils import clean_text

_FIELD_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 ./()'&-]{1,40}):\s*(.+)$")


def _read_table(table_locator, case_ref=""):
    """One <table> -> {"title": str, "headers": [...], "rows": [dict, ...]}."""
    title = ""
    try:
        preceding = table_locator.locator("xpath=preceding-sibling::*[1]")
        if preceding.count() > 0:
            txt = clean_text(preceding.first.inner_text())
            if txt and len(txt) < 120:
                # Drop a trailing "<case ref>" if the page appended it,
                # e.g. "Petitioner Details: RFA 1143/2014" -> "Petitioner Details"
                if case_ref and case_ref in txt:
                    txt = txt.split(case_ref)[0].strip(" :")
                title = txt
    except Exception:
        pass

    headers = []
    try:
        header_cells = table_locator.locator("thead th")
        if header_cells.count() == 0:
            header_cells = table_locator.locator("tr").first.locator("th")
        if header_cells.count() > 0:
            headers = [clean_text(h) for h in header_cells.all_inner_texts()]
    except Exception:
        pass

    all_rows = table_locator.locator("tr")
    row_count = all_rows.count()
    start_idx = 0
    if headers and row_count > 0:
        # If the header row's cells were <th>, it's usually also the
        # first <tr> -- skip it so it isn't read again as a data row.
        first_row_has_th = all_rows.first.locator("th").count() > 0
        if first_row_has_th:
            start_idx = 1

    rows = []
    for idx in range(start_idx, row_count):
        try:
            row_el = all_rows.nth(idx)
            cells = [clean_text(c) for c in row_el.locator("td").all_inner_texts()]
        except Exception:
            continue
        if not cells or not any(cells):
            continue

        if headers and len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
        elif rows and len(cells) == 1:
            # A single wide cell right under a data row is a
            # continuation/note line (e.g. Daily Orders' remark
            # spanning the full row width) -- fold it into the
            # previous row instead of creating a lopsided new one.
            note = cells[0]
            prev = rows[-1]
            prev["Notes"] = (prev.get("Notes", "") + "\n" + note).strip()
        else:
            # Column count didn't match anything we expected -- keep
            # the data rather than silently drop it, using generic
            # column names so it still lines up across rows.
            row_dict = {}
            for i, val in enumerate(cells):
                label = headers[i] if i < len(headers) else f"Column {i + 1}"
                row_dict[label] = val
            rows.append(row_dict)

    return {"title": title, "headers": headers, "rows": rows}


def _read_field_pairs(text):
    """"Label: Value" narrative lines -> [(label, value), ...], or None."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pairs = []
    unmatched = 0
    for line in lines:
        m = _FIELD_LINE_RE.match(line)
        if m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
        else:
            unmatched += 1

    # Only call it "fields" if most lines actually matched the
    # pattern -- a narrative paragraph that happens to contain one
    # colon shouldn't be forced into this shape.
    if pairs and unmatched <= max(1, len(lines) // 4):
        return pairs
    return None


def extract_section_structure(container, case_ref="", log=print):
    """
    container: a Playwright locator already scoped to the section's
               revealed content (e.g. case_page.locator('#H1')).
    case_ref:  "<Case Type> <Case No>/<Case Year>", used only to trim
               a table's own caption if the page appended it there.

    Returns one of:
      {"kind": "tables", "tables": [{"title","headers","rows"}, ...]}
      {"kind": "fields",  "pairs": [(label, value), ...]}
      {"kind": "narrative", "text": "..."}
      None  -- nothing there (RECORD_NOT_FOUND, empty, "please wait...")
    """
    try:
        raw_text = clean_text(container.inner_text())
        if not raw_text:
            return None

        tables = container.locator("table")
        table_count = tables.count()
        if table_count > 0:
            parsed_tables = []
            for i in range(table_count):
                t = _read_table(tables.nth(i), case_ref=case_ref)
                if t["rows"]:
                    parsed_tables.append(t)
            if parsed_tables:
                return {"kind": "tables", "tables": parsed_tables}
            # Tables existed in the DOM but produced no rows (e.g. a
            # "no records" placeholder table) -- fall through to text.

        field_pairs = _read_field_pairs(raw_text)
        if field_pairs:
            return {"kind": "fields", "pairs": field_pairs}

        return {"kind": "narrative", "text": raw_text}

    except Exception as e:
        log(f"  Could not read section structure: {e}")
        return None
