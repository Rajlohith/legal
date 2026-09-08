"""
FastAPI backend for the Karnataka Judiciary Case Search web UI.

Run with:
    python web.py
or:
    uvicorn backend.server:app --host 0.0.0.0 --port 8000

Routes:
  GET  /                    -- the web UI (frontend/index.html)
  GET  /api/form-options    -- static dropdown data (case types, years, coram, bench, report type)
  POST /api/judges          -- {db_bench} -> live Judge/Author Judge options for that bench
  POST /api/ai-fill         -- {text} -> LLM-interpreted structured field values, for review
  POST /api/search          -- {..SearchCriteria..} -> starts the Playwright+Tesseract scraper
  POST /api/search/stop     -- requests early stop of the running search
  WS   /ws/logs             -- live log lines / progress / final results
  GET  /outputs/<file>.xlsx -- download a finished workbook
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import BENCH_OPTIONS, CASE_TYPES, CASE_YEARS, CORAM_OPTIONS, REPORT_TYPE_OPTIONS
from scraper.judge_lookup import fetch_judge_options

from backend.ai_fill import AiFillError, ai_fill_form
from backend.job_manager import OUTPUT_DIR, job_manager
from backend.schemas import (
    AiFillRequest,
    AiFillResponse,
    JudgeLookupRequest,
    SearchCriteria,
    SearchStartResponse,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

TESSERACT_CMD = os.environ.get("TESSERACT_CMD") or None
SCRAPER_HEADLESS = os.environ.get("SCRAPER_HEADLESS", "true").strip().lower() != "false"

app = FastAPI(title="Karnataka Judiciary Case Search")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def bind_event_loop():
    import asyncio

    job_manager.bind_loop(asyncio.get_running_loop())


# ----------------------------------------------------------------------
# Static form data
# ----------------------------------------------------------------------


@app.get("/api/form-options")
async def form_options():
    return {
        "db_bench": [{"value": v, "label": k} for k, v in BENCH_OPTIONS.items()],
        "case_types": [{"value": v, "label": label} for v, label in CASE_TYPES],
        "case_years": [y for y in CASE_YEARS if y],
        "coram": [{"value": v, "label": k} for k, v in CORAM_OPTIONS.items()],
        "report_type": [{"value": v, "label": k} for k, v in REPORT_TYPE_OPTIONS.items()],
    }


@app.post("/api/judges")
async def judges(request: JudgeLookupRequest):
    if request.db_bench not in ("B", "D", "K"):
        return {"judges": [], "error": "db_bench must be B, D or K."}

    try:
        options = await run_in_threadpool(
            fetch_judge_options, request.db_bench, SCRAPER_HEADLESS,
        )
    except Exception as e:  # noqa: BLE001 -- surfaced to the UI
        return {"judges": [], "error": str(e)}

    return {"judges": options}


# ----------------------------------------------------------------------
# AI fill
# ----------------------------------------------------------------------


@app.post("/api/ai-fill", response_model=AiFillResponse)
async def ai_fill(request: AiFillRequest):
    try:
        fields, notes = await ai_fill_form(request.text)
    except AiFillError as e:
        return AiFillResponse(fields={}, notes=str(e))

    return AiFillResponse(fields=fields, notes=notes)


# ----------------------------------------------------------------------
# Search job
# ----------------------------------------------------------------------


@app.post("/api/search", response_model=SearchStartResponse)
async def start_search(criteria: SearchCriteria):
    started, message = job_manager.start(
        criteria.model_dump(), tesseract_cmd=TESSERACT_CMD, headless=SCRAPER_HEADLESS,
    )
    return SearchStartResponse(started=started, message=message)


@app.post("/api/search/stop")
async def stop_search():
    stopped = job_manager.request_stop()
    return {"stopped": stopped}


@app.get("/api/search/status")
async def search_status():
    return {"is_running": job_manager.is_running}


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    queue = job_manager.subscribe()
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        job_manager.unsubscribe(queue)


# ----------------------------------------------------------------------
# Output files + frontend
# ----------------------------------------------------------------------


@app.get("/outputs/{filename}")
async def download_output(filename: str):
    path = (OUTPUT_DIR / filename).resolve()
    if OUTPUT_DIR.resolve() not in path.parents or not path.exists():
        return {"error": "File not found."}
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
