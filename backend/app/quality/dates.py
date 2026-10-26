"""Conservative Indonesian/English dates with explicit years and optional explicit times."""

import re
from datetime import date, datetime, timedelta, timezone

from ..models import TimelineEntry

MONTHS = {}
for number, names in enumerate((
    "januari january jan", "februari february feb", "maret march mar", "april apr", "mei may",
    "juni june jun", "juli july jul", "agustus august agu agt aug", "september sep sept",
    "oktober october okt oct", "november nov", "desember december des dec",
), 1):
    MONTHS.update({name: number for name in names.split()})
MONTH_PATTERN = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
DAY = r"\d{1,2}(?:st|nd|rd|th)?"
NAMED = rf"(?P<day>{DAY})\s+(?P<month>{MONTH_PATTERN})\s*,?\s*(?P<year>20\d{{2}})"
ENGLISH = rf"(?P<month>{MONTH_PATTERN})\s+(?P<day>{DAY}),?\s+(?P<year>20\d{{2}})"
ISO = r"(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})"


def timezone_for(label: str | None):
    if not label:
        return None
    normalized = label.upper().replace(" ", "")
    offsets = {"WIB": 7, "WITA": 8, "WIT": 9, "UTC": 0, "GMT": 0,
               "ASIA/JAKARTA": 7, "ASIA/MAKASSAR": 8, "ASIA/JAYAPURA": 9}
    if normalized in offsets:
        return timezone(timedelta(hours=offsets[normalized]))
    match = re.fullmatch(r"(?:UTC|GMT)([+-])(\d{1,2})(?::?(\d{2}))?", normalized)
    if match:
        hours, minutes = int(match[2]), int(match[3] or 0)
        if hours <= 14 and minutes < 60 and (hours < 14 or minutes == 0):
            return timezone((1 if match[1] == "+" else -1) * timedelta(hours=hours, minutes=minutes))
    return None


def _date(match) -> date:
    groups = match.groupdict()
    day = int(re.sub(r"\D", "", groups["day"]))
    month_text = groups["month"].lower()
    month = int(month_text) if month_text.isdigit() else MONTHS[month_text]
    return date(int(groups["year"]), month, day)


def parse_timeline(raw: str, *, kind="other", label: str | None = None,
                   timezone_hint: str | None = None, phase_id: str | None = None) -> TimelineEntry:
    entry = TimelineEntry(kind=kind, label=label, raw_text=raw, phase_id=phase_id)
    normalized = re.sub(r"\s+", " ", raw).strip()
    tz_match = re.search(r"\b(?:WITA|WIB|WIT|(?:UTC|GMT)(?:\s*[+-]\d{1,2}(?::?\d{2})?)?)\b", normalized, re.I)
    tz_label = tz_match[0].upper() if tz_match else timezone_hint
    entry.timezone = tz_label
    # Numeric slash/dot dates, relative dates and multiple alternatives are deliberately unresolved.
    if re.search(r"\b\d{1,2}[/.]\d{1,2}[/.](?:20)?\d{2}\b|\b(?:atau|or)\b", normalized, re.I):
        return entry
    pattern = rf"(?<!\w)(?:{NAMED})(?!\w)"
    matches = list(re.finditer(pattern, normalized, re.I))
    if not matches:
        matches = list(re.finditer(rf"(?<!\w)(?:{ENGLISH})(?!\w)", normalized, re.I))
    if not matches:
        matches = list(re.finditer(rf"(?<!\d){ISO}(?!\d)", normalized))
    if not matches or len(matches) > 2:
        return entry
    try:
        if len(matches) == 2:
            between = normalized[matches[0].end():matches[1].start()].strip()
            if between.lower() not in ("-", "–", "—", "s/d", "s.d.", "sampai", "hingga", "to"):
                return entry
            start, end = _date(matches[0]), _date(matches[1])
            if start > end:
                return entry
            entry.start_date, entry.date = start, end
        else:
            match = matches[0]
            entry.date = _date(match)
            prefix = normalized[:match.start()]
            # Shared month/year within an explicit range, e.g. 1–22 November 2030.
            short = re.search(rf"(?<!\d)(?P<start>\d{{1,2}})\s*(?:-|–|—|s/d|hingga|sampai|to)\s*$", prefix, re.I)
            cross_month = re.search(rf"(?<!\d)(?P<start>\d{{1,2}})\s+(?P<month>{MONTH_PATTERN})\s*(?:-|–|—|s/d|hingga|sampai|to)\s*$", prefix, re.I)
            if short:
                entry.start_date = date(entry.date.year, entry.date.month, int(short["start"]))
            elif cross_month:
                month = MONTHS[cross_month["month"].lower()]
                # Dec–Jan without a start year does not justify inventing a previous year.
                if month <= entry.date.month:
                    entry.start_date = date(entry.date.year, month, int(cross_month["start"]))
            if entry.start_date and entry.start_date > entry.date:
                entry.date = entry.start_date = None
                return entry
        # A time is accepted only when one date and one explicit time are present.
        # Date ranges with times need separate start/end evidence and remain date-only for now.
        tail = normalized[matches[-1].end():]
        time_match = re.match(r"(?:T|\s+(?:pukul\s+|at\s+|jam\s+)?)(\d{1,2})[:.](\d{2})(?::(\d{2})(?:\.\d+)?)?", tail, re.I)
        if (len(matches) == 2 or entry.start_date is not None) and re.search(r"\d{1,2}[:.]\d{2}", normalized):
            return entry  # Ranges with explicit times need separate start/end evidence.
        if not time_match and re.search(r"\b(?:pukul|jam|at)\s+\d", tail, re.I):
            return entry
        if time_match and entry.start_date is None:
            hour, minute, second = int(time_match[1]), int(time_match[2]), int(time_match[3] or 0)
            if hour > 23 or minute > 59 or second > 59:
                entry.date = None
                return entry
            tz = timezone_for(tz_label)
            offset = re.match(r"(?:Z|[+-]\d{2}:\d{2})", tail[time_match.end():])
            if offset:
                iso_offset = "+00:00" if offset[0] == "Z" else offset[0]
                entry.at = datetime.fromisoformat(f"{entry.date.isoformat()}T{hour:02}:{minute:02}:{second:02}{iso_offset}")
                entry.timezone = "UTC" if offset[0] == "Z" else "UTC" + offset[0]
            elif tz:
                entry.at = datetime(entry.date.year, entry.date.month, entry.date.day, hour, minute, second, tzinfo=tz)
            else:
                return entry  # Time supplied without timezone: do not silently turn it into midnight/date-only.
            entry.time_precision = "second" if time_match[3] is not None else "minute"
        entry.needs_review = False
        return entry
    except (ValueError, KeyError):
        entry.date = entry.start_date = None
        entry.at = entry.start_at = None
        return entry


def deadline_passed(entry: TimelineEntry, now: datetime) -> bool | None:
    if entry.needs_review:
        return None
    if entry.at is not None:
        if entry.time_precision == "minute":
            return now >= entry.at + timedelta(minutes=1)
        return now > entry.at
    if entry.date is None:
        return None
    # An unknown zone is closed only after the date has ended everywhere (UTC−12).
    tz = timezone_for(entry.timezone) or timezone(timedelta(hours=-12))
    end = datetime.combine(entry.date + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return now >= end
