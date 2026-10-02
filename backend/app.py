from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import PROJECT_ROOT
from .runtime import StreamRuntime

load_dotenv(PROJECT_ROOT / ".env")


class ActionRequest(BaseModel):
    action: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def create_app(runtime: StreamRuntime | None = None) -> FastAPI:
    rt = runtime or StreamRuntime()
    web_dir = rt.root / "web"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = rt
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(title="BicycleStreamUI", version="2.0", lifespan=lifespan)
    app.state.runtime = rt
    app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")

    @app.get("/")
    async def root():
        return RedirectResponse("/admin")

    @app.get("/challenge-overlay")
    async def challenge_overlay():
        return FileResponse(web_dir / "challenge-overlay.html")

    @app.get("/event-overlay")
    async def event_overlay():
        return FileResponse(web_dir / "event-overlay.html")

    @app.get("/dashboard")
    async def dashboard():
        return FileResponse(web_dir / "dashboard.html")

    @app.get("/admin")
    async def admin():
        return FileResponse(web_dir / "admin.html")

    @app.get("/api/state")
    async def state():
        return rt.overlay_state()

    @app.get("/api/events")
    async def events(since: int = 0):
        return {"events": rt.events_since(since), "last_seq": rt.events.last_seq}

    @app.get("/api/stats/topdamage")
    async def topdamage(limit: int = 5):
        return {"items": rt.db.top_damage(max(1, min(100, limit)))}

    @app.get("/api/stats/search")
    async def search(q: str = ""):
        return {"items": rt.db.search_damage(q, 30)}

    @app.post("/api/admin/action")
    async def action(req: ActionRequest):
        try:
            return await rt.admin_action(req.action, req.payload)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            rt.log.exception("Admin action failed: %s", req.action)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        last_seq = 0
        try:
            while True:
                for ev in rt.events_since(last_seq):
                    await websocket.send_json({"type": "event", "payload": ev})
                    last_seq = max(last_seq, int(ev["seq"]))
                await websocket.send_json({"type": "state", "payload": rt.overlay_state()})
                await asyncio.sleep(0.25)
        except (WebSocketDisconnect, asyncio.CancelledError):
            return

    return app


app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.getenv("BICYCLE_STREAM_PORT", "5050"))
    uvicorn.run("backend.app:app", host="127.0.0.1", port=port, reload=False, access_log=False)


if __name__ == "__main__":
    main()
