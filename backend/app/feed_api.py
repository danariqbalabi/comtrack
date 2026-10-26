"""Reading the feed never fetches sources or changes saved observations."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from .quality.service import visible_competitions
from .repository import Repository, NotFoundError

router = APIRouter(prefix="/api", tags=["competitions"])


def repository_for(request: Request):
    return Repository(request.app.state.database)


@router.get("/competitions")
def feed(response: Response, category: Literal["hackathon", "BCC", "BPC"] | None = None,
         q: str = Query(default="", max_length=200), sort: Literal["newest", "deadline"] = "newest",
         offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100),
         repository: Repository = Depends(repository_for)):
    response.headers["Cache-Control"] = "no-store"
    rows = [row for row in visible_competitions(repository) if (category is None or row.data.category == category)
            and q.casefold() in (row.data.name + " " + (row.data.organizer or "")).casefold()]
    if sort == "deadline":
        def deadline(row):
            dates = [str(entry.date) for entry in row.data.timeline if entry.kind == "registration" and entry.date]
            return (min(dates) if dates else "9999-12-31", -row.id)
        rows.sort(key=deadline)
    return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}
