"""Explainable Indonesia/student/category and registration filters, evaluated at read time too."""

import re
from datetime import datetime, time, timezone

from ..models import CompetitionData, Preferences
from .dates import deadline_passed, timezone_for


def registration_status(data: CompetitionData, now: datetime) -> str:
    asserted = data.registration_status if data.registration_status_origin != "timeline" else "unknown"
    if asserted == "closed":
        return "closed"
    entries = [item for item in data.timeline if item.kind == "registration"]
    if not entries:
        return asserted
    states = [deadline_passed(item, now) for item in entries]
    if states and all(state is True for state in states):
        return "closed"
    for entry, passed in zip(entries, states):
        tz = timezone_for(entry.timezone)
        if passed is False and entry.start_date and tz:
            start = entry.start_at or datetime.combine(entry.start_date, time.min, tzinfo=tz)
            if now >= start:
                return "open"
    starts = [item.start_at or datetime.combine(item.start_date, time.min, tzinfo=timezone_for(item.timezone))
              for item in entries if item.start_date and timezone_for(item.timezone) and not item.needs_review]
    if len(starts) == len(entries) and all(now < start for start in starts):
        return "upcoming"
    return asserted


def evaluate(data: CompetitionData, preferences: Preferences, *, now: datetime | None = None) -> CompetitionData:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Waktu evaluasi harus menyertakan zona waktu.")
    result = data.model_copy(deep=True)
    reasons = []; uncertain = []
    uncertain.extend(warning for warning in data.warnings if warning.startswith('[Perlu review ekstraksi]'))
    registration = registration_status(data, now)
    result.registration_status = registration
    asserted = data.registration_status if data.registration_status_origin != "timeline" else "unknown"
    result.registration_status_origin = "timeline" if registration != asserted else "source" if asserted != "unknown" else "unknown"
    name = data.name.casefold()
    kind = data.content_kind
    if kind in ("unknown", "competition"):
        if re.search(r"^(?:\[[^]]*\]\s*)?(?:webinar|seminar|workshop|kelas|course|lowongan|job vacancy|internship)\b", name):
            kind = "seminar"
        elif re.search(r"pengumuman (?:pemenang|juara)|winners? announcement|congratulations|selamat.{0,60}(?:juara|pemenang)", name):
            kind = "winner_announcement"
    if kind in ("seminar", "webinar", "course", "job"):
        reasons.append("Konten berupa seminar, kelas, atau lowongan, bukan pendaftaran lomba.")
    if kind == "winner_announcement":
        has_new_registration = registration in ("open", "upcoming") and any(
            entry.kind == "registration" and deadline_passed(entry, now) is False for entry in data.timeline)
        if not has_new_registration:
            reasons.append("Pengumuman pemenang tanpa bukti pendaftaran baru.")
    if data.category == "uncertain":
        if re.search(r"\blomba (?:fotografi|foto|poster|puisi|esai|essay)\b|\b(?:photo|poster|poetry|essay) competition\b", name):
            reasons.append("Lomba di luar kategori hackathon, BCC, dan BPC.")
        else:
            uncertain.append("Kategori lomba perlu dicek.")
    elif data.category not in preferences.categories:
        reasons.append("Kategori lomba di luar preferensi.")
    country = (data.country or "").casefold().strip()
    if data.scope == "international" or country not in ("", "id", "idn", "indonesia"):
        reasons.append("Lomba di luar cakupan Indonesia.")
    elif not country and data.scope != "indonesia":
        uncertain.append("Cakupan Indonesia belum terverifikasi.")
    eligibility = data.eligibility or ""
    college = bool(re.search(r"\bmahasiswa|\bundergraduate|university students?|college students?|\bD[134]\b|\bS[12]\b", eligibility, re.I))
    school = bool(re.search(r"\bSMA\b|\bSMK\b|\bSMP\b|high school|secondary school", eligibility, re.I))
    denied = bool(re.search(r"(?:tidak (?:menerima|untuk)|bukan untuk|not (?:open|available) to)\s+(?:para )?(?:mahasiswa|university students|college students)", eligibility, re.I))
    restricted_country = re.search(r"(?:khusus|only|must be).{0,30}(?:US citizens|Singapore citizens|warga negara (?!Indonesia)[A-Za-z]+)", eligibility, re.I)
    if restricted_country:
        reasons.append("Persyaratan kewarganegaraan tidak cocok untuk peserta Indonesia.")
    if preferences.education_level == "university" and (denied or (school and not college)):
        reasons.append("Lomba khusus pelajar atau tidak menerima mahasiswa.")
    elif not eligibility or (preferences.education_level == "university" and not college):
        uncertain.append("Syarat peserta perlu dicek.")
    if re.search(r"khusus.{0,30}(?:jurusan|program studi)|only.{0,30}(?:major|department)", eligibility, re.I):
        uncertain.append("Pembatasan jurusan perlu dicocokkan dengan profil pengguna.")
    if re.search(r"khusus.{0,40}(?:universitas|perguruan tinggi|kampus|domisili|wilayah)|only.{0,30}(?:residents|university of)", eligibility, re.I):
        uncertain.append("Pembatasan institusi atau wilayah peserta perlu dicek.")
    if any(entry.needs_review for entry in data.timeline):
        uncertain.append("Ada tanggal ambigu; teks asli perlu dicek.")
    active_conflicts = [conflict for conflict in data.conflicts if conflict.get("status", "unresolved") == "unresolved"]
    if active_conflicts:
        uncertain.append("Ada konflik informasi sumber yang belum terselesaikan.")
    finals = [entry for entry in data.timeline if entry.kind in ("event", "final")]
    finals_passed = finals and all(deadline_passed(entry, now) is True for entry in finals)
    if finals_passed:
        disputed_final = any(item.get("field", "").startswith(("timeline:final", "timeline:event")) for item in active_conflicts)
        if registration in ("open", "upcoming") or disputed_final:
            uncertain.append("Jadwal pendaftaran bertentangan dengan tanggal pelaksanaan yang sudah lewat.")
        else:
            reasons.append("Lomba sudah selesai.")
    if preferences.hide_closed and registration == "closed":
        disputed_registration = any(item.get("field", "").startswith("timeline:registration") or item.get("field") == "registration_status" for item in active_conflicts)
        if disputed_registration:
            uncertain.append("Status tutup masih diperselisihkan oleh sumber lain.")
        else:
            reasons.append("Pendaftaran sudah ditutup.")
    if uncertain and not preferences.include_unknown_eligibility and any("peserta" in item or "Cakupan" in item or "jurusan" in item for item in uncertain):
        reasons.append("Informasi kelayakan belum jelas dan preferensi menyembunyikannya.")
    result.relevance_status = "excluded" if reasons else "needs_review" if uncertain else "relevant"
    result.relevance_reasons = list(dict.fromkeys(reasons + uncertain))
    return result
