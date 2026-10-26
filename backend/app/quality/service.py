"""One atomic match → merge → evaluate → save transaction for an observation."""

from datetime import datetime, timezone

from ..models import CompetitionData, EvidenceData, Preferences
from ..repository import Repository, competition_record
from .identity import canonical_url, same_competition, storage_key
from .merge import merge, timeline_key
from .prepare import prepare
from .relevance import evaluate


def ingest(repository: Repository, data: CompetitionData, evidence: EvidenceData, *,
           adapter_key: str | None = None, now: datetime | None = None, guard=None):
    now = now or datetime.now(timezone.utc)
    data = prepare(data)
    if canonical_url(data.source_url) != canonical_url(evidence.url):
        raise ValueError("URL bukti harus sesuai dengan URL sumber observasi.")
    snapshot = data.model_dump(mode="json", exclude={"field_provenance", "conflicts", "relevance_reasons"})
    evidence = evidence.model_copy(update={"field_values": {**evidence.field_values, "_observation": snapshot}})
    key = adapter_key or storage_key(data)
    with repository.database.transaction() as conn:
        if guard is not None:
            guard(conn)
        preferences = Preferences.model_validate_json(conn.execute("SELECT data_json FROM preferences WHERE singleton = 1").fetchone()[0])
        row = conn.execute("SELECT * FROM competitions WHERE dedup_key = ?", (key,)).fetchone()
        if row:
            candidate = competition_record(row)
            if candidate.data.category != data.category or candidate.data.edition != data.edition:
                raise ValueError("Identitas adapter bertabrakan dengan kategori/edisi berbeda; penggabungan ditolak.")
            previous = candidate
        else:
            matches = [competition_record(row) for row in conn.execute("SELECT * FROM competitions WHERE category = ?", (data.category,))
                       if same_competition(competition_record(row).data, data)]
            # Ambiguous multiple matches must not be auto-merged.
            if len(matches) > 1:
                raise ValueError("Lebih dari satu lomba cocok; penggabungan otomatis ditolak.")
            previous = matches[0] if matches else None
        old = previous.data.model_copy(deep=True) if previous else None
        if old and not old.field_provenance:
            # Backfill provenance for pre-stage-4 records using their retained source evidence.
            proof = conn.execute("SELECT * FROM evidence WHERE competition_id = ? AND url = ? ORDER BY id DESC LIMIT 1",
                                 (previous.id, str(old.source_url))).fetchone()
            if proof:
                origin = {"url": proof["url"], "content_hash": proof["content_hash"], "quote": proof["raw_text"]}
                old.field_provenance = {field: dict(origin) for field in snapshot}
                old.field_provenance.update({timeline_key(entry): dict(origin) for entry in old.timeline})
        merged = merge(old, data, evidence)
        assessed = evaluate(merged, preferences, now=now)
        if previous:
            record = repository.update_competition(previous.id, assessed, expected_version=previous.version,
                                                  reason="source_observation_evaluated", evidence=evidence, _connection=conn)
            outcome = "updated" if record.version != previous.version else "unchanged"
        else:
            record = repository.create_competition(assessed, dedup_key=key, evidence=evidence, _connection=conn)
            outcome = "created"
    return record, outcome


def visible_competitions(repository: Repository, *, now: datetime | None = None) -> list:
    """Reevaluate saved results against current time/preferences; excluded observations stay auditable."""
    preferences = repository.get_preferences()
    records = []
    offset = 0
    while batch := repository.list_competitions(limit=200, offset=offset):
        for record in batch:
            assessed = evaluate(record.data, preferences, now=now)
            if assessed.relevance_status != "excluded":
                records.append(record.model_copy(update={"data": assessed}))
        offset += len(batch)
    return records
