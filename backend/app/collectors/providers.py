"""Opt-in fixed-endpoint APIs. Credentials never enter URLs, evidence, or errors."""
import hashlib
import http.client
import json
import re
import shutil
import ssl
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from ..config import get_settings
from .http import FetchError, public_url
from .public import Batch, client_for, from_text, parse_html


class ProviderUnavailable(ValueError):
    pass


def request_json(host, path, *, token, payload=None, brave=False):
    connection = http.client.HTTPSConnection(host, timeout=75, context=ssl.create_default_context())
    try:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        headers["X-Subscription-Token" if brave else "Authorization"] = token if brave else "Bearer " + token
        connection.request("POST" if payload is not None else "GET", path,
                           body=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise ValueError(f"Provider merespons HTTP {response.status}; cek credential/kuota di server.")
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Respons provider melebihi batas ukuran.")
        return json.loads(raw)
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        raise ValueError("Koneksi atau respons provider tidak valid; tidak dicoba ulang otomatis.") from None
    finally:
        connection.close()


def ocr_image(url, settings):
    if not settings.ocr_enabled:
        return ""
    command = shutil.which(settings.tesseract_command)
    if command is None:
        raise ProviderUnavailable("OCR belum terhubung: pasang Tesseract dan atur TESSERACT_COMMAND.")
    page = client_for(url).get(url)
    if not page.content_type.lower().startswith(("image/png", "image/jpeg", "image/webp")):
        raise ValueError("Format poster tidak didukung OCR.")
    digest = hashlib.sha256(page.body + settings.ocr_language.encode() + b"ocr-v1").hexdigest()
    cache = settings.resolved_database_path.parent / "ocr-cache"
    cache.mkdir(parents=True, exist_ok=True)
    saved = cache / (digest + ".txt")
    if saved.exists():
        return saved.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        image = Path(folder) / "poster.img"
        image.write_bytes(page.body)
        try:
            result = subprocess.run([command, str(image), "stdout", "-l", settings.ocr_language], capture_output=True,
                                    timeout=25, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (subprocess.SubprocessError, OSError):
            raise ValueError("OCR gagal; periksa poster dan language pack Tesseract.") from None
    text = result.stdout.decode("utf-8", "replace")[:30000]
    temporary = cache / (digest + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(saved)
    return text


def collect_instagram(source, client=None):
    settings = get_settings()
    if not settings.instagram_provider_enabled or not settings.apify_token.get_secret_value():
        raise ProviderUnavailable("Instagram belum terhubung: atur APIFY_TOKEN dan INSTAGRAM_PROVIDER_ENABLED di server.")
    profile = urlsplit(source["source_url"])
    username = profile.path.strip('/')
    if profile.hostname not in ("www.instagram.com", "instagram.com") or not re.fullmatch(r"[\w.]{1,30}", username, re.ASCII):
        raise ValueError("Sumber bukan profil Instagram yang valid.")
    limit = settings.instagram_posts_limit
    posts = request_json("api.apify.com", "/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?" + urlencode({
        "timeout":60, "maxItems":limit, "limit":limit, "maxTotalChargeUsd":settings.apify_max_charge_usd, "restartOnError":"false"}),
        token=settings.apify_token.get_secret_value(), payload={"directUrls":[source["source_url"]], "resultsType":"posts", "resultsLimit":limit})
    if not isinstance(posts, list):
        raise ValueError("Format output Instagram provider berubah.")
    batch = Batch()
    for post in posts[:limit]:
        batch.inspected += 1
        if not isinstance(post, dict) or post.get("error"):
            batch.errors.append("Postingan tidak dapat dibaca provider."); continue
        url = post.get("url", "")
        try:
            public_url(url, frozenset({"www.instagram.com", "instagram.com"}))
        except (FetchError, ValueError, TypeError):
            batch.errors.append("URL postingan provider tidak valid."); continue
        parsed = urlsplit(url)
        if parsed.hostname not in ("www.instagram.com", "instagram.com") or not re.match(r"^/(p|reel)/[\w-]+/?$", parsed.path):
            batch.errors.append("Provider tidak memberikan URL postingan asli yang valid."); continue
        owner = post.get("ownerUsername")
        if not owner or owner.casefold() != username.casefold():
            batch.errors.append("Pemilik postingan tidak cocok dengan akun pantauan."); continue
        caption = post.get("caption") or ""
        if not isinstance(caption, str):
            batch.errors.append("Caption provider tidak valid."); continue
        raw = caption[:30000]
        images = list(dict.fromkeys([post.get("displayUrl")] + (post.get("images") or []) +
                      [child.get("displayUrl") for child in (post.get("childPosts") or []) if isinstance(child, dict)]))
        for image in [image for image in images if isinstance(image, str)][:5]:
            if settings.ocr_enabled:
                try:
                    raw += "\n[OCR poster; perlu dicek]\n" + ocr_image(image, settings)
                except (FetchError, ValueError):
                    batch.errors.append("Poster gagal dibaca OCR; caption tetap diproses.")
        title = next((line for line in raw.splitlines() if re.search(r"hackathon|business (case|plan)|\bBCC\b|\bBPC\b", line, re.I)), raw.splitlines()[0] if raw else "")
        item = from_text(title, raw, url)
        if item:
            item.data.warnings.append("Observasi caption/poster Instagram. Syarat harus dicek di sumber asli." if settings.ocr_enabled else "OCR nonaktif; informasi hanya dari caption, poster belum dibaca.")
            batch.items.append(item)
    return batch


def collect_discovery(source, client=None):
    settings = get_settings()
    if not settings.discovery_provider_enabled or not settings.brave_api_key.get_secret_value():
        raise ProviderUnavailable("Discovery belum terhubung: atur BRAVE_API_KEY dan DISCOVERY_PROVIDER_ENABLED di server.")
    batch, seen = Batch(), set()
    queries = ["hackathon Indonesia mahasiswa pendaftaran", "business case competition Indonesia registration", "lomba business plan mahasiswa Indonesia pendaftaran"]
    for index, query in enumerate(queries):
        if index:
            time.sleep(1.1)
        result = request_json("api.search.brave.com", "/res/v1/web/search?" + urlencode({"q":query,"country":"ID","search_lang":"id","count":5}),
                              token=settings.brave_api_key.get_secret_value(), brave=True)
        if not isinstance(result, dict):
            raise ValueError("Format respons search provider tidak valid.")
        for hit in result.get("web", {}).get("results", [])[:5]:
            url = hit.get("url", "")
            if url in seen or len(seen) >= 10:
                continue
            seen.add(url); batch.inspected += 1
            candidate = {"url":url, "title":str(hit.get("title", ""))[:300], "status":"unverified", "reason":None}
            try:
                host = urlsplit(url).hostname
                public_url(url, frozenset({host}))
                item = parse_html(client_for(url).get(url))
                candidate["status"] = "verified" if item else "irrelevant"
                if item:
                    batch.items.append(item)
            except (FetchError, ValueError):
                candidate.update(status="failed", reason="Halaman asli tidak dapat diverifikasi; hasil pencarian hanya kandidat.")
            batch.candidates.append(candidate)
    return batch
