"""
Capturing the "Judgment" PDF from a case's detail page.

The case detail page's Judgment Information section (id "H5") has a
"View Judgment" button: <button onclick="viewjud('<token>')">. The
site's own JS (viewjud in casedetails.js) POSTs that token to
napix/highcourtorderdetails.php, which replies with JSON:
    {"status": 2, "data": "<base64 PDF bytes>", "filename": "X.pdf"}
    {"status": <other>, ...}   -- nothing available for this case

We do the same POST server-side via Playwright's APIRequestContext
(context.request), which shares the browser context's session
cookies, so no extra login/CAPTCHA is needed for this call.

Earlier attempt note: the results-table's green "Judgment" button
(onclick="judgement(this.id)") posts to a *different* endpoint,
rep_judgment_download_single.php, whose response did not actually
contain usable PDF bytes for this token format -- this module only
uses the verified-working napix endpoint above.
"""

import base64
import json
import re
from urllib.parse import urljoin

from config import SEARCH_URL

DOWNLOAD_ENDPOINT = urljoin(SEARCH_URL, "napix/highcourtorderdetails.php")

_VIEWJUD_RE = re.compile(r"""viewjud\(\s*["']([^"']+)["']\s*\)""")


def fetch_judgment_pdf(context, case_page, save_dir, case_ref, log=print):
    """
    case_page: the Playwright Page for the opened case detail page
               (same one extract_case_sections() was called on).
    save_dir: Path to write the PDF into (created if needed).
    case_ref: filesystem-safe base name to fall back on if the site
              doesn't give us a filename, e.g. "WP_12345_2023".

    Returns the PDF's filename (relative, just the name) on success,
    or None if there was no judgment PDF to fetch / the request failed.
    """
    try:
        button = case_page.locator('button[onclick*="viewjud"]').first
        if button.count() == 0:
            return None

        onclick = button.get_attribute("onclick") or ""
        match = _VIEWJUD_RE.search(onclick)
        if not match:
            return None
        token = match.group(1)
        if not token:
            return None

        resp = context.request.post(
            DOWNLOAD_ENDPOINT,
            form={"data": token},
            timeout=30000,
        )
        if not resp.ok:
            log(f"  Judgment PDF request failed ({resp.status}) for {case_ref}.")
            return None

        payload = json.loads(resp.text())
        if str(payload.get("status")) != "2" or not payload.get("data"):
            return None

        pdf_bytes = base64.b64decode(payload["data"])
        save_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = (payload.get("filename") or "").strip()
        filename = raw_filename if raw_filename.lower().endswith(".pdf") else f"{case_ref}.pdf"
        (save_dir / filename).write_bytes(pdf_bytes)
        return filename

    except Exception as e:
        log(f"  Could not fetch Judgment PDF for {case_ref}: {e}")
        return None
