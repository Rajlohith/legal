"""Writing the combined Summary + one-sheet-per-case workbook with improved formatting."""

import re

import openpyxl
from openpyxl.styles import (
    Alignment, Font, PatternFill, Border, Side
)
from openpyxl.utils import get_column_letter

from config import DETAILS_COLUMN
from scraper.text_utils import sanitize_sheet_name, split_party_names

# Defense-in-depth: strip Excel-illegal control characters immediately
_ILLEGAL_XLSX_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _excel_safe(value):
    """Remove Excel/XML-illegal control characters from string values."""
    if isinstance(value, str):
        return _ILLEGAL_XLSX_CHARS_RE.sub("", value)
    return value


def case_sheet_name(base_row, used_names):
    """Create a unique Excel sheet name from case type, number, and year."""
    from scraper.text_utils import clean_text

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


# ------------------------------------------------------------------
# Style helpers
# ------------------------------------------------------------------

NAVY = "1F3A5F"
GOLD = "8C6D2F"
LIGHT_BLUE = "DCE9F5"
LIGHT_GRAY = "F6F4EE"
BORDER_COLOR = "D6D2C2"

_thin = Side(style="thin", color=BORDER_COLOR)
_thick = Side(style="medium", color=NAVY)
_cell_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_header_border = Border(left=_thick, right=_thick, top=_thick, bottom=_thick)


def _header_style(cell, bold=True, bg=NAVY, fg="FFFFFF", size=10, wrap=False):
    cell.font = Font(bold=bold, color=fg, size=size, name="Calibri")
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=wrap)
    cell.border = _cell_border


def _data_style(cell, bold=False, bg=None, size=10, wrap=True, valign="top"):
    cell.font = Font(bold=bold, color="1B1B17", size=size, name="Calibri")
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    cell.alignment = Alignment(horizontal="left", vertical=valign, wrap_text=wrap)
    cell.border = _cell_border


def _set_col_width(ws, col_letter, width):
    ws.column_dimensions[col_letter].width = width


def _freeze(ws, cell_ref):
    ws.freeze_panes = cell_ref


# ------------------------------------------------------------------
# Summary sheet
# ------------------------------------------------------------------

def _write_summary_sheet(ws, summary_rows):
    ws.title = "Summary"

    headers = ["#", "Case Type", "Case No", "Year", "Petitioner", "Respondent"]
    widths = [5, 14, 10, 8, 45, 45]

    # Header row
    for col_idx, (h, w) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        _header_style(cell)
        _set_col_width(ws, get_column_letter(col_idx), w)

    ws.row_dimensions[1].height = 20

    # Data rows
    for row_idx, row in enumerate(summary_rows, start=2):
        values = [
            row["SlNo"], row["Case Type"], row["Case No"],
            row["Year"], row["Petitioner"], row["Respondent"],
        ]
        bg = LIGHT_GRAY if row_idx % 2 == 0 else None
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            _data_style(cell, bg=bg, wrap=(col_idx >= 5))
        ws.row_dimensions[row_idx].height = 15

    _freeze(ws, "A2")

    # Auto-filter
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"


# ------------------------------------------------------------------
# Detail sheet per case
# ------------------------------------------------------------------

def _write_case_sheet(ws, case):
    base_row = case["base_row"]
    petitioner, respondent = split_party_names(
        base_row.get("Petitioner V/S Respondent Name", "")
    )

    # Title row
    case_ref = f"{_excel_safe(base_row.get('Case Type', ''))} {_excel_safe(base_row.get('Case No', ''))}/{_excel_safe(base_row.get('Case Year', ''))}"
    title_cell = ws.cell(row=1, column=1, value=case_ref)
    _header_style(title_cell, size=12)
    ws.merge_cells("A1:B1")
    ws.row_dimensions[1].height = 22

    # Party row
    ws.cell(row=2, column=1, value="Petitioner").font = Font(bold=True, color=NAVY, name="Calibri", size=9)
    ws.cell(row=2, column=1).fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    ws.cell(row=2, column=1).alignment = Alignment(horizontal="left", vertical="top")
    ws.cell(row=2, column=2, value=petitioner)
    ws.cell(row=2, column=2).font = Font(name="Calibri", size=10)
    ws.cell(row=2, column=2).alignment = Alignment(wrap_text=True, vertical="top")

    ws.cell(row=3, column=1, value="Respondent").font = Font(bold=True, color=NAVY, name="Calibri", size=9)
    ws.cell(row=3, column=1).fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    ws.cell(row=3, column=1).alignment = Alignment(horizontal="left", vertical="top")
    ws.cell(row=3, column=2, value=respondent)
    ws.cell(row=3, column=2).font = Font(name="Calibri", size=10)
    ws.cell(row=3, column=2).alignment = Alignment(wrap_text=True, vertical="top")

    ws.row_dimensions[2].height = 15
    ws.row_dimensions[3].height = 15

    # Separator
    sep_cell = ws.cell(row=4, column=1, value="")
    sep_cell.fill = PatternFill("solid", fgColor=NAVY)
    ws.merge_cells("A4:B4")
    ws.row_dimensions[4].height = 3

    # Section header row
    hdr_a = ws.cell(row=5, column=1, value="Section")
    _header_style(hdr_a)
    hdr_b = ws.cell(row=5, column=2, value="Details")
    _header_style(hdr_b)
    ws.row_dimensions[5].height = 18

    # Data rows — only sections that actually have content are written;
    # no empty rows are created for sections absent from this case's result.
    current_row = 6
    detail_rows = []

    case_info_text = case.get("case_info_text", "")
    if case_info_text and case_info_text.strip():
        detail_rows.append(
            {
                "Section": "Case Information",
                DETAILS_COLUMN: _excel_safe(case_info_text),
            }
        )

    for section_name, section_text in case.get("sections_data", {}).items():
        if section_text and section_text.strip():
            detail_rows.append(
                {
                    "Section": _excel_safe(section_name),
                    DETAILS_COLUMN: _excel_safe(section_text),
                }
            )

    for r_idx, row in enumerate(detail_rows):
        section_val = row["Section"]
        details_val = row[DETAILS_COLUMN]
        bg = LIGHT_GRAY if r_idx % 2 == 0 else None

        sec_cell = ws.cell(row=current_row, column=1, value=section_val)
        _data_style(sec_cell, bold=True, bg=bg, wrap=False)
        sec_cell.font = Font(bold=True, color=NAVY, size=10, name="Calibri")

        det_cell = ws.cell(row=current_row, column=2, value=details_val)
        _data_style(det_cell, bg=bg, wrap=True)

        # Estimate row height: ~15pt per ~100 chars, max 400
        char_len = len(details_val or "")
        est_lines = max(1, char_len // 100)
        ws.row_dimensions[current_row].height = min(15 * est_lines + 5, 400)

        current_row += 1

    # Column widths
    _set_col_width(ws, "A", 32)
    _set_col_width(ws, "B", 90)
    _freeze(ws, "A6")


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def write_combined_workbook(filename, cases):
    """Write one summary sheet and one organized detail sheet per unique case."""
    wb = openpyxl.Workbook()
    # Remove the default blank sheet
    default_sheet = wb.active
    wb.remove(default_sheet)

    summary_ws = wb.create_sheet("Summary")
    summary_rows = []
    used_sheet_names = {"Summary"}

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

    for case in cases:
        base_row = case["base_row"]
        sheet_name = case_sheet_name(base_row, used_sheet_names)
        ws = wb.create_sheet(sheet_name)
        _write_case_sheet(ws, case)

    wb.save(filename)
