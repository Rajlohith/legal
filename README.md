# Karnataka Judiciary Case Search

A desktop tool that searches the Karnataka Judiciary case-status website
for judgments matching one or more entity names over a date range,
opens each matching case's detail page, and compiles everything into
a single Excel workbook (one `Summary` sheet + one detail sheet per
case).

This started as a single 538-line script (`search.py`). It has been
split into a proper project with a clean GUI on top; the scraping
behavior itself is unchanged.

## Project layout

```
legal_case_search/
├── main.py                  # entry point — run this
├── config.py                 # URL, section list, bench options, defaults
├── requirements.txt
├── scraper/
│   ├── search_engine.py       # orchestrates the whole browser run
│   ├── captcha.py             # CAPTCHA screenshot + OCR
│   ├── table_utils.py         # locate the judgments results table
│   ├── case_extraction.py     # pull each case's detail sections
│   ├── text_utils.py          # cleaning, sheet-name/filename sanitizing
│   └── date_utils.py          # date parsing + 90-day window splitting
├── excel/
│   └── writer.py              # builds the combined .xlsx workbook
└── gui/
    ├── app.py                 # the CustomTkinter desktop window
    └── settings.py            # remembers tesseract path / headless choice
```

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

You'll also need Tesseract OCR installed separately (it's a system
binary, not a Python package):
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- macOS: `brew install tesseract`
- Linux: `sudo apt install tesseract-ocr`

The app tries to find it automatically; if it can't, set the path in
the **Settings** dialog (gear icon, top right).

## Running

```bash
python main.py
```

1. Enter one or more entity aliases (one per line, or comma-separated).
2. Enter a start and end date (`DD-MM-YYYY`).
3. Pick a bench.
4. Choose where to save the output `.xlsx`.
5. Click **Run Search**. Progress and status appear in the activity
   log on the right; **Stop** ends the run early and still saves
   whatever was collected so far.

## Notes

- The site limits each query to a 90-day window, so a longer range is
  automatically split into consecutive windows behind the scenes.
- CAPTCHA solving is automatic (OCR via Tesseract) with up to 5 retries
  per search; leave the browser visible (Settings → uncheck headless)
  if you want to watch it work or step in if OCR keeps failing.
- Duplicate cases found through more than one alias are skipped and
  counted in the final summary.
