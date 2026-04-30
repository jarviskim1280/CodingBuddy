"""FastAPI dashboard — REST API + WebSocket real-time stream."""
import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from buddy.db import init_db
from dashboard.api.routes import agents, projects, tasks

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="CodingBuddy Dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(agents.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    init_db()


# ── WebSocket broadcast manager ───────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)

    async def broadcast(self, event: dict):
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


manager = ConnectionManager()


async def broadcast_event(event: dict):
    """Injected into agents by the runner."""
    await manager.broadcast(event)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client sends pings
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Serve the built React UI (or a fallback) ─────────────────────────────────

UI_DIST = Path(__file__).parent.parent / "ui" / "dist"

if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = UI_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"message": "UI not built — run: cd dashboard/ui && npm run build"}
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "CodingBuddy API running",
            "ui": "Build the UI: cd dashboard/ui && npm install && npm run build",
            "docs": "/docs",
        }
