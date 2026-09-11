"""
Entry point for the web UI.

Run with:
    python web.py

This starts the FastAPI backend (backend/server.py) and serves the web
UI (frontend/) on http://localhost:8000 by default. The desktop GUI
(main.py) still works exactly as before -- this is an additional way
to use the same scraper, not a replacement for it.
"""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("DEV_RELOAD", "false").strip().lower() == "true"

    uvicorn.run("backend.server:app", host=host, port=port, reload=reload)
