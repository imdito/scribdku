"""FastAPI application: REST API plus the static Scribd downloader UI."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import backend_bridge
from auth import AuthError, AuthManager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from jobs import (
    SUPPORTED_FORMATS,
    BackendUnavailableError,
    InvalidFormatError,
    InvalidURLError,
    JobConflictError,
    JobError,
    JobManager,
    JobNotFoundError,
)

LOG_LEVEL = os.getenv("SCRIBD_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("scribd").setLevel(LOG_LEVEL)
logger = logging.getLogger("scribd.app")

VERSION = "1.0.0"
WEB_DIR = Path(
    os.getenv(
        "SCRIBD_WEB_DIR",
        Path(__file__).resolve().parent.parent / "scribd-downloader-web" / "scribd-downloader-web",
    )
).expanduser().resolve()

manager = JobManager.from_env()
auth = AuthManager.from_env()

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/me",
    "/api/auth/logout",
    "/api/openapi.json",
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "error": message},
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.initialize()
    await manager.start()
    logger.info("Scribd downloader API %s listening (web dir: %s)", VERSION, WEB_DIR)
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(
    title="Scribd Downloader API",
    version=VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def api_guard(request: Request, call_next):
    """Require a valid session for every API route except health and auth."""
    path = request.url.path
    protected = (
        path.startswith("/api/")
        and path not in PUBLIC_API_PATHS
        and not path.startswith("/api/docs")
    )

    if protected:
        username = auth.session_username(request.cookies.get(auth.cookie_name))
        if not username:
            response = _error(401, "unauthorized", "Silakan login terlebih dahulu.")
        else:
            request.state.username = username
            response = await call_next(request)
    else:
        response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
    return _error(422, "invalid_request", "Permintaan tidak valid.")


class CreateJobPayload(BaseModel):
    url: str = ""
    format: str = "pdf"


class LoginPayload(BaseModel):
    username: str = ""
    password: str = ""


class CreateUserPayload(BaseModel):
    username: str = ""
    password: str = ""


@app.post("/api/auth/login")
async def login(payload: LoginPayload, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    username = (payload.username or "").strip()
    throttle_key = auth.throttle_key(client_ip, username)

    retry_after = auth.retry_after(throttle_key)
    if retry_after:
        return _error(
            429,
            "too_many_attempts",
            f"Terlalu banyak percobaan. Coba lagi dalam {retry_after} detik.",
        )

    verified = await asyncio.to_thread(
        auth.verify_credentials, username, payload.password
    )
    if not verified:
        auth.record_failure(throttle_key)
        logger.warning("failed login for %r from %s", username, client_ip)
        return _error(401, "invalid_credentials", "Username atau password salah.")

    auth.clear_failures(throttle_key)
    token = auth.create_session(verified)
    response = JSONResponse({"username": verified})
    auth.set_session_cookie(response, token)
    logger.info("login ok for %s from %s", verified, client_ip)
    return response


@app.get("/api/auth/me")
async def current_user(request: Request):
    username = auth.session_username(request.cookies.get(auth.cookie_name))
    if not username:
        return _error(401, "unauthorized", "Silakan login terlebih dahulu.")
    return auth.get_public_user(username) or {"username": username}


@app.post("/api/auth/logout")
async def logout():
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


@app.get("/api/auth/users")
async def list_users() -> list[dict]:
    return auth.list_users()


@app.post("/api/auth/users", status_code=201)
async def create_user(payload: CreateUserPayload, request: Request):
    try:
        user = await asyncio.to_thread(
            auth.create_user,
            payload.username,
            payload.password,
            getattr(request.state, "username", "unknown"),
        )
    except AuthError as error:
        return _error(error.status_code, error.code, error.message)
    return JSONResponse(status_code=201, content=user)


@app.get("/api/health")
async def health() -> dict:
    try:
        backend_script = str(backend_bridge.backend_script_path())
    except RuntimeError:
        backend_script = None
    return {
        "status": "ok",
        "service": "scribd-downloader",
        "version": VERSION,
        "backend_script": backend_script,
        **manager.stats(),
    }


@app.get("/api/config")
async def config() -> dict:
    return {
        "formats": list(SUPPORTED_FORMATS),
        "retention_days": manager.retention_days,
        "max_concurrent": manager.max_concurrent,
    }


@app.post("/api/jobs", status_code=202)
async def create_job(payload: CreateJobPayload):
    try:
        return await manager.create_job(payload.url, payload.format)
    except JobError as error:
        return _error(error.status_code, error.code, error.message)


@app.get("/api/jobs")
async def list_jobs() -> list[dict]:
    return manager.list_jobs()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return manager.get_job(job_id)
    except JobError as error:
        return _error(error.status_code, error.code, error.message)


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    try:
        return await manager.cancel_job(job_id)
    except JobError as error:
        return _error(error.status_code, error.code, error.message)


@app.get("/api/jobs/{job_id}/file")
async def download_file(job_id: str):
    try:
        path, filename, media_type = manager.get_file(job_id)
    except JobError as error:
        return _error(error.status_code, error.code, error.message)
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    try:
        await manager.delete_job(job_id)
    except JobError as error:
        return _error(error.status_code, error.code, error.message)
    return {"deleted": job_id}


@app.delete("/api/jobs")
async def clear_history():
    removed = await manager.clear_history()
    return {"removed": removed}


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:
    logger.warning("web directory not found: %s", WEB_DIR)

    @app.get("/")
    async def missing_web() -> JSONResponse:
        return _error(
            503,
            "web_missing",
            f"Folder UI tidak ditemukan: {WEB_DIR}",
        )


# Re-exported for tests and for clearer tracebacks from uvicorn.
__all__ = [
    "app",
    "manager",
    "auth",
    "BackendUnavailableError",
    "InvalidFormatError",
    "InvalidURLError",
    "JobConflictError",
    "JobNotFoundError",
]
