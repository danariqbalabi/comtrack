import re

from ..models import CompetitionData
from .dates import parse_timeline


def infer_category(name: str, description: str = "") -> str:
    patterns = {"hackathon": r"\bhackathons?\b|\bhackfest\b", "BCC": r"\bBCC\b|\bbusiness[ -]+case(?:[ -]+competition)?\b",
                "BPC": r"\bBPC\b|\bbusiness[ -]+plan(?:[ -]+competition)?\b|\brencana bisnis\b"}
    for text in (name, description):
        matches = [category for category, pattern in patterns.items() if re.search(pattern, text, re.I)]
        if matches:
            return matches[0] if len(matches) == 1 else "uncertain"
    return "uncertain"


def prepare(data: CompetitionData) -> CompetitionData:
    result = data.model_copy(deep=True)
    if result.category == "uncertain":
        result.category = infer_category(result.name, result.summary or "")
    result.timeline = [parse_timeline(entry.raw_text, kind=entry.kind, label=entry.label,
                                      timezone_hint=entry.timezone, phase_id=entry.phase_id)
                       if entry.date is None and entry.at is None else entry for entry in result.timeline]
    return result
