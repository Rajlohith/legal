"""
Writing the workbook: a Summary sheet, and one "Case Details" sheet
built dynamically from each case's structured section data (see
scraper/section_structure.py) -- no column layout is hardcoded to a
particular section's name or fields. Whatever sections/columns the
scraped cases actually have determine the sheet's shape.

Layout of "Case Details":
  - Sections that hold ONE value per case (Case Information's fields,
    the Judgment PDF link, Prayer Information's narrative, ...) become
    merged column bands. Their values are written once per case and
    merged vertically down that case's whole block of rows.
  - Sections that repeat (Party Information, Judgment/Daily Orders
    tables, ...) become their own column bands too, but each entry
    gets its own row -- appended one after another underneath the
    case's single-value row, leaving unrelated columns blank on that
    row. A case's block is therefore as tall as it needs to be.

Which sections end up in which group, and which columns each needs,
is decided by scanning every case first (see _build_schema).
"""

import re
from collections import OrderedDict

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from config import SECTION_ORDER
from scraper.text_utils import split_party_names

_ILLEGAL_XLSX_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _excel_safe(value):
    if isinstance(value, str):
        return _ILLEGAL_XLSX_CHARS_RE.sub("", value)
    return value


# ------------------------------------------------------------------
# Style helpers
# ------------------------------------------------------------------

NAVY = "1F3A5F"
GOLD = "8C6D2F"
REPEAT_PURPLE = "5B4B8A"
LIGHT_GRAY = "F6F4EE"
STRIPE = "EFEBDD"
BORDER_COLOR = "D6D2C2"

_thin = Side(style="thin", color=BORDER_COLOR)
_cell_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _band_style(cell, bg):
    cell.font = Font(bold=True, color="FFFFFF", size=10, name="Calibri")
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = _cell_border


def _field_header_style(cell):
    cell.font = Font(bold=True, color="FFFFFF", size=9, name="Calibri")
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    cell.border = _cell_border


def _data_style(cell, bg=None, bold=False, wrap=True, valign="top"):
    cell.font = Font(bold=bold, color="1B1B17", size=10, name="Calibri")
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="left", vertical=valign, wrap_text=wrap)
    cell.border = _cell_border


# ------------------------------------------------------------------
# Summary sheet (unchanged)
# ------------------------------------------------------------------

def _write_summary_sheet(ws, summary_rows):
    ws.title = "Summary"
    headers = ["#", "Case Type", "Case No", "Year", "Petitioner", "Respondent"]
    widths = [5, 14, 10, 8, 45, 45]

    for col_idx, (h, w) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        _band_style(cell, NAVY)
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    ws.row_dimensions[1].height = 20

    for row_idx, row in enumerate(summary_rows, start=2):
        values = [
            row["SlNo"], row["Case Type"], row["Case No"],
            row["Year"], row["Petitioner"], row["Respondent"],
        ]
        bg = LIGHT_GRAY if row_idx % 2 == 0 else None
        for col_idx, val in enumerate(values, start=1):
            _data_style(ws.cell(row=row_idx, column=col_idx, value=val), bg=bg, wrap=(col_idx >= 5))
        ws.row_dimensions[row_idx].height = 15

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"


# ------------------------------------------------------------------
# Case Details sheet -- schema discovery
# ------------------------------------------------------------------

def _display_case_ref(base_row):
    return f"{base_row.get('Case Type', '')} {base_row.get('Case No', '')}/{base_row.get('Case Year', '')}".strip()


