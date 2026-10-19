"""Subject parsing and thread-key normalization for meeting mail."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mirko.ingest.filename import parse_filename

_CANON_RE = re.compile(r"(?<![A-Za-z0-9])S3[-_ ]?(\d{6})(?!\d)", re.IGNORECASE)
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_AGENDA_RE = re.compile(r"^\d+(?:\.\d+)*$")
_MEETING_RE = re.compile(r"\b([A-Z]{2,4}\d?)#(\d+)\b")
_BRACKET_REV_RE = re.compile(r"\]\s*-?\s*r(\d{1,3})(?!\d)", re.IGNORECASE)
_REPLY_PREFIX_RE = re.compile(
    r"^\s*(?:(?:re|fwd|fw|aw|sv|antwort)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE
)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class SubjectInfo:
    raw: str
    meeting_id: str | None
    agenda_items: tuple[str, ...]
    tdocs: tuple[str, ...]
    working_rev: int | None
    source_hints: tuple[str, ...]
    inference: dict = field(default_factory=dict)

    @property
    def agenda_item(self) -> str | None:
        return self.agenda_items[0] if self.agenda_items else None


def normalize_subject(subject: str) -> str:
    """Produce a thread-fallback key: strip reply prefixes, fold case."""
    text = _REPLY_PREFIX_RE.sub("", subject or "")
    return _WHITESPACE.sub(" ", text).strip().casefold()


def _canonical(value: str) -> str | None:
    match = _CANON_RE.search(value)
    return f"S3-{match.group(1)}" if match else None


def _agenda_from_bracket(value: str) -> str | None:
    text = value.strip()
    if not text or "KI#" in text.upper():
        return None
    return text if _AGENDA_RE.fullmatch(text) else None


def _bracket_revision(subject: str) -> int | None:
    match = _BRACKET_REV_RE.search(subject)
    return int(match.group(1)) if match else None


def parse_subject(
    subject: str, *, series_prefix: str | None = None
) -> SubjectInfo:
    raw = subject or ""
    normalized = _WHITESPACE.sub(" ", raw.replace("\xa0", " ")).strip()

    meeting_id: str | None = None
    meeting_match = _MEETING_RE.search(normalized)
    if meeting_match is not None:
        meeting_id = f"{meeting_match.group(1)}#{meeting_match.group(2)}"

    agenda_items: list[str] = []
    bracket_tdocs: list[str] = []
    for bracket in _BRACKET_RE.finditer(normalized):
        content = bracket.group(1)
        agenda = _agenda_from_bracket(content)
        if agenda is not None and agenda not in agenda_items:
            agenda_items.append(agenda)
        tdoc = _canonical(content)
        if tdoc is not None and tdoc not in bracket_tdocs:
            bracket_tdocs.append(tdoc)

    tdocs: list[str] = []
    for match in _CANON_RE.finditer(normalized):
        tdoc = f"S3-{match.group(1)}"
        if tdoc not in tdocs:
            tdocs.append(tdoc)
    for tdoc in bracket_tdocs:
        if tdoc not in tdocs:
            tdocs.insert(0, tdoc)

    heuristic = parse_filename(normalized, series_prefix=series_prefix)
    working_rev = heuristic.working_rev
    bracket_rev = _bracket_revision(normalized)
    if working_rev is None:
        working_rev = bracket_rev

    inference = {
        "meeting_id": meeting_id,
        "agenda_items": list(agenda_items),
        "tdocs": list(tdocs),
        "working_rev": working_rev,
        "source_hints": list(heuristic.source_hints),
        "hint_kind": heuristic.hint_kind,
    }
    return SubjectInfo(
        raw=raw,
        meeting_id=meeting_id,
        agenda_items=tuple(agenda_items),
        tdocs=tuple(tdocs),
        working_rev=working_rev,
        source_hints=heuristic.source_hints,
        inference=inference,
    )
