"""Conservative matching; no fuzzy-name merges across years or festival branches."""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..models import CompetitionData


def normalize(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"\bbusiness\s+plan\s+competition\b", "bpc", value)
    value = re.sub(r"\bbusiness\s+case\s+competition\b", "bcc", value)
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def canonical_url(value) -> str:
    parsed = urlsplit(str(value))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    port = parsed.port
    if port and port not in (80, 443):
        host += ":" + str(port)
    query = urlencode(sorted((key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
                             if not key.lower().startswith("utm_") and key.lower() not in ("fbclid", "gclid")))
    # Fragment identifiers can identify separate festival branches. Keep them.
    return host + (parsed.path.rstrip("/") or "/") + ("?" + query if query else "") + ("#" + parsed.fragment if parsed.fragment else "")


def same_competition(left: CompetitionData, right: CompetitionData) -> bool:
    if left.category == "uncertain" or left.category != right.category:
        return False
    if not left.edition or not right.edition or normalize(left.edition) != normalize(right.edition):
        return False
    if normalize(left.name) != normalize(right.name):
        return False
    official = left.official_url and right.official_url and canonical_url(left.official_url) == canonical_url(right.official_url)
    organizer = left.organizer and right.organizer and normalize(left.organizer) == normalize(right.organizer)
    same_page = canonical_url(left.source_url) == canonical_url(right.source_url)
    return bool(official or organizer or same_page)


def storage_key(data: CompetitionData) -> str:
    raw = "|".join((canonical_url(data.source_url), normalize(data.name), data.category, normalize(data.edition)))
    return "observation:" + hashlib.sha256(raw.encode()).hexdigest()
