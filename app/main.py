"""Shot Deadline API + UI.

GET  /api/board        the live shot board (from the in-process simulation)
POST /api/chat         {question, conversation_id?} → SSE stream of tool calls, findings, plan
GET  /api/config       Grafana URL for dashboard links

With EMIT=true the production simulation runs inside the app and streams metrics/logs to Grafana
Cloud over OTLP. The agent only ever reads Grafana through the official mcp-grafana server.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel

from agent.pipeline import build_pipeline
from telemetry.sim import build_world, run_simulation

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
APP_NAME = "shot-deadline"

world = build_world()
_stop = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if os.environ.get("EMIT", "true").lower() == "true":
        task = asyncio.create_task(run_simulation(world, _stop))
    yield
    _stop.set()
    if task:
        await task


app = FastAPI(title="Shot Deadline", version="1.0", lifespan=lifespan)


@app.get("/api/board")
async def board():
    return world.board()


@app.get("/api/config")
async def config():
    return {"grafana_url": os.environ.get("GRAFANA_URL", ""), "dashboard_uid": os.environ.get("DASHBOARD_UID", "shot-deadline")}


_runner: Optional[InMemoryRunner] = None
_sessions: dict[str, str] = {}
_lock = asyncio.Lock()


async def runner() -> InMemoryRunner:
    global _runner
    if _runner is None:
        _runner = InMemoryRunner(agent=build_pipeline(), app_name=APP_NAME)
    return _runner


class ChatIn(BaseModel):
    question: str
    conversation_id: Optional[str] = None


def _sse(o: dict) -> str:
    return f"data: {json.dumps(o, default=str)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatIn):
    r = await runner()
    cid = body.conversation_id or uuid.uuid4().hex[:10]
    async with _lock:
        if cid not in _sessions:
            s = await r.session_service.create_session(app_name=APP_NAME, user_id="coordinator")
            _sessions[cid] = s.id
    sid = _sessions[cid]
    # give the agent the board's own snapshot as context, so numbers line up with what the user sees
    b = world.board()
    snap = "; ".join(f"{s['sequence']} lock in {s['days_to_lock']:.1f}d" for s in b["sequences"])
    msg = types.Content(role="user", parts=[types.Part(text=f"(Board now: {snap}.) {body.question}")])

    async def gen():
        yield _sse({"kind": "start", "conversation_id": cid})
        try:
            async for ev in r.run_async(user_id="coordinator", session_id=sid, new_message=msg):
                if not (ev.content and ev.content.parts):
                    continue
                for p in ev.content.parts:
                    if p.function_call:
                        yield _sse({"kind": "tool_call", "agent": ev.author, "name": p.function_call.name, "args": dict(p.function_call.args or {})})
                    elif p.function_response:
                        resp = p.function_response.response
                        try:
                            preview = resp["content"][0]["text"][:1500]
                        except Exception:
                            preview = json.dumps(resp, default=str)[:1200]
                        yield _sse({"kind": "tool_result", "agent": ev.author, "name": p.function_response.name, "preview": preview})
                    elif p.text and not ev.partial:
                        yield _sse({"kind": "text", "agent": ev.author, "text": p.text})
            yield _sse({"kind": "done"})
        except Exception as e:
            yield _sse({"kind": "error", "error": f"{type(e).__name__}: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz():
    return {"ok": True, "hour": world.hour, "otlp": bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")), "grafana": bool(os.environ.get("GRAFANA_URL"))}


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
