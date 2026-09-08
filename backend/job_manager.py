"""
Runs the (unchanged) SearchEngine in a background thread -- exactly
the same pattern gui/app.py already uses (worker thread + callbacks),
just re-pointed at WebSocket subscribers instead of a Tkinter queue.

Only one search runs at a time; that matches the desktop app (one
browser window) and keeps a single Chromium instance from being
launched multiple times concurrently on the server.
"""

import asyncio
import threading
from pathlib import Path

from config import BENCH_OPTIONS, DEFAULT_OUTPUT_FILENAME
from scraper.date_utils import parse_user_date
from scraper.search_engine import SearchEngine
from scraper.text_utils import sanitize_filename_part, split_party_names

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

BENCH_VALUE_TO_NAME = {v: k for k, v in BENCH_OPTIONS.items()}


def _serialize_cases(cases):
    """Turn the engine's raw case list into something the frontend can
    render directly: identity fields pulled out, plus every expandable
    section (Party Information, Daily Orders, Documents, Fees, etc.)."""
    serialized = []
    for case in cases:
        base_row = case.get("base_row", {})
        petitioner, respondent = split_party_names(
            base_row.get("Petitioner V/S Respondent Name", "")
        )
        serialized.append(
            {
                "case_type": base_row.get("Case Type", ""),
                "case_no": base_row.get("Case No", ""),
                "case_year": base_row.get("Case Year", ""),
                "petitioner": petitioner,
                "respondent": respondent,
                "base_row": base_row,
                "case_information": case.get("case_info_text", ""),
                "sections": case.get("sections_data", {}),
            }
        )
    return serialized


class JobManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._is_running = False
        self._subscribers = set()
        self._loop = None
        self.last_result = None

    # ------------------------------------------------------------------
    # WebSocket subscription
    # ------------------------------------------------------------------

    def bind_loop(self, loop):
        """Called once from the FastAPI app so the worker thread has a
        live event loop to safely hand messages back to."""
        self._loop = loop

    def subscribe(self):
        queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._subscribers.discard(queue)

    def _broadcast(self, msg_type, payload):
        if self._loop is None:
            return
        message = {"type": msg_type, "payload": payload}
        for queue in list(self._subscribers):
            self._loop.call_soon_threadsafe(queue.put_nowait, message)

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    @property
    def is_running(self):
        return self._is_running

    def start(self, criteria, tesseract_cmd=None, headless=True):
        with self._lock:
            if self._is_running:
                return False, "A search is already running. Stop it first."
            self._is_running = True

        thread = threading.Thread(
            target=self._run_job, args=(criteria, tesseract_cmd, headless), daemon=True,
        )
        thread.start()
        return True, "Search started."

    def request_stop(self):
        if self._engine:
            self._engine.request_stop()
            return True
        return False

    def _run_job(self, criteria, tesseract_cmd, headless):
        try:
            self._do_run(criteria, tesseract_cmd, headless)
        except Exception as e:  # noqa: BLE001 -- surfaced to the UI, not swallowed
            self._broadcast("error", str(e))
        finally:
            self._is_running = False
            self._engine = None

    def _do_run(self, criteria, tesseract_cmd, headless):
        def log(message):
            self._broadcast("log", message)

        def on_progress(done, total):
            self._broadcast("progress", {"done": done, "total": total})

        self._engine = SearchEngine(
            log=log, on_progress=on_progress, tesseract_cmd=tesseract_cmd, headless=headless,
        )

        from_date = parse_user_date(criteria["from_date"]) if criteria.get("from_date") else None
        to_date = parse_user_date(criteria["to_date"]) if criteria.get("to_date") else None

        bench_value = criteria["db_bench"]
        bench_name = BENCH_VALUE_TO_NAME.get(bench_value, bench_value)

        filename = criteria.get("output_filename") or DEFAULT_OUTPUT_FILENAME
        if not filename.lower().endswith(".xlsx"):
            filename += ".xlsx"
        filename = sanitize_filename_part(filename.rsplit(".xlsx", 1)[0]) + ".xlsx"
        output_path = str(OUTPUT_DIR / filename)

        summary = self._engine.run(
            criteria.get("aliases") or [],
            from_date,
            to_date,
            bench_value,
            bench_name,
            output_path,
            alias_field=criteria.get("alias_field") or "respondname",
            case_type=criteria.get("case_type") or None,
            case_no=criteria.get("case_no") or None,
            case_year=criteria.get("case_year") or None,
            petitioner_name=criteria.get("petitioner_name") or None,
            respondent_name=criteria.get("respondent_name") or None,
            petitioner_adv=criteria.get("petitioner_adv") or None,
            respondent_adv=criteria.get("respondent_adv") or None,
            judge=criteria.get("judge") or None,
            author_judge=criteria.get("author_judge") or None,
            coram=criteria.get("coram") or None,
            report_type=criteria.get("report_type") or None,
        )

        self.last_result = summary
        self._broadcast(
            "done",
            {
                "output_filename": Path(summary["output_path"]).name,
                "case_count": summary["case_count"],
                "duplicates_skipped": summary["duplicates_skipped"],
                "cancelled": summary["cancelled"],
                "cases": _serialize_cases(summary["cases"]),
            },
        )


job_manager = JobManager()
