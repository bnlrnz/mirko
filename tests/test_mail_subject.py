"""Tests for 3GPP mail subject parsing and thread keys."""

from __future__ import annotations

from mirko.ingest.mail_subject import normalize_subject, parse_subject


def test_meeting_and_agenda_without_tdoc() -> None:
    info = parse_subject(
        "[SA3#130][5.3.1.8.1] LS LS on security aspects", series_prefix="S3-26"
    )
    assert info.meeting_id == "SA3#130"
    assert info.agenda_items == ("5.3.1.8.1",)
    assert info.agenda_item == "5.3.1.8.1"
    assert info.tdocs == ()


def test_tdoc_inside_bracket_with_revision() -> None:
    info = parse_subject(
        "Re: [SA3#130][S3-264549-r1] Revised draft", series_prefix="S3-26"
    )
    assert info.meeting_id == "SA3#130"
    assert info.tdocs == ("S3-264549",)
    assert info.working_rev == 1


def test_revision_after_bracket() -> None:
    info = parse_subject(
        "[SA3#130] [S3-264463]-r2 New revision", series_prefix="S3-26"
    )
    assert info.tdocs == ("S3-264463",)
    assert info.working_rev == 2


def test_tdoc_anywhere_in_subject() -> None:
    info = parse_subject(
        "[SA3#130][5.3.1.3.2] CR S3-264202 on NTN", series_prefix="S3-26"
    )
    assert info.agenda_items == ("5.3.1.3.2",)
    assert info.tdocs == ("S3-264202",)


def test_ki_bracket_is_not_an_agenda_item() -> None:
    info = parse_subject("[SA3#130][KI#NEW] status update")
    assert info.agenda_items == ()
    assert info.tdocs == ()


def test_multiple_tdocs_and_hints() -> None:
    info = parse_subject(
        "[SA3#130] merger of S3-263847 and S3-263848 into S3-264454",
        series_prefix="S3-26",
    )
    assert info.tdocs == ("S3-263847", "S3-263848", "S3-264454")
    assert info.source_hints == ("S3-263847", "S3-263848")


def test_normalize_subject_strips_reply_prefixes() -> None:
    assert normalize_subject("Re: Fwd: [SA3#130]  Hello   World") == (
        "[sa3#130] hello world"
    )
    assert normalize_subject("AW: Re: [SA3#130] Hello") == "[sa3#130] hello"


def test_missing_subject_is_empty() -> None:
    info = parse_subject("")
    assert info.meeting_id is None
    assert info.agenda_items == ()
    assert info.tdocs == ()
