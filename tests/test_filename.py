"""Golden and property tests for the layered filename parser."""

from __future__ import annotations

import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from mirko.ingest.filename import FilenameInfo, normalize_filename, parse_filename

TDOC_RE = re.compile(r"^S3-\d{6}$")

CORPUS = Path("SYSTEM_DESIGN.md")


def corpus_names() -> list[str]:
    text = CORPUS.read_text(encoding="utf-8")
    block = text.split("## Appendix A", 1)[1].split("```", 2)[1]
    return [line for line in block.strip().splitlines() if line]


def test_normalize_dashes_and_whitespace() -> None:
    assert normalize_filename("draft\u2011S3\u2011264314\t r1  .docx") == (
        "draft-S3-264314 r1 .docx"
    )


def test_draft_prefixed_primary_wins() -> None:
    info = parse_filename(
        "Draft LS reply (S3-264202 S6- 263386).docx", series_prefix="S3-26"
    )
    assert info.primary_tdoc == "S3-264202"
    assert info.tier == 1


def test_attached_revision_markers() -> None:
    assert parse_filename("draft S3-264313r1-New.docx").working_rev == 1
    assert parse_filename("draft_S3-264550 -r1 TR.docx").working_rev == 1
    assert parse_filename("draft_S3-263832-r3 .docx").working_rev == 3
    assert parse_filename("draft_S3-264279_abbreviations-r1.docx").working_rev == 1
    assert parse_filename("draft-S3-264561-was-263713 notes r3..docx").working_rev == 3


def test_document_version_is_kept_separate() -> None:
    info = parse_filename("draft_S3-263703-v5-DetailedAgenda.docx")
    assert info.working_rev is None
    assert info.document_version == 5


def test_source_hint_expansion_and_self_reference() -> None:
    info = parse_filename(
        "draft_S3-264002r2 merger of 4002 4181 and 3776.docx",
        series_prefix="S3-26",
    )
    assert info.source_hints == ("S3-264181", "S3-263776")


def test_self_reference_is_removed_from_hints() -> None:
    info = parse_filename(
        "draft-S3-264163-r1-merger_of_S3-263756_S3-263845_S3-264163.docx"
    )
    assert info.source_hints == ("S3-263756", "S3-263845")


def test_multiple_hint_groups_are_combined() -> None:
    info = parse_filename(
        "draft-S3-264549-r1_revision of 3846_merger of 4123, 4167_A#6.docx",
        series_prefix="S3-26",
    )
    assert info.source_hints == ("S3-263846", "S3-264123", "S3-264167")


def test_hyphen_chain_is_expanded() -> None:
    info = parse_filename(
        "draft_S3-264253-r1-merger of 4253-4276-4370-4356-4381-Standalone.docx",
        series_prefix="S3-26",
    )
    assert info.source_hints == (
        "S3-264276",
        "S3-264370",
        "S3-264356",
        "S3-264381",
    )


def test_adjacent_hint_and_token() -> None:
    info = parse_filename(
        "draft_S3-264580_r2_ KI (mergingS3-264084, S3-263794).docx"
    )
    assert info.source_hints == ("S3-264084", "S3-263794")


def test_malformed_primary_does_not_steal_hint_token() -> None:
    info = parse_filename(
        "draft_S3-26abcd-r3 was S3-263733_A#8.docx", series_prefix="S3-26"
    )
    assert info.primary_tdoc is None
    assert info.source_hints == ("S3-263733",)
    assert any(issue.startswith("malformed_tdoc") for issue in info.issues)
    assert info.tier == 3
    assert info.unfiled


def test_shortcut_detection() -> None:
    info = parse_filename("draft_S3-264452-r4 was 3799 - A#9.docx.lnk")
    assert info.is_shortcut
    assert info.extension == ".lnk"


def test_corpus_is_parsed_without_crashing() -> None:
    names = corpus_names()
    assert len(names) >= 50
    for name in names:
        info = parse_filename(name, series_prefix="S3-26")
        assert isinstance(info, FilenameInfo)
        if info.primary_tdoc is not None:
            assert TDOC_RE.fullmatch(info.primary_tdoc)
        if info.working_rev is not None:
            assert 1 <= info.working_rev <= 16
        for hint in info.source_hints:
            assert TDOC_RE.fullmatch(hint)
        assert 0.0 <= info.confidence <= 1.0


def test_corpus_expected_primaries() -> None:
    expected = {
        "drafft_S3-264314-r1.docx": "S3-264314",
        "draft S3-264313r1-New_NTN_Security_SID.docx": "S3-264313",
        "draft-S3-263561-was-263713 A#4.docx": "S3-263561",
        "draft_S3-264089-r1 merging S3-2604090.docx": "S3-264089",
        "draft_S3-264519-r1_merger_of_S3-263764_S3263763.docx": "S3-264519",
        "S3-263915.zip": "S3-263915",
        "Meeting notes for Monday lunch session (5.1.10).docx": None,
        "SP-260918_2026-09-07_5G-ACIA-LS_2026-002.docx": None,
    }
    for name, primary in expected.items():
        assert parse_filename(name, series_prefix="S3-26").primary_tdoc == primary


@given(st.text(max_size=200))
@settings(max_examples=200)
def test_arbitrary_filenames_never_crash(name: str) -> None:
    info = parse_filename(name, series_prefix="S3-26")
    assert 0.0 <= info.confidence <= 1.0


@given(st.text(max_size=200))
@settings(max_examples=100)
def test_parse_is_idempotent(name: str) -> None:
    first = parse_filename(name, series_prefix="S3-26")
    second = parse_filename(first.raw, series_prefix="S3-26")
    assert first == second
