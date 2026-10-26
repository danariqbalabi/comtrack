import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .config import Settings, get_settings
from .database import Database, MigrationError
from .jobs_api import router as jobs_router
from .feed_api import router as feed_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    database = Database(get_settings().resolved_database_path)
    await run_in_threadpool(database.migrate)
    application.state.database = database
    yield


def get_database(request: Request) -> Database:
    return request.app.state.database


app = FastAPI(
    title=get_settings().app_name,
    description="API pribadi Lomba Radar. Tahap 5: job manual dan worker terpisah.",
    version="0.5.0",
    lifespan=lifespan,
)
app.include_router(jobs_router)
app.include_router(feed_router)


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
