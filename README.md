# Karnataka Judiciary Case Search

A tool that searches the Karnataka Judiciary case-status website
(`rep_judgment.php`) for judgments, opens each matching case's detail
page, and compiles everything into a single Excel workbook (one
`Summary` sheet + one detail sheet per case).

It ships two front ends on top of the same scraper:

- **Desktop GUI** (`main.py`) -- the original CustomTkinter app.
- **Web UI** (`web.py`) -- a browser-based version with every search
  field the real site exposes, plus an optional AI "describe your
  search in plain English" mode.

Both drive the exact same Playwright + Tesseract engine
(`scraper/search_engine.py`), so search behavior, CAPTCHA solving,
90-day date-window splitting, deduplication, progress/cancellation,
and the combined Excel export all work identically either way.

## Project layout

```
legal/
├── main.py                    # desktop entry point
├── web.py                     # web UI entry point
├── config.py                  # URL, section list, and every real form field (see below)
├── requirements.txt
├── .env.example                # web backend config (LLM keys, scraper options)
├── scraper/
│   ├── search_engine.py        # orchestrates the whole browser run
│   ├── judge_lookup.py         # live "Judge"/"Author Judge" dropdown lookup
│   ├── captcha.py               # CAPTCHA screenshot + OCR
│   ├── table_utils.py           # locate the judgments results table
│   ├── case_extraction.py       # pull each case's detail sections
│   ├── text_utils.py            # cleaning, sheet-name/filename sanitizing
│   └── date_utils.py            # date parsing + 90-day window splitting
├── excel/
│   └── writer.py                # builds the combined .xlsx workbook
├── gui/                        # desktop UI (CustomTkinter)
│   ├── app.py
│   └── settings.py
├── backend/                    # web UI's FastAPI server
│   ├── server.py                 # routes + WebSocket log/progress stream
│   ├── job_manager.py            # background search job, one at a time
│   ├── ai_fill.py                 # natural language -> structured field values
│   └── schemas.py                 # request/response models
├── frontend/                   # web UI's static assets
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── outputs/                    # web UI's saved .xlsx files land here
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

The app tries to find it automatically; if it can't, point it at the
right path (Settings dialog on desktop, `TESSERACT_CMD` in `.env` on
web).

## Running the desktop app

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

## Running the web app

```bash
cp .env.example .env      # fill in an LLM key if you want the AI-fill feature
python web.py
```

Then open **http://localhost:8000**.

The page has every search field the real site exposes: Judge, Author
Judge, Coram, Case Type, Case Number, Case Year, Petitioner/Respondent
name and advocate, Date of Order range, Report Type, and a
multi-entity alias search (searches several names in turn, same as
the desktop app's alias list). Judge and Author Judge are populated
live from the site once you pick a bench, the same way the site's own
form does it.

You can either:
- **fill the form yourself**, or
- switch to **"Describe your search (AI)"**, type what you're looking
  for in plain English, and click **Fill form with AI**. The AI only
  ever *interprets your text into form values* -- it never touches
  the website. Every value it fills in lands back on the manual form
  for you to review and edit before you search.

Click **Run Search** either way. The Playwright + Tesseract scraper
then runs exactly as it always has: it fills in the real site's form,
solves the CAPTCHA, works through the results, and opens each case's
detail page. Progress, live log lines, and the final results stream
back over a WebSocket.

Results appear as expandable cards, one per case, each with every
detail section the site has for it (Party Information, Daily Orders,
Linked Cases, Judgment Information, Documents, Fees, and the rest of
`config.py`'s `SECTION_ORDER`), plus a link to download the same
combined Excel workbook the desktop app produces.

### Configuring the AI-fill feature

Set `LLM_PROVIDER` in `.env` to `gemini` (default) or `openai`:

```bash
# Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.0-flash

# or an OpenAI-compatible endpoint (OpenAI, Groq, a local
# Ollama/vLLM server, etc.)
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

API keys are read from environment variables server-side only; they
are never sent to or exposed in the browser. If no key is configured,
the AI tab shows an error and the manual form still works normally.

## Notes

- The site limits each date-of-order query to a 90-day window, so a
  longer range is automatically split into consecutive windows behind
  the scenes -- unchanged from the original script.
- CAPTCHA solving is automatic (OCR via Tesseract) with up to 5
  retries per search.
- Duplicate cases found through more than one alias/date-window are
  skipped and counted in the final summary.
- A Case Number search (Case Type + Case Number + Case Year, all
  filled in) doesn't require a date range, matching the real site's
  own validation rule; every other combination still needs a
  Date of Order range.
- Every field in `config.py` (`CASE_TYPES`, `CASE_YEARS`,
  `CORAM_OPTIONS`, `REPORT_TYPE_OPTIONS`, `BENCH_OPTIONS`) was read
  directly out of the live site's HTML/JS, not guessed -- see the
  comments above each block in `config.py` for exactly where each one
  came from.
- Only one search runs at a time in the web app (same as the desktop
  app only having one browser window); starting a new one while
  another is running is rejected until you stop it or it finishes.
