"""Merge observations without replacing confirmed fields with ambiguity or conflicting sources."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..models import CompetitionData, EvidenceData, TimelineEntry
from .identity import canonical_url, normalize
from .dates import timezone_for

METADATA = {"source_url", "warnings", "conflicts", "field_provenance", "relevance_status", "relevance_reasons", "registration_status", "registration_status_origin"}


def timeline_key(entry: TimelineEntry) -> str:
    identity = entry.phase_id or normalize(entry.label)
    return "timeline:" + entry.kind + ":" + (identity or "unlabelled:" + hashlib.sha256(entry.raw_text.encode()).hexdigest()[:16])


def known(value: Any) -> bool:
    return value not in (None, "", "unknown", "uncertain", [], {})


def provenance(evidence: EvidenceData, field: str) -> dict:
    return {"url": str(evidence.url), "content_hash": evidence.content_hash,
            "quote": evidence.field_values.get(field) or evidence.field_values.get(field.split(":")[0])}


def conflict_id(field: str, origin: dict, evidence: EvidenceData) -> str:
    raw = json.dumps([field, origin.get("url"), str(evidence.url), evidence.content_hash], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def merge(previous: CompetitionData | None, incoming: CompetitionData, evidence: EvidenceData) -> CompetitionData:
    if previous is None:
        result = incoming.model_copy(deep=True)
        result.conflicts = []
        result.field_provenance = {field: provenance(evidence, field) for field, value in incoming.model_dump(mode="json").items()
                                   if field not in METADATA and field != "timeline" and known(value)}
        for index, entry in enumerate(incoming.timeline):
            result.field_provenance[timeline_key(entry)] = provenance(evidence, f"timeline.{index}")
        return result
    result = previous.model_dump(mode="json")
    conflicts = deepcopy(previous.conflicts)
    origins = deepcopy(previous.field_provenance)
    fallback = {"url": str(previous.source_url), "content_hash": None, "quote": None}

    def consider(field: str, old: Any, new: Any, *, uncertain: bool = False, quote_field: str | None = None):
        origin = origins.get(field, fallback)
        if not known(old) and not known(new):
            return old
        same_source = canonical_url(origin["url"]) == canonical_url(evidence.url) or canonical_url(previous.source_url) == canonical_url(evidence.url)
        # Raw date wording can differ without changing the asserted date/time.
        def semantic(value):
            if field.startswith("timeline:") and isinstance(value, dict):
                if value.get("at"):
                    return {"at": datetime.fromisoformat(value["at"]).astimezone(timezone.utc).isoformat(),
                            "start_date": value.get("start_date"),
                            "start_at": datetime.fromisoformat(value["start_at"]).astimezone(timezone.utc).isoformat() if value.get("start_at") else None,
                            "time_precision": value.get("time_precision"),
                            "needs_review": value.get("needs_review")}
                tz = timezone_for(value.get("timezone"))
                fields = {key: value.get(key) for key in ("date", "at", "start_date", "start_at", "timezone", "needs_review")}
                fields["timezone"] = str(tz.utcoffset(None)) if tz else value.get("timezone")
                return fields
            return normalize(value) if field in ("name", "organizer", "edition") and isinstance(value, str) else value
        equivalent = semantic(old) == semantic(new)
        if equivalent:
            # Agreement from the formerly conflicting source resolves that conflict without deleting it.
            for item in conflicts:
                if item.get("field") == field and item.get("status", "unresolved") == "unresolved" and canonical_url(item["observed_source"]) == canonical_url(evidence.url):
                    item["status"] = "resolved"; item["resolved_by_hash"] = evidence.content_hash
            if same_source:
                origins[field] = provenance(evidence, quote_field or field)
                return new
            return old
        if not known(new) and not uncertain:
            return old  # Omitted information is not contradictory evidence.
        if not known(old) and known(new):
            origins[field] = provenance(evidence, quote_field or field)
            return new
        if known(old) and (uncertain or not known(new) or not same_source):
            identity = conflict_id(field, origin, evidence)
            if not any(item.get("id") == identity for item in conflicts):
                conflicts.append({"id": identity, "field": field, "kept": old, "observed": new,
                                  "kept_source": origin["url"], "observed_source": str(evidence.url),
                                  "evidence_hash": evidence.content_hash, "status": "unresolved",
                                  "reason": "uncertain_or_missing" if uncertain or not known(new) else "sources_disagree"})
            return old
        origins[field] = provenance(evidence, quote_field or field)
        # A primary source can supersede its own previous precise information. History retains it.
        for item in conflicts:
            if item.get("field") == field and item.get("status", "unresolved") == "unresolved" and semantic(item.get("observed")) == semantic(new):
                item["status"] = "resolved"; item["resolved_by_hash"] = evidence.content_hash
        return new

    old_dump, new_dump = previous.model_dump(mode="json"), incoming.model_dump(mode="json")
    for field in new_dump:
        if field in METADATA or field == "timeline":
            continue
        uncertain_fee = field == "fees" and new_dump[field] and all(item.get("amount") is None for item in new_dump[field]) and any(item.get("amount") is not None for item in old_dump[field])
        value = consider(field, old_dump[field], new_dump[field], uncertain=bool(uncertain_fee))
        result[field] = value
    # Revalidate at the end, because considered values above use JSON representations.
    entries = {timeline_key(entry): entry for entry in previous.timeline}
    for index, entry in enumerate(incoming.timeline):
        key = timeline_key(entry)
        old_entry = entries.get(key)
        if old_entry:
            old_precise = not old_entry.needs_review and (old_entry.date is not None or old_entry.at is not None)
            new_precise = not entry.needs_review and (entry.date is not None or entry.at is not None)
            if new_precise and not old_precise:
                value = entry.model_dump(mode="json")
                origins[key] = provenance(evidence, f"timeline.{index}")
            elif old_entry.at is not None and entry.at is None and old_entry.date == entry.date and not entry.needs_review:
                value = old_entry.model_dump(mode="json")
            else:
                value = consider(key, old_entry.model_dump(mode="json"), entry.model_dump(mode="json"),
                                 uncertain=bool(old_precise and not new_precise), quote_field=f"timeline.{index}")
            entries[key] = TimelineEntry.model_validate(value)
        else:
            entries[key] = entry
            origins[key] = provenance(evidence, f"timeline.{index}")
    result["timeline"] = [entry.model_dump(mode="json") for entry in entries.values()]
    result["conflicts"] = conflicts
    result["warnings"] = list(dict.fromkeys(previous.warnings + incoming.warnings))
    # An explicit status disagreement should be visible too; inference is evaluated separately.
    if incoming.registration_status != "unknown":
        previous_asserted = previous.registration_status if previous.registration_status_origin != "timeline" else "unknown"
        result["registration_status"] = consider("registration_status", previous_asserted, incoming.registration_status)
        result["registration_status_origin"] = "source"
    result["field_provenance"] = origins
    return CompetitionData.model_validate(result)
