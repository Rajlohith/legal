"""Finding the right results table on the search-results page."""


def find_judgments_table(results):
    """
    The results container can hold more than one <table>. Identify the
    real judgments table by its header row rather than assuming index 0.
    """
    tables = results.locator("table")

    for i in range(tables.count()):
        table = tables.nth(i)
        headers = [
            h.strip().replace("\n", " ")
            for h in table.locator("thead th").all_inner_texts()
        ]
        if "Sl. No." in headers and "Case Type" in headers and "Case No" in headers:
            return table

    return None
