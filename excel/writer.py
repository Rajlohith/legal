"""Writing the combined Summary + one-sheet-per-case workbook."""

import pandas as pd

from config import SECTION_ORDER, DETAILS_COLUMN
from scraper.text_utils import sanitize_sheet_name, split_party_names


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


def write_combined_workbook(filename, cases):
    """Write one summary sheet and one organized detail sheet per unique case."""
    summary_rows = []
    used_sheet_names = set()

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        for case in cases:
            base_row = case["base_row"]
            petitioner, respondent = split_party_names(
                base_row.get("Petitioner V/S Respondent Name", "")
            )
            summary_rows.append(
                {
                    "SlNo": len(summary_rows) + 1,
                    "Case Type": base_row.get("Case Type", ""),
                    "Case No": base_row.get("Case No", ""),
                    "Year": base_row.get("Case Year", ""),
                    "Petitioner": petitioner,
                    "Respondent": respondent,
                }
            )

        summary_df = pd.DataFrame(
            summary_rows,
            columns=["SlNo", "Case Type", "Case No", "Year", "Petitioner", "Respondent"],
        )
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        for case in cases:
            base_row = case["base_row"]
            sheet_name = case_sheet_name(base_row, used_sheet_names)
            detail_rows = [{"Section": "Case Information", DETAILS_COLUMN: case["case_info_text"]}]
            detail_rows.extend(
                {
                    "Section": section_name,
                    DETAILS_COLUMN: case["sections_data"].get(section_name, ""),
                }
                for _section_id, section_name in SECTION_ORDER
            )
            pd.DataFrame(detail_rows, columns=["Section", DETAILS_COLUMN]).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )
