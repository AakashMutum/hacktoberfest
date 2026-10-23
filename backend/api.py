"""FastAPI app: WebSocket stream, metrics, investigation, graph, vision scan and red-team endpoints."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import investigator, policy, rules  # noqa: E402
from .engine import ROOT, Engine  # noqa: E402

engine: Engine | None = None
log = logging.getLogger("circuit_breaker")

SCAN_PATH = "/api/scan-screenshot"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
# Room for multipart boundaries and the form fields around the image.
MAX_SCAN_BODY = MAX_IMAGE_BYTES + 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = Engine(seed=int(os.getenv("SEED", "42")))
    tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.worker())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Circuit Breaker", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def limit_scan_upload(request: Request, call_next):
    """Reject oversized screenshot uploads from Content-Length, before the body is read."""
    if request.url.path == SCAN_PATH and request.method == "POST":
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse({"detail": "Content-Length header required"}, status_code=411)
        try:
            size = int(length)
        except ValueError:
            return JSONResponse({"detail": "invalid Content-Length header"}, status_code=400)
        if size > MAX_SCAN_BODY:
            return JSONResponse({"detail": "image larger than 6 MB"}, status_code=413)
    return await call_next(request)


class Toggle(BaseModel):
    enabled: bool


class Control(BaseModel):
    action: str
    speed: int | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "llm": engine.llm_status, "llm_available": engine.llm_status["state"] == "ready",
            "seed": engine.seed, "safe_mode": engine.safe_mode, "cached_results": engine.cached_count(), "rules": {"simple": rules.describe("simple"), "tight": rules.describe("tight")},
            "thresholds": policy.THRESHOLDS, "hold_minutes": policy.HOLD_MINUTES}


@app.get("/api/metrics")
def metrics():
    return engine.metrics()


@app.post("/api/stream/control")
def control(c: Control):
    if c.action == "pause":
        engine.running = False
    elif c.action == "resume":
        engine.running = engine.cursor < len(engine.stream_rows)
    elif c.action == "reset":
        engine.reset()
    elif c.action == "speed" and c.speed in (1, 4, 16):
        engine.speed = c.speed
    else:
        raise HTTPException(400, "unknown control")
    return engine.metrics()["stream"]


@app.post("/api/lang/{lang}")
def set_lang(lang: str):
    if lang not in policy.LANGS:
        raise HTTPException(400, "lang must be en, ta or hi")
    engine.lang = lang
    return {"lang": lang}


@app.get("/api/copy")
def copy():
    return {"copy": policy.COPY, "hold_minutes": policy.HOLD_MINUTES}


@app.get("/api/txn/{txn_id}")
def txn(txn_id: str):
    rec = engine.records.get(txn_id)
    if rec is None:
        raise HTTPException(404, "transaction not in recent window")
    return rec


@app.post("/api/investigate/{txn_id}")
async def investigate(txn_id: str, lang: str = "en"):
    if lang not in policy.LANGS:
        raise HTTPException(400, "lang must be en, ta or hi")
    result = engine.request_investigation(txn_id, lang)
    if result is None:
        raise HTTPException(404, "transaction not in recent window")
    return result


@app.post("/api/safe-mode")
async def safe_mode(t: Toggle):
    engine.safe_mode = t.enabled
    state = {"enabled": engine.safe_mode, "cached_results": engine.cached_count()}
    await engine.broadcast({"type": "safe_mode", **state})
    return state


@app.get("/api/llm-status")
def llm_status():
    return engine.llm_status


@app.get("/api/graph/{txn_id}")
def graph(txn_id: str):
    g = engine.ego_graph(txn_id)
    if g is None:
        raise HTTPException(404, "transaction not in recent window")
    return g


@app.post("/api/scan-screenshot")
async def scan_screenshot(file: UploadFile = File(...), lang: str = Form("en")):
    if file.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(415, "upload a PNG, JPEG or WebP image")
    if await investigator.resolve_provider() is None:
        raise HTTPException(503, "Scan unavailable: no model provider is configured")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image larger than 6 MB")
    try:
        return await investigator.scan_image(data, file.content_type, lang)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Gemma did not answer in time")
    except Exception:
        log.exception("screenshot scan failed")
        raise HTTPException(503, "Scan unavailable: the model could not read this image")


@app.post("/api/redteam/attack")
def redteam_attack():
    return engine.attack()


@app.post("/api/redteam/adapt")
async def redteam_adapt():
    return await asyncio.to_thread(engine.adapt)


@app.get("/api/redteam")
def redteam_state():
    return {"attacks": engine.attacks, "adapt": engine.adapt_result}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue()
    engine.subscribers.add(q)
    try:
        await websocket.send_json({"type": "hello", "metrics": engine.metrics()})
        while True:
            await websocket.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.subscribers.discard(q)


DIST = os.path.realpath(os.path.join(ROOT, "web", "dist"))


def resolve_static(path: str) -> str:
    """Map a request path to a file inside web/dist, or to index.html for anything else."""
    index = os.path.join(DIST, "index.html")
    if not path:
        return index
    target = os.path.realpath(os.path.join(DIST, path))
    try:
        inside = os.path.commonpath([DIST, target]) == DIST
    except ValueError:  # different drives on Windows
        inside = False
    if inside and os.path.isfile(target):
        return target
    return index


if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        return FileResponse(resolve_static(path))