def _build_schema(cases):
    """
    One pass over every case to decide:
      - single_value: OrderedDict[section_name] -> OrderedDict[field] -> True
      - repeating:    OrderedDict[section_name] -> OrderedDict[column] -> True
                       (each repeating section also gets a leading
                       "Table" sub-column if any of its tables, in any
                       case, had a distinct title)

    A section is "repeating" if it produced at least one table in at
    least one case; otherwise it's single-valued everywhere.
    """
    section_is_table_somewhere = set()
    for case in cases:
        for name, data in (case.get("sections_structured") or {}).items():
            if data.get("kind") == "tables":
                section_is_table_somewhere.add(name)

    single_value = OrderedDict()
    repeating = OrderedDict()
    section_needs_table_title = set()

    # Case Identity always first, always single-valued.
    single_value["Case Identity"] = OrderedDict(
        (f, True) for f in ("Case Type", "Case No", "Case Year")
    )

    # Case Information, if any case has it structured as fields.
    ci_fields = OrderedDict()
    for case in cases:
        ci = case.get("case_info_structured")
        if ci and ci.get("kind") == "fields":
            for label, _ in ci["pairs"]:
                ci_fields.setdefault(label, True)
    if ci_fields:
        single_value["Case Information"] = ci_fields

    # Judgment PDF -- a one-column pseudo-section, single-valued.
    if any(case.get("judgment_pdf") for case in cases):
        single_value["Judgment PDF"] = OrderedDict({"File": True})

    # Every other section, in the site's own order.
    for _section_id, section_name in SECTION_ORDER:
        cols = OrderedDict()
        is_repeating = section_name in section_is_table_somewhere

        for case in cases:
            data = (case.get("sections_structured") or {}).get(section_name)
            if not data:
                continue

            if is_repeating:
                if data["kind"] == "tables":
                    for table in data["tables"]:
                        if table.get("title"):
                            section_needs_table_title.add(section_name)
                        for row in table["rows"]:
                            for key in row.keys():
                                cols.setdefault(key, True)
                elif data["kind"] == "fields":
                    for label, _ in data["pairs"]:
                        cols.setdefault(label, True)
                elif data["kind"] == "narrative":
                    cols.setdefault("Text", True)
            else:
                if data["kind"] == "fields":
                    for label, _ in data["pairs"]:
                        cols.setdefault(label, True)
                elif data["kind"] == "narrative":
                    cols.setdefault(section_name, True)

        if not cols:
            continue

        if is_repeating:
            ordered = OrderedDict()
            if section_name in section_needs_table_title:
                ordered["Table"] = True
            ordered.update(cols)
            repeating[section_name] = ordered
        else:
            single_value[section_name] = cols

    return single_value, repeating


# ------------------------------------------------------------------
# Case Details sheet -- writing
# ------------------------------------------------------------------

