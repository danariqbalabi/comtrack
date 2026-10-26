"""Personal preferences and validated monitoring sources; no fetch on save."""
import re
import sqlite3
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from .collectors.http import public_url, FetchError
from .collectors import ou_festival
from .feed_api import repository_for
from .models import Model, Preferences, SourceData
from .repository import Repository, NotFoundError

router = APIRouter(prefix="/api", tags=["settings"])


class SourceInput(Model):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    kind: str = "website"
    title_selector: str | None = Field(default=None, max_length=200)
    body_selector: str | None = Field(default=None, max_length=200)
    links_selector: str | None = Field(default=None, max_length=200)


class EnabledInput(Model):
    enabled: bool


def normalize_source(body: SourceInput) -> SourceData:
    url, kind = body.url.strip(), body.kind
    if kind not in ("website", "rss", "instagram"):
        raise ValueError("Jenis sumber tidak dikenal.")
    if kind == "instagram":
        if not url.startswith(("https://", "http://")):
            url = "https://www.instagram.com/" + url.lstrip("@") + "/"
        parsed = urlsplit(url)
        username = parsed.path.strip("/")
        if parsed.hostname not in ("instagram.com", "www.instagram.com") or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", username) or username in ("p", "reel", "stories", "explore"):
            raise ValueError("Masukkan username atau URL profil Instagram, bukan postingan.")
        url = f"https://www.instagram.com/{username.lower()}/"
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("Masukkan URL HTTP/HTTPS lengkap.")
    public_url(url, frozenset({host}))
    adapter = "instagram_provider" if kind == "instagram" else "rss" if kind == "rss" else "public_html"
    if kind == "website" and url.rstrip("/") == ou_festival.SOURCE_URL.rstrip("/"):
        adapter = ou_festival.ADAPTER
    config = {key: getattr(body, key) for key in ("title_selector", "body_selector", "links_selector") if getattr(body, key)}
    return SourceData(name=body.name, url=url, kind=kind, adapter=adapter, config=config)


@router.get("/sources")
def sources(response: Response, repository: Repository = Depends(repository_for)):
    response.headers["Cache-Control"] = "no-store"
    return {"items": repository.list_sources()}


@router.post("/sources", status_code=201)
def add_source(body: SourceInput, repository: Repository = Depends(repository_for)):
    if len(repository.list_sources()) >= 30:
        raise HTTPException(status_code=409, detail="Maksimal 30 sumber pantauan; hapus sumber yang tidak dipakai.")
    try:
        return repository.create_source(normalize_source(body))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Sumber ini sudah terdaftar.") from None
    except (ValueError, FetchError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.patch("/sources/{source_id}")
def enable_source(source_id: int, body: EnabledInput, repository: Repository = Depends(repository_for)):
    try:
        repository.set_source_enabled(source_id, body.enabled)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"ok": True}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, repository: Repository = Depends(repository_for)):
    try:
        repository.delete_source(source_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"ok": True}


@router.get("/preferences")
def preferences(response: Response, repository: Repository = Depends(repository_for)):
    response.headers["Cache-Control"] = "no-store"
    return repository.get_preferences()


@router.put("/preferences")
def save_preferences(body: Preferences, repository: Repository = Depends(repository_for)):
    repository.save_preferences(body)
    return body
