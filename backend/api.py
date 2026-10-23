"""FastAPI app: WebSocket stream, metrics, investigation, graph, vision scan and red-team endpoints."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import investigator, policy  # noqa: E402
from .engine import ROOT, Engine  # noqa: E402

engine: Engine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = Engine(seed=int(os.getenv("SEED", "42")))
    tasks = [asyncio.create_task(engine.run()), asyncio.create_task(engine.auto_investigate())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Circuit Breaker", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Control(BaseModel):
    action: str
    speed: int | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "provider": investigator.provider(), "model": investigator.model_name(),
            "llm_available": investigator.available(), "seed": engine.seed,
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
    result = await engine.investigate(txn_id, lang)
    if result is None:
        raise HTTPException(404, "transaction not in recent window")
    return result


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
    data = await file.read()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(413, "image larger than 6 MB")
    try:
        return await investigator.scan_image(data, file.content_type, lang)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Gemma did not answer in time")
    except Exception as exc:
        raise HTTPException(503, f"Scan unavailable: {str(exc)[:200]}")


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


_dist = os.path.join(ROOT, "web", "dist")
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = os.path.join(_dist, path)
        if path and os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(_dist, "index.html"))
