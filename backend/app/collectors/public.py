"""Bounded RSS/Atom and configurable HTML extraction. No guessed facts."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from ..models import CompetitionData, Money
from ..quality.dates import MONTHS, parse_timeline
from .http import PublicClient, FetchError
from .ou_festival import ExtractedCompetition


@dataclass
class Batch:
    items: list[ExtractedCompetition] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    inspected: int = 0
    candidates: list[dict] = field(default_factory=list)


def from_text(title, raw, url):
    title = re.sub(r"\s+", " ", title).strip()[:300]
    raw = raw.strip()[:30000]
    categories = []
    for category, pattern in (("hackathon", r"\bhackathon\b"), ("BCC", r"\b(bcc|business case|case competition|kompetisi kasus bisnis)\b"), ("BPC", r"\b(bpc|business plan|business model|rencana bisnis|rencana usaha)\b")):
        if re.search(pattern, title + "\n" + raw, re.I):
            categories.append(category)
    if not categories or not title:
        return None
    category = categories[0] if len(categories) == 1 else "uncertain"
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    timeline, fees = [], []
    for index, line in enumerate(lines):
        if re.search(r"pendaftaran|registrasi|registration|submission|pengumpulan|deadline|final", line, re.I):
            kind = "registration" if re.search(r"pendaftaran|registrasi|registration", line, re.I) else "submission" if re.search(r"submission|pengumpulan", line, re.I) else "final" if re.search(r"\bfinal\b", line, re.I) else "other"
            context = line if re.search(r"\b20\d{2}\b", line) else " ".join(lines[index:index + 3])
            month_pattern = r"\b(?:" + "|".join(MONTHS) + r")\b"
            date_hint = re.search(month_pattern, context, re.I) or re.search(r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b", context)
            if date_hint or re.search(r"\b(TBA|menyusul)\b", line, re.I):
                if kind == "registration" and re.search(r"dibuka|opens?|starts?", line, re.I) and not re.search(r"ditutup|closed?|hingga|sampai", line, re.I):
                    kind = "other"  # An opening date is not the registration deadline.
                timeline.append(parse_timeline(context[:1000], kind=kind, label=line[:150]))
        if re.search(r"\b(biaya|gratis|free|investment|registration fee)\b", line, re.I):
            fees.append(Money(raw_text=line[:1000]))
    years = re.findall(r"\b20\d{2}\b", title)
    eligibility = next((line for line in lines if re.search(r"mahasiswa|undergraduate|student|peserta|eligibility", line, re.I)), None)
    data = CompetitionData(name=title, category=category, edition=years[0] if len(set(years)) == 1 else None,
        summary=raw[:700] or None, eligibility=eligibility, timeline=timeline[:20], fees=fees[:10], source_url=url,
        scope="international" if re.search(r"\b(international|internasional)\b", title, re.I) else "indonesia" if re.search(r"\b(indonesia|nasional)\b", raw, re.I) else "unknown",
        content_kind="competition" if re.search(r"lomba|kompetisi|competition|hackathon", title, re.I) else "unknown",
        warnings=["Ekstraksi konservatif dari teks publik; periksa ketentuan dan poster pada sumber asli."])
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return ExtractedCompetition(data, "", raw, digest, {"name": title, "timeline": "\n".join(entry.raw_text for entry in timeline), "fees": "\n".join(fee.raw_text for fee in fees)})


def client_for(url):
    host = urlsplit(url).hostname
    aliases = {host, host[4:] if host.startswith("www.") else "www." + host}
    return PublicClient(frozenset(aliases))


def parse_html(page, config=None):
    config = config or {}
    if "html" not in page.content_type.lower():
        raise ValueError("Halaman bukan HTML publik.")
    soup = BeautifulSoup(page.body, "html.parser")
    for node in soup.select("script,style,noscript,nav,footer,header,form,svg"):
        node.decompose()
    try:
        title = soup.select_one(config.get("title_selector") or "h1")
        body = soup.select_one(config.get("body_selector") or "article, .entry-content, .post-body, main")
    except Exception:
        raise ValueError("Selector CSS tidak valid.") from None
    if title is None or body is None:
        raise ValueError("Judul/isi artikel tidak ditemukan. Atur selector CSS atau gunakan URL artikel.")
    return from_text(title.get_text(" ", strip=True), body.get_text("\n", strip=True), page.url)


def collect_html(source, client=None):
    config = json.loads(source["config_json"])
    url = source["source_url"]
    client = client or client_for(url)
    page = client.get(url)
    if not config.get("links_selector"):
        item = parse_html(page, config)
        return Batch([item] if item else [], inspected=1)
    soup = BeautifulSoup(page.body, "html.parser")
    try:
        nodes = soup.select(config["links_selector"])
    except Exception:
        raise ValueError("Selector link tidak valid.") from None
    if not nodes:
        raise ValueError("Link artikel tidak ditemukan; struktur daftar mungkin berubah.")
    batch = Batch()
    urls = list(dict.fromkeys(urljoin(page.url, node.get("href", "")) for node in nodes if node.get("href")))[:10]
    for target in urls:
        batch.inspected += 1
        try:
            item = parse_html(client.get(target), config)
            if item:
                batch.items.append(item)
        except (FetchError, ValueError):
            batch.errors.append("Satu artikel gagal diambil atau strukturnya tidak terbaca.")
    return batch


def collect_rss(source, client=None):
    client = client or client_for(source["source_url"])
    page = client.get(source["source_url"])
    # Reject DTD/entity declarations before stdlib XML parsing.
    if re.search(br"<!\s*(DOCTYPE|ENTITY)", page.body, re.I):
        raise ValueError("Feed XML dengan DTD/entity tidak didukung.")
    try:
        root = ET.fromstring(page.body)
    except ET.ParseError:
        raise ValueError("RSS/Atom tidak valid.") from None
    if root.tag.rsplit('}', 1)[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("URL tidak mengembalikan RSS/Atom.")
    entries = root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
    batch = Batch()
    for entry in entries[:10]:
        fields = {child.tag.rsplit('}', 1)[-1]: child for child in entry}
        title = fields.get('title')
        link = fields.get('link')
        if title is None or link is None:
            continue
        target = urljoin(page.url, link.get('href') or link.text or '')
        body = '\n'.join(''.join(node.itertext()) for key, node in fields.items() if key in ('description', 'encoded', 'content', 'summary'))
        raw = BeautifulSoup(body, 'html.parser').get_text('\n', strip=True)
        if from_text(''.join(title.itertext()), raw, target) is None:
            continue
        batch.inspected += 1
        try:
            item = parse_html(client.get(target))  # The feed only identifies candidates; verify original article.
            if item:
                batch.items.append(item)
        except (FetchError, ValueError):
            batch.errors.append('Artikel dari feed gagal diverifikasi; tidak disimpan sebagai lomba terverifikasi.')
    return batch
