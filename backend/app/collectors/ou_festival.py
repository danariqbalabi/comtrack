"""Source-specific extraction of the public EPIC dossier; no festival-wide guesses."""

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..models import CompetitionData, Money, TimelineEntry
from ..quality.dates import MONTHS, parse_timeline
from .http import Page, PublicClient

SOURCE_URL = "https://ou-festival.com/"
SOURCE_NAME = "OU Festival · EPIC Business Plan"
ADAPTER = "ou_festival_epic"
ALLOWED_HOSTS = frozenset({"ou-festival.com", "www.ou-festival.com"})


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedCompetition:
    data: CompetitionData
    dedup_key: str
    raw_text: str
    content_hash: str
    field_values: dict[str, str]


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def extract(page: Page) -> ExtractedCompetition:
    if "text/html" not in page.content_type.lower():
        raise ExtractionError("Sumber tidak mengembalikan HTML.")
    soup = BeautifulSoup(page.body, "html.parser")
    for element in soup.select("script, style, noscript, svg"):
        element.decompose()
    panel = soup.select_one("#berkas-epic")
    title = soup.find("title")
    heading = soup.find("h1")
    about = soup.select_one("#tentang")
    footer = soup.find("footer")
    if panel is None or title is None or heading is None or about is None:
        raise ExtractionError("Struktur OU Festival berubah: berkas EPIC atau identitas festival tidak ditemukan.")
    title_text = text(title)
    edition = re.search(r"OU Festival\s+(\d+)\s+(20\d{2}/20\d{2})\b", title_text)
    if not edition or "Olimpiade Update" not in text(heading):
        raise ExtractionError("Edisi atau penyelenggara OU Festival tidak dapat diverifikasi.")
    if not panel.find("h3") or text(panel.find("h3")) != "EPIC" or "kompetisi rencana bisnis" not in text(panel).lower():
        raise ExtractionError("Berkas EPIC bukan kompetisi rencana bisnis yang dikenali.")
    facts = {}
    for label in panel.select("dl dt"):
        value = label.find_next_sibling("dd")
        if value:
            facts[text(label)] = text(value)
    if not all(facts.get(key) for key in ("Jenjang", "Peserta", "Pendaftaran", "Biaya")):
        raise ExtractionError("Fakta utama EPIC tidak lengkap; data lama tidak diganti.")
    if "mahasiswa" not in facts["Jenjang"].lower() or "nasional" not in text(about).lower():
        raise ExtractionError("Cakupan nasional atau kelayakan mahasiswa tidak ditemukan.")
    timezone = "WIB" if footer and "tanggal" in text(footer).lower() and "WIB" in text(footer) else None
    registration_entry = parse_timeline(facts["Pendaftaran"], kind="registration", label="Batas pendaftaran EPIC", timezone_hint=timezone)
    fields = {
        "name": "EPIC — " + title_text,
        "category": next(text(node) for node in panel.find_all("p") if "kompetisi rencana bisnis" in text(node).lower()),
        "organizer": text(heading), "edition": title_text,
        "eligibility": facts["Jenjang"] + ". " + facts["Peserta"],
        "fees": facts["Biaya"], "timeline.0": facts["Pendaftaran"],
        "scope": text(about), "content_kind": text(panel.find("h3")),
    }
    if timezone:
        fields["timezone"] = text(footer)
    timeline = [registration_entry]
    warnings = ["Syarat rinci, domisili peserta, serta basis biaya per orang/per tim perlu dicek di juknis."]
    team = re.search(r"\b(\d+)\s*[–-]\s*(\d+)\s+orang\b", facts["Peserta"])
    fees = []
    if "BMC gratis" in facts["Biaya"]:
        fees.append(Money(amount=Decimal(0), raw_text=facts["Biaya"]))
    # Preserve conditions and periods alongside each amount. Do not assume per-team billing.
    for match in re.finditer(r"Rp\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:\s*\([^)]*\))?", facts["Biaya"]):
        fees.append(Money(amount=Decimal(match[1].replace(".", "")), currency="IDR", raw_text=facts["Biaya"]))
    if not fees:
        fees.append(Money(raw_text=facts["Biaya"]))
    final_online = False
    for step in panel.select("ol > li"):
        parts = step.select("div > p")
        if len(parts) < 2:
            continue
        label, raw_date = text(parts[0]), text(parts[1])
        description = " ".join(text(part) for part in parts[2:])
        kind = "submission" if label in ("Seleksi BMC", "Proposal lengkap") else "final" if label == "Presentasi final" else "other"
        parsed = parse_timeline(raw_date, kind=kind, label=label, timezone_hint=timezone)
        parsed_date = parsed.date
        if kind == "final":
            # Pick the university date only when the prose confirms the dated endpoint.
            student_day = re.search(r"mahasiswa pada\s+(\d{1,2})\s+(\w+)", description, re.I)
            if not student_day or not parsed_date or int(student_day[1]) != parsed_date.day or MONTHS.get(student_day[2].lower()) != parsed_date.month:
                parsed_date = None
            else:
                label += " mahasiswa"
            final_online = "Zoom" in description
        entry = TimelineEntry(kind=kind, label=label, raw_text=raw_date + ". " + description,
                              date=parsed_date, start_date=parsed.start_date if kind != "final" else None,
                              at=parsed.at, timezone=parsed.timezone, needs_review=parsed_date is None or parsed.needs_review)
        fields[f"timeline.{len(timeline)}"] = label + ": " + entry.raw_text
        timeline.append(entry)
    if any(entry.needs_review for entry in timeline):
        warnings.append("Ada tanggal yang belum dapat dipastikan; teks asli disimpan.")
    guidebook = None
    registration = None
    for anchor in panel.select("a[href]"):
        label = text(anchor).lower()
        target = urljoin(page.url, anchor["href"])
        parsed = urlsplit(target)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            continue
        if "juknis" in label:
            guidebook = target
            fields["guidebook_url"] = target
        elif label == "lihat lomba" and parsed.hostname in ALLOWED_HOSTS:
            registration = target
            fields["registration_url"] = target
    if registration:
        warnings.append("Halaman pendaftaran memerlukan akun; tanggal pada halaman detail terpisah belum diverifikasi.")
    if guidebook:
        warnings.append("Tautan juknis ditemukan di sumber; isi dokumennya belum diambil.")
    # Source provides national scope and WIB, but not an explicit country/venue field.
    # Do not turn that context into a fabricated venue or nationality restriction.
    data = CompetitionData(
        name=f"EPIC — OU Festival {edition[1]} ({edition[2]})", category="BPC", organizer="Olimpiade Update",
        edition=f"{edition[1]} / {edition[2]}", summary="Kompetisi rencana bisnis tingkat nasional OU Festival untuk SMA dan mahasiswa. Peserta membentuk tim dari sekolah atau kampus yang sama; biaya proposal berlaku jika lolos seleksi BMC.",
        eligibility=fields["eligibility"], team_min=int(team[1]) if team else None,
        team_max=int(team[2]) if team else None, team_raw=facts["Peserta"],
        format="online" if final_online else "unknown", fees=fees, timeline=timeline,
        source_url=page.url + "#berkas-epic", official_url=page.url + "#berkas-epic",
        registration_url=registration, guidebook_url=guidebook, relevance_status="needs_review",
        registration_status="unknown", scope="indonesia", content_kind="competition", warnings=warnings,
    )
    if final_online:
        fields["format"] = next(entry.raw_text for entry in timeline if entry.kind == "final")
    # Keep a stable relevant snapshot; navigation, scripts, countdowns, and unrelated branches are excluded.
    snapshot = title_text + "\n" + text(heading) + "\n" + text(panel) + "\n"
    snapshot += "\n".join(f"{key}: {value}" for key, value in sorted(fields.items()))
    return ExtractedCompetition(data=data, dedup_key=f"ou-festival:epic:bpc:{edition[1]}:{edition[2]}",
                                raw_text=snapshot, content_hash=hashlib.sha256(snapshot.encode()).hexdigest(), field_values=fields)


def collect(client: PublicClient | None = None) -> ExtractedCompetition:
    client = client or PublicClient(ALLOWED_HOSTS)
    return extract(client.get(SOURCE_URL))
