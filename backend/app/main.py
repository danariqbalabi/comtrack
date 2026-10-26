from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel

from .config import Settings, get_settings

app = FastAPI(
    title=get_settings().app_name,
    description="API pribadi Lomba Radar. Tahap 1: fondasi dan pemeriksaan kesehatan.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    environment: str


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health(response: Response, settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report API availability; no database or provider is configured at this stage."""
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse(service=settings.app_name, environment=settings.app_env)
