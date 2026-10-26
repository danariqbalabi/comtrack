import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .config import ROOT, Settings, get_settings
from .database import Database, MigrationError
from .jobs_api import router as jobs_router
from .feed_api import router as feed_router
from .settings_api import router as settings_router
from .security import protect_writes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    if bool(settings.access_username) != bool(settings.access_password.get_secret_value()):
        raise RuntimeError("ACCESS_USERNAME dan ACCESS_PASSWORD harus diisi berpasangan.")
    if settings.app_env == 'production':
        if not settings.access_username or len(settings.access_password.get_secret_value()) < 16:
            raise RuntimeError("Production memerlukan username dan password pribadi minimal 16 karakter.")
        if not (ROOT / 'frontend' / 'dist' / 'index.html').exists():
            raise RuntimeError("Build frontend dahulu sebelum menjalankan production.")
    database = Database(get_settings().resolved_database_path)
    await run_in_threadpool(database.migrate)
    application.state.database = database
    yield


def get_database(request: Request) -> Database:
    return request.app.state.database


app = FastAPI(
    title=get_settings().app_name,
    description="Radar pribadi lomba Indonesia dengan pencarian manual dan bukti sumber.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(jobs_router)
app.include_router(feed_router)
app.include_router(settings_router)
app.middleware("http")(protect_writes)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    environment: str
    database: str = "ok"
    schema_version: str


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health(response: Response, settings: Settings = Depends(get_settings),
           database: Database = Depends(get_database)) -> HealthResponse:
    """Only report healthy after reading the initialized application database."""
    response.headers["Cache-Control"] = "no-store"
    try:
        version = database.check()
    except (sqlite3.Error, MigrationError, OSError):
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database belum siap.") from None
    return HealthResponse(service=settings.app_name, environment=settings.app_env, schema_version=version)


if (ROOT / 'frontend' / 'dist').is_dir():
    app.mount('/', StaticFiles(directory=ROOT / 'frontend' / 'dist', html=True), name='frontend')
