import threading
import uuid
import json
import os
from urllib.request import Request, urlopen
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scraper_service import ScraperService, parse_date


app = FastAPI(title="Iudicium", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
jobs = {}
jobs_lock = threading.Lock()
job_services = {}

BENCHES = {
    "principal": "B",
    "dharwad": "D",
    "kalaburagi": "K",
}


class SearchRequest(BaseModel):
    respondent_aliases: list[str] = Field(default_factory=list)
    petitioner_aliases: list[str] = Field(default_factory=list)
    judge: str | None = None
    author_judge: str | None = None
    coram: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_year: str | None = None
    petitioner_name: str | None = None
    respondent_name: str | None = None
    petitioner_advocate: str | None = None
    respondent_advocate: str | None = None
    start_date: str
    end_date: str
    bench: str = "principal"
    headless: bool = True
    tesseract_cmd: str | None = None


class AgentParseRequest(BaseModel):
    message: str = Field(min_length=1)


class AgentParseResponse(BaseModel):
    respondent_aliases: list[str] = Field(default_factory=list)
    petitioner_aliases: list[str] = Field(default_factory=list)
    judge: str | None = None
    author_judge: str | None = None
    coram: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_year: str | None = None
    petitioner_name: str | None = None
    respondent_name: str | None = None
    petitioner_advocate: str | None = None
    respondent_advocate: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bench: str | None = None


AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "")

AGENT_SCHEMA = AgentParseResponse.model_json_schema()


def run_job(job_id, request):
    def log(message):
        with jobs_lock:
            jobs[job_id]["logs"].append(message)

    def progress(done, total):
        with jobs_lock:
            jobs[job_id]["completed_jobs"] = done
            jobs[job_id]["total_jobs"] = total

    with jobs_lock:
        jobs[job_id]["status"] = "running"
    try:
        service = ScraperService(
            log=log,
            progress=progress,
            tesseract_cmd=request.tesseract_cmd,
            headless=request.headless,
        )
        with jobs_lock:
            job_services[job_id] = service
        result = service.run(
            respondent_aliases=request.respondent_aliases + ([request.respondent_name] if request.respondent_name else []),
            petitioner_aliases=request.petitioner_aliases + ([request.petitioner_name] if request.petitioner_name else []),
            filters={
                "judge": request.judge,
                "author_judge": request.author_judge,
                "coram": request.coram,
                "case_type": request.case_type,
                "case_number": request.case_number,
                "case_year": request.case_year,
                "petitioner_advocate": request.petitioner_advocate,
                "respondent_advocate": request.respondent_advocate,
            },
            start_date=parse_date(request.start_date),
            end_date=parse_date(request.end_date),
            bench_value=BENCHES[request.bench],
        )
        with jobs_lock:
            jobs[job_id].update(result, status="cancelled" if result["cancelled"] else "completed")
            job_services.pop(job_id, None)
    except Exception as error:
        with jobs_lock:
            jobs[job_id].update(status="failed", error=str(error))
            job_services.pop(job_id, None)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/agent/parse", response_model=AgentParseResponse)
def parse_agent_request(request: AgentParseRequest):
    if not all((AGENT_API_KEY, AGENT_BASE_URL, AGENT_MODEL)):
        raise HTTPException(
            status_code=503,
            detail="Agent configuration is empty. Set AGENT_API_KEY, AGENT_BASE_URL, and AGENT_MODEL.",
        )

    payload = {
        "model": AGENT_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Convert the user's natural-language judiciary search request into JSON. "
                    "Use DD-MM-YYYY dates. Return only JSON matching this schema: "
                    + json.dumps(AGENT_SCHEMA)
                ),
            },
            {"role": "user", "content": request.message},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        http_request = Request(
            f"{AGENT_BASE_URL.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {AGENT_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(http_request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        return AgentParseResponse.model_validate_json(content)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Agent parsing failed: {error}") from error


@app.post("/api/searches", status_code=202)
def create_search(request: SearchRequest):
    if request.bench not in BENCHES:
        raise HTTPException(status_code=422, detail="bench must be principal, dharwad, or kalaburagi")
    try:
        start_date = parse_date(request.start_date)
        end_date = parse_date(request.end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="dates must use DD-MM-YYYY")
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be before end_date")

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "completed_jobs": 0,
            "total_jobs": 0,
            "logs": [],
        }
    threading.Thread(target=run_job, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/searches/{job_id}/cancel")
def cancel_search(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        service = job_services.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="search job not found")
        if job["status"] not in {"queued", "running"}:
            return {"job_id": job_id, "status": job["status"]}
        if service is not None:
            service.request_stop()
        job["status"] = "cancelling"
        return {"job_id": job_id, "status": "cancelling"}


@app.get("/api/searches/{job_id}")
def get_search(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="search job not found")
        return job


@app.get("/api/searches/{job_id}/results")
def get_results(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="search job not found")
        if job["status"] not in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail="search is not complete")
        return {"cases": job.get("cases", []), "case_count": job.get("case_count", 0)}
