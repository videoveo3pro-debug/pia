from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.services.health_monitor import run_health_monitor
from app.services.vpn_manager import VPNManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

manager = VPNManager(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_task = asyncio.create_task(asyncio.to_thread(manager.recover_all, force=False))
    task = asyncio.create_task(run_health_monitor(manager, settings.health_interval_seconds))
    try:
        yield
    finally:
        startup_task.cancel()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="PIA SOCKS5 Multi-Worker Gateway",
    version="5.0.0-multi-worker-gateway",
    lifespan=lifespan,
)


if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def api_token_auth(request: Request, call_next):
    if not settings.api_auth_enabled:
        return await call_next(request)
    path = request.url.path
    exempt_prefixes = [p.strip() for p in settings.api_auth_exempt_paths if p.strip()]
    def is_exempt(item: str) -> bool:
        if item == "/":
            return path == "/"
        return path == item or path.startswith(item.rstrip("/") + "/")
    if any(is_exempt(item) for item in exempt_prefixes):
        return await call_next(request)
    if not path.startswith("/api"):
        return await call_next(request)
    expected = settings.api_token.strip()
    supplied = request.headers.get("authorization", "")
    token = supplied.removeprefix("Bearer ").strip() if supplied.lower().startswith("bearer ") else request.headers.get("x-api-token", "").strip()
    if not expected or token != expected:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized. Set Authorization: Bearer <API_TOKEN>."})
    return await call_next(request)


app.include_router(router)

WEB_DIR = Path(__file__).parent / "web"
STATIC_DIR = WEB_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(str(WEB_DIR / "dashboard.html"))


@app.get("/api-docs", include_in_schema=False)
def api_docs_page():
    return FileResponse(str(WEB_DIR / "api-docs.html"))


@app.get("/healthz")
def healthz():
    return {"ok": True}
