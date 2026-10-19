"""Layered heuristic parser for 3GPP working-draft filenames.

The parser never raises on malformed input. Every family it recognises is
returned with a confidence, and ambiguous fragments are reported as hints rather
than guessed silently. Official lineage still comes only from the HTML agenda.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_WHITESPACE = re.compile(r"\s+")

_DRAFT_PREFIX_RE = re.compile(
    r"(?<![A-Za-z])(?:drafft|draft)[-_ ]*S3[-_ ]?(\d{6})(?!\d)",
    re.IGNORECASE,
)
_CANON_RE = re.compile(r"(?<![A-Za-z0-9])S3[-_ ]?(\d{6})(?!\d)", re.IGNORECASE)
_CANON_ANY_RE = re.compile(r"S3[-_ ]?(\d{6})(?!\d)", re.IGNORECASE)
_BARE6_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_BARE4_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_MALFORMED_RE = re.compile(
    r"(?<![A-Za-z0-9])S3[-_ ]?([A-Za-z0-9]{2,12})", re.IGNORECASE
)

_ATTACHED_REV_RE = re.compile(
    r"[ \t]*[-_]?[ \t]*([rv])(\d{1,3})(?!\d)", re.IGNORECASE
)
_TRAILING_REV_RE = re.compile(
    r"(?:^|[\s_\-])r(\d{1,3})[.\s]*$", re.IGNORECASE
)

_HINT_PHRASES = (
    "mergering",
    "merger of",
    "merger_of",
    "merger-of",
    "merge of",
    "merge_of",
    "merge-of",
    "merging",
    "merged",
    "merger",
    "revision of",
    "revision_of",
    "revision-of",
    "was",
)
_HINT_RE = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(re.escape(phrase) for phrase in _HINT_PHRASES)
    + r")(?:(?![A-Za-z])|(?=S3[-_ ]?\d{6}))",
    re.IGNORECASE,
)
_HINT_KINDS = {
    "was": "was",
    "revision of": "revision_of",
    "revision_of": "revision_of",
    "revision-of": "revision_of",
    "merged": "merged",
    "merging": "merging",
    "mergering": "mergering",
    "merger": "merger",
    "merger of": "merger_of",
    "merger_of": "merger_of",
    "merger-of": "merger_of",
    "merge of": "merge_of",
    "merge_of": "merge_of",
    "merge-of": "merge_of",
}
_SEPARATOR_RE = re.compile(r"(?:[\s,_+\-]+|\band\b|&)+", re.IGNORECASE)

_SHORTCUT_EXTENSIONS = frozenset(
    {".lnk", ".desktop", ".exe", ".sh", ".bat", ".cmd", ".ps1"}
)


@dataclass(frozen=True)
class FilenameInfo:
    raw: str
    name: str
    normalized: str
    primary_tdoc: str | None
    working_rev: int | None
    document_version: int | None
    source_hints: tuple[str, ...]
    hint_kind: str | None
    confidence: float
    tier: int
    extension: str
    is_shortcut: bool
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unfiled(self) -> bool:
        return self.primary_tdoc is None


def normalize_filename(name: str) -> str:
    """Tier 0: normalize dashes/whitespace without destroying the raw name."""
    value = name.replace("\xa0", " ")
    for dash in _DASHES:
        value = value.replace(dash, "-")
    return _WHITESPACE.sub(" ", value).strip()


def _canonical_from_match(match: re.Match[str]) -> str:
    return f"S3-{match.group(1)}"


def _find_primary(normalized: str) -> tuple[re.Match[str], bool] | None:
    preferred = _DRAFT_PREFIX_RE.search(normalized)
    if preferred is not None:
        return preferred, True
    match = _CANON_RE.search(normalized)
    if match is not None:
        first_hint = _HINT_RE.search(normalized)
        if first_hint is not None and first_hint.start() < match.start():
            return None
        return match, False
    return None


def _parse_revision(
    normalized: str, span: tuple[int, int]
) -> tuple[int | None, int | None, list[str]]:
    issues: list[str] = []
    tail = normalized[span[1] :]
    working_rev: int | None = None
    document_version: int | None = None
    attached = _ATTACHED_REV_RE.match(tail)
    if attached is not None:
        marker = attached.group(1).casefold()
        number = int(attached.group(2))
        if marker == "r":
            working_rev = number
        else:
            document_version = number

    text_without_extension = normalized
    suffix = PurePosixPath(normalized).suffix
    if suffix:
        text_without_extension = normalized[: -len(suffix)]

    if working_rev is None:
        trailing = _TRAILING_REV_RE.search(text_without_extension)
        if trailing is not None:
            working_rev = int(trailing.group(1))
    elif attached is not None:
        trailing = _TRAILING_REV_RE.search(text_without_extension)
        if trailing is not None and int(trailing.group(1)) != working_rev:
            issues.append("revision_conflict")
    return working_rev, document_version, issues


def _expand_bare(value: str, prefix: str | None) -> str | None:
    if len(value) == 6:
        return f"S3-{value}"
    if len(value) == 4 and prefix:
        return f"{prefix}{value}"
    return None


def _collect_hint_tokens(
    normalized: str, start: int, prefix: str | None
) -> list[str]:
    tokens: list[str] = []
    position = start
    length = len(normalized)
    while position < length:
        separator = _SEPARATOR_RE.match(normalized, position)
        if separator is not None:
            if separator.end() == position:
                break
            position = separator.end()
        if position >= length:
            break

        canonical = _CANON_ANY_RE.match(normalized, position)
        if canonical is not None:
            tokens.append(_canonical_from_match(canonical))
            position = canonical.end()
            continue

        bare_six = _BARE6_RE.match(normalized, position)
        if bare_six is not None:
            tokens.append(f"S3-{bare_six.group(1)}")
            position = bare_six.end()
            continue

        bare_four = _BARE4_RE.match(normalized, position)
        if bare_four is not None:
            expanded = _expand_bare(bare_four.group(1), prefix)
            if expanded is not None:
                tokens.append(expanded)
                position = bare_four.end()
                continue
        break
    return tokens


def _source_hints(
    normalized: str, primary: str | None, prefix: str | None
) -> tuple[tuple[str, ...], str | None, list[str]]:
    hints: list[str] = []
    first_kind: str | None = None
    issues: list[str] = []
    for hint in _HINT_RE.finditer(normalized):
        kind = _HINT_KINDS.get(hint.group(1).casefold(), hint.group(1).casefold())
        if first_kind is None:
            first_kind = kind
        for token in _collect_hint_tokens(normalized, hint.end(), prefix):
            if token != primary and token not in hints:
                hints.append(token)
    return tuple(hints), first_kind, issues


def parse_filename(
    raw: str, *, series_prefix: str | None = None
) -> FilenameInfo:
    """Parse a single filename into primary TDoc, revision, and source hints."""
    name = PurePosixPath(raw.replace("\\", "/")).name
    normalized = normalize_filename(name)
    extension = PurePosixPath(name).suffix.casefold()
    issues: list[str] = []

    primary_match = _find_primary(normalized)
    if primary_match is not None:
        match, after_draft_prefix = primary_match
        primary = _canonical_from_match(match)
        span = match.span(1)
        working_rev, document_version, revision_issues = _parse_revision(
            normalized, span
        )
        issues.extend(revision_issues)
        tier = 1
    else:
        primary = None
        working_rev = None
        document_version = None
        tier = 4
        malformed = _MALFORMED_RE.search(normalized)
        if malformed is not None:
            issues.append(f"malformed_tdoc:{malformed.group(0)}")
        after_draft_prefix = False

    hints, first_kind, hint_issues = _source_hints(
        normalized, primary, series_prefix
    )
    issues.extend(hint_issues)
    if primary is None and hints:
        tier = 3

    if primary is not None and hints:
        confidence = 0.8
    elif primary is not None:
        confidence = 0.7
    elif hints:
        confidence = 0.4
    else:
        confidence = 0.0

    if after_draft_prefix:
        confidence = min(1.0, confidence + 0.05)

    return FilenameInfo(
        raw=raw,
        name=name,
        normalized=normalized,
        primary_tdoc=primary,
        working_rev=working_rev,
        document_version=document_version,
        source_hints=hints,
        hint_kind=first_kind,
        confidence=round(confidence, 2),
        tier=tier,
        extension=extension,
        is_shortcut=extension in _SHORTCUT_EXTENSIONS,
        issues=tuple(issues),
    )
