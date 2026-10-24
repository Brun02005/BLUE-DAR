"""API local + UI web (solo 127.0.0.1)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from importlib import resources

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from ..pipeline import Session
from ..store.export import entities_to_csv, snapshot_to_json

PUSH_INTERVAL_S = 1.0


class LabelIn(BaseModel):
    lab_id: str | None = None


class RegisterIn(BaseModel):
    node_id: str


class BatchIn(BaseModel):
    records: list[dict]


class CalibrateIn(BaseModel):
    entity_id: str
    node_id: str
    distance_m: float = 1.0


def _static(name: str) -> str:
    return resources.files("bluedar.app").joinpath("static", name).read_text(encoding="utf-8")


def create_app(session: Session) -> FastAPI:
    # Todos los endpoints son `async def`: corren en el hilo del event loop, el mismo
    # que alimenta la sesión. Con `def` FastAPI los manda a un threadpool y
    # `snapshot()` podría recorrer diccionarios que el escáner está modificando.
    app = FastAPI(title="BLUE-DAR", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _static("index.html")

    @app.get("/app.js")
    async def app_js() -> Response:
        return Response(_static("app.js"), media_type="text/javascript")

    @app.get("/style.css")
    async def style() -> Response:
        return Response(_static("style.css"), media_type="text/css")

    @app.get("/api/state")
    async def state() -> dict:
        return {**session.snapshot(), "meta": _public_meta(session)}

    @app.get("/api/entities/{entity_id}/history")
    async def history(entity_id: str) -> dict:
        points = session.history(entity_id)
        if points is None:
            raise HTTPException(404, "Entidad desconocida")
        return {"id": entity_id, "points": points}

    @app.post("/api/entities/{entity_id}/label")
    async def label(entity_id: str, body: LabelIn) -> dict:
        if not session.label(entity_id, body.lab_id):
            raise HTTPException(404, "Entidad desconocida")
        return {"ok": True}

    @app.post("/api/nodes/register")
    async def register_node(body: RegisterIn) -> dict:
        try:
            return session.register_node(body.node_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/nodes/{node_id}/observations")
    async def node_observations(node_id: str, body: BatchIn, authorization: str = Header("")) -> dict:
        token = authorization.removeprefix("Bearer ").strip()
        try:
            accepted = session.ingest_remote(node_id, token, body.records)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, f"Registro inválido: {exc}") from exc
        return {"accepted": accepted}

    @app.post("/api/calibrate")
    async def calibrate(body: CalibrateIn) -> dict:
        try:
            return session.calibrate(body.entity_id, body.node_id, body.distance_m)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/export.csv")
    async def export_csv() -> PlainTextResponse:
        snap = session.snapshot()
        return PlainTextResponse(
            entities_to_csv(snap["entities"]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=bluedar-entidades.csv"},
        )

    @app.get("/api/export.json")
    async def export_json() -> Response:
        return Response(
            snapshot_to_json(session.snapshot(), _public_meta(session)),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=bluedar-sesion.json"},
        )

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        try:
            while True:
                await socket.send_text(json.dumps(session.snapshot(), default=str))
                await asyncio.sleep(PUSH_INTERVAL_S)
        except WebSocketDisconnect:
            pass
        except Exception:
            with contextlib.suppress(Exception):
                await socket.close()

    return app


def _public_meta(session: Session) -> dict:
    keys = ("session_id", "adapter", "scanning_mode", "keep_names", "classic", "source", "labels")
    return {k: session.meta[k] for k in keys if k in session.meta}
