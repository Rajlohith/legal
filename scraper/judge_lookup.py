"""
Fetching the "Judge" / "Author Judge" dropdown options for a given
registry bench (Principal / Dharwad / Kalaburagi).

On the real site these two <select> elements (#cmbjudge and
#cmbauthjudge) start out empty and are populated client-side by the
page's own connect() function, which POSTs the chosen bench to
rep_getjud_name.php and appends the returned <option> HTML into both
selects. There's no separate documented API -- this *is* the site's
API for that dropdown.

Rather than reverse-engineer that endpoint's session/cookie handling
with a bare HTTP client, we do exactly what a browser does: open the
real search page with Playwright, pick the bench, let the site's own
JS make the call, then read back whatever options it populated. This
keeps the same Playwright-driven approach as the rest of the scraper
instead of adding a second, more fragile way of talking to the site.
"""

from playwright.sync_api import sync_playwright

from config import SEARCH_URL


def fetch_judge_options(db_bench_value, headless=True, timeout_ms=20000):
    """
    db_bench_value: "B" | "D" | "K"

    Returns a list of {"value": ..., "label": ...} dicts, suitable for
    both the "Judge" and "Author Judge" dropdowns (the site populates
    them from the same list). Returns [] if the bench has no judges
    on file or the page didn't respond in time.
    """
    options = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)  # 60 seconds, stop waiting for network to idle
            page.locator("#db_bench").select_option(db_bench_value)

            judge_select = page.locator("#cmbjudge")
            # connect() re-populates #cmbjudge asynchronously; wait
            # until it actually has more than the empty state.
            try:
                page.wait_for_function(
                    "document.querySelector('#cmbjudge') && "
                    "document.querySelector('#cmbjudge').options.length > 0",
                    timeout=timeout_ms,
                )
            except Exception:
                pass

            count = judge_select.locator("option").count()
            for i in range(count):
                opt = judge_select.locator("option").nth(i)
                value = opt.get_attribute("value") or ""
                label = (opt.inner_text() or "").strip()
                if label:
                    options.append({"value": value, "label": label})
        finally:
            browser.close()

    return options