def _write_case_details_sheet(ws, cases):
    single_value, repeating = _build_schema(cases)

    col = 1
    field_col = {}       # (group, field) -> column index
    group_span = {}      # group -> (start_col, end_col)

    def write_band(group_name, fields, bg):
        nonlocal col
        start_col = col
        for f in fields:
            field_col[(group_name, f)] = col
            col += 1
        end_col = col - 1
        group_span[group_name] = (start_col, end_col)

        band_cell = ws.cell(row=1, column=start_col, value=group_name)
        _band_style(band_cell, bg)
        if end_col > start_col:
            ws.merge_cells(start_row=1, start_column=start_col, end_row=1, end_column=end_col)
        for c in range(start_col, end_col + 1):
            ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor=bg)

        for f, c in zip(fields, range(start_col, end_col + 1)):
            _field_header_style(ws.cell(row=2, column=c, value=f))
            is_wide = f in ("Text", "Prayer Details") or "Notes" in f or "Address" in f
            ws.column_dimensions[get_column_letter(c)].width = 55 if is_wide else 24

    for group_name, fields in single_value.items():
        write_band(group_name, list(fields.keys()), GOLD)
    for group_name, fields in repeating.items():
        write_band(group_name + "  (repeats)", list(fields.keys()), REPEAT_PURPLE)
        group_span[group_name] = group_span.pop(group_name + "  (repeats)")
        for f in fields:
            field_col[(group_name, f)] = field_col.pop((group_name + "  (repeats)", f))

    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 24
    identity_end = group_span.get("Case Identity", (1, 3))[1]
    ws.freeze_panes = f"{get_column_letter(identity_end + 1)}3"

    # --- write each case's block --------------------------------------
    row = 3
    for case_idx, case in enumerate(cases):
        base_row = case["base_row"]
        stripe = case_idx % 2 == 1
        bg = STRIPE if stripe else None

        repeat_row_counts = []
        for group_name in repeating:
            data = (case.get("sections_structured") or {}).get(group_name)
            if not data:
                continue
            if data["kind"] == "tables":
                repeat_row_counts.append(sum(len(t["rows"]) for t in data["tables"]))
            else:
                repeat_row_counts.append(1)
        n_rows = max(1, sum(repeat_row_counts))
        end_row = row + n_rows - 1

        # -- single-value bands: write once, merge down the block ------
        for group_name, fields in single_value.items():
            for f in fields:
                c = field_col[(group_name, f)]
                val = _value_for_single(case, base_row, group_name, f)
                cell = ws.cell(row=row, column=c, value=_excel_safe(val))
                _data_style(cell, bg=bg, valign="center")
                if group_name == "Judgment PDF" and val:
                    cell.hyperlink = f"pdfs/{val}"
                    cell.font = Font(color="DCE9F5", underline="single", size=10, name="Calibri")
                if end_row > row:
                    ws.merge_cells(start_row=row, start_column=c, end_row=end_row, end_column=c)

        # -- repeating bands: one row per entry, stacked ----------------
        r = row
        for group_name, fields in repeating.items():
            data = (case.get("sections_structured") or {}).get(group_name)
            if not data:
                continue

            entries = []
            if data["kind"] == "tables":
                for table in data["tables"]:
                    for table_row in table["rows"]:
                        entry = dict(table_row)
                        if "Table" in fields and table.get("title"):
                            entry["Table"] = table["title"]
                        entries.append(entry)
            elif data["kind"] == "fields":
                entries.append(dict(data["pairs"]))
            elif data["kind"] == "narrative":
                entries.append({"Text": data["text"]})

            for entry in entries:
                for f in fields:
                    c = field_col[(group_name, f)]
                    val = _excel_safe(entry.get(f, ""))
                    _data_style(ws.cell(row=r, column=c, value=val), bg=bg)
                ws.row_dimensions[r].height = 30
                r += 1

        row = end_row + 1

    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 14)


def _value_for_single(case, base_row, group_name, field):
    if group_name == "Case Identity":
        return base_row.get(field, "")
    if group_name == "Judgment PDF":
        return case.get("judgment_pdf") or ""
    if group_name == "Case Information":
        ci = case.get("case_info_structured")
        if ci and ci.get("kind") == "fields":
            return dict(ci["pairs"]).get(field, "")
        return ""
    data = (case.get("sections_structured") or {}).get(group_name)
    if not data:
        return ""
    if data["kind"] == "fields":
        return dict(data["pairs"]).get(field, "")
    if data["kind"] == "narrative":
        return data["text"]
    return ""


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def write_combined_workbook(filename, cases):
    """Write the Summary sheet and the single dynamically-built Case Details sheet."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    summary_ws = wb.create_sheet("Summary")
    summary_rows = []
    for case in cases:
        base_row = case["base_row"]
        petitioner, respondent = split_party_names(
            base_row.get("Petitioner V/S Respondent Name", "")
        )
        summary_rows.append(
            {
                "SlNo": len(summary_rows) + 1,
                "Case Type": _excel_safe(base_row.get("Case Type", "")),
                "Case No": _excel_safe(base_row.get("Case No", "")),
                "Year": _excel_safe(base_row.get("Case Year", "")),
                "Petitioner": _excel_safe(petitioner),
                "Respondent": _excel_safe(respondent),
            }
        )
    _write_summary_sheet(summary_ws, summary_rows)

    details_ws = wb.create_sheet("Case Details")
    _write_case_details_sheet(details_ws, cases)

    wb.save(filename)
