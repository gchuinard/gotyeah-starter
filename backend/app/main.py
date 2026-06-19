"""App FastAPI : sert le frontend statique, lance les provisionnements et stream les logs (SSE)."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .events import bus
from .models import ProvisionRequest, ProvisionStarted
from .orchestrator import Orchestrator

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="gotyeah-starter", version="1.0.0")

# Tâches en cours, gardées pour éviter qu'elles soient garbage-collectées.
_tasks: dict[str, asyncio.Task] = {}


@app.get("/api/health")
async def health() -> dict:
    """Indique quelles intégrations sont configurées (sans révéler les secrets)."""
    return {
        "status": "ok",
        "config": {
            "github": bool(settings.github_token and settings.github_owner),
            "cloudflare": bool(settings.cloudflare_token and settings.pi_public_ip),
            "npm": bool(settings.npm_email and settings.npm_password),
        },
    }


@app.post("/api/provision", response_model=ProvisionStarted)
async def provision(req: ProvisionRequest) -> ProvisionStarted:
    job_id = uuid.uuid4().hex
    bus.create(job_id)
    orch = Orchestrator(job_id, req)
    task = asyncio.create_task(orch.run())
    _tasks[job_id] = task
    task.add_done_callback(lambda _t, jid=job_id: _tasks.pop(jid, None))
    return ProvisionStarted(job_id=job_id)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def stream():
        try:
            async for event in bus.subscribe(job_id):
                yield f"data: {json.dumps(event.model_dump())}\n\n"
        finally:
            # Laisse l'historique dispo un court instant pour d'éventuelles reconnexions,
            # puis nettoie quand le job est terminé.
            await asyncio.sleep(0)

    if job_id not in _tasks and job_id not in bus._history:  # noqa: SLF001
        raise HTTPException(status_code=404, detail="Job inconnu")
    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Frontend statique (servi par le même conteneur) -------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
