from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings
from .job_queue import JobQueue, NoSourcesError
from .repository import NotFoundError

router = APIRouter(prefix="/api", tags=["collection jobs"])


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ids: list[Annotated[int, Field(strict=True, ge=1)]] | None = Field(default=None, min_length=1, max_length=30)


def queue_for(request: Request):
    return JobQueue(request.app.state.database, lease_seconds=get_settings().worker_lease_seconds)


@router.post("/refresh", status_code=202)
def refresh(request: Request, response: Response, body: RefreshRequest, queue: JobQueue = Depends(queue_for)):
    # A custom header prevents cross-site simple requests from causing paid/network collection later.
    if request.headers.get("x-lomba-radar") != "1":
        raise HTTPException(status_code=403, detail="Header X-Lomba-Radar: 1 diperlukan.")
    origin = request.headers.get("origin")
    allowed = {item.strip() for item in get_settings().api_allowed_origins.split(",") if item.strip()}
    if origin is not None and origin not in allowed:
        raise HTTPException(status_code=403, detail="Origin permintaan tidak diizinkan.")
    try:
        job_id, created = queue.enqueue(body.source_ids)
    except NoSourcesError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return {"id": job_id, "created": created, "job": queue.get(job_id)}


@router.get("/jobs/latest")
def latest(response: Response, queue: JobQueue = Depends(queue_for)):
    response.headers["Cache-Control"] = "no-store"
    return {"job": queue.latest()}


@router.get("/jobs/{job_id}")
def job(response: Response, job_id: Annotated[int, Path(ge=1)], queue: JobQueue = Depends(queue_for)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return queue.get(job_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
