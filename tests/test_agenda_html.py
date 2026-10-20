"""Tests for the agenda/allocation HTML parser.

Runs with the standard library::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from mirko.ingest.agenda_html import (
    canonical_tdoc,
    normalize_note,
    normalize_text,
    parse_agenda_file,
    parse_agenda_html,
    timestamp_from_filename,
)

FIXTURE = Path(__file__).parent / "fixtures" / "agenda_excerpt.htm"


class NormalizationTests(unittest.TestCase):
    def test_canonical_tdoc_variants(self) -> None:
        self.assertEqual(canonical_tdoc("S3\u2011263700"), "S3-263700")
        self.assertEqual(canonical_tdoc("S3_263700"), "S3-263700")
        self.assertEqual(canonical_tdoc("S3 263700"), "S3-263700")
        self.assertEqual(canonical_tdoc("S3263700"), "S3-263700")
        self.assertEqual(canonical_tdoc("x S3-263700.zip"), "S3-263700")

    def test_canonical_tdoc_rejects_malformed(self) -> None:
        self.assertIsNone(canonical_tdoc("S3-26abcd"))
        self.assertIsNone(canonical_tdoc("S3-2604090"))
        self.assertIsNone(canonical_tdoc("S6-263386"))
        self.assertIsNone(canonical_tdoc(""))

    def test_normalize_text_nbsp_and_dashes(self) -> None:
        self.assertEqual(normalize_text("\xa0S3\u2011263700\xa0"), "S3-263700")
        self.assertEqual(normalize_text("A\u2013B\u2014C"), "A-B-C")

    def test_normalize_note_preserves_lines(self) -> None:
        note = normalize_note(
            "Nokia: one.  \nHuawei: two.\n\n\nQualcomm: three."
        )
        self.assertEqual(note, "Nokia: one.\nHuawei: two.\n\nQualcomm: three.")

    def test_timestamp_from_filename(self) -> None:
        self.assertEqual(
            timestamp_from_filename(
                "AgendaWithTdocAllocation_2026-10-16_14h37.htm"
            ),
            "2026-10-16T14:37:00",
        )


class AgendaParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse_agenda_file(FIXTURE)
        cls.by = {row.tdoc: row for row in cls.result.rows}

    def test_header(self) -> None:
        self.assertEqual(len(self.result.header), 13)
        self.assertEqual(self.result.header[2], "TDoc")

    def test_row_count_and_agenda_forward_fill(self) -> None:
        self.assertEqual(len(self.result.rows), 6)
        self.assertEqual(self.by["S3-263701"].agenda_item, "1")
        self.assertEqual(self.by["S3-264262"].agenda_item, "5.3.1.2.2")
        self.assertEqual(self.by["S3-264402"].agenda_item, "5.3.1.2.2")

    def test_tdoc_fields(self) -> None:
        row = self.by["S3-263700"]
        self.assertEqual(row.type, "agenda")
        self.assertTrue(row.avail)
        self.assertTrue(row.treated)
        self.assertIsNotNone(row.treated_note)
        self.assertIn("Delegates to check the LS.", row.treated_note or "")
        self.assertIn("Huawei: no objection.", row.treated_note or "")
        self.assertEqual(row.decision, "approved")
        self.assertEqual(row.zip_path, "docs/S3-263700.zip")

    def test_revision_fields(self) -> None:
        self.assertEqual(self.by["S3-263701"].decision, "revised")
        self.assertEqual(self.by["S3-263701"].replaced_by, "S3-264398")
        self.assertEqual(self.by["S3-264398"].replaces, "S3-263701")

    def test_lineage(self) -> None:
        edges = {(edge.source, edge.kind, edge.target) for edge in self.result.edges}
        self.assertIn(("S3-263701", "revision_of", "S3-264398"), edges)
        self.assertIn(("S3-264262", "revision_of", "S3-264402"), edges)
        self.assertIn(("S3-264300", "merged_into", "S3-264402"), edges)
        self.assertEqual(self.result.issues, [])

    def test_source_timestamp(self) -> None:
        self.assertEqual(self.result.source_timestamp, "2026-10-16T14:37:00")

    def test_accepts_bytes(self) -> None:
        result = parse_agenda_html(FIXTURE.read_bytes())
        self.assertEqual(len(result.rows), 6)


REAL_FIXTURE = Path(__file__).parent / "fixtures" / "agenda_2026-10-16.htm"


@unittest.skipUnless(REAL_FIXTURE.exists(), "real agenda snapshot not present")
class RealSnapshotRegressionTests(unittest.TestCase):
    """Golden counts for a saved SA3#130 agenda snapshot.

    If this fails after 3GPP republishes the file, refresh the fixture rather
    than loosening the assertions.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = parse_agenda_file(REAL_FIXTURE)

    def test_row_and_header_counts(self) -> None:
        self.assertEqual(len(self.result.header), 13)
        self.assertEqual(len(self.result.rows), 900)

    def test_treated_notes_and_zip_paths(self) -> None:
        self.assertEqual(
            sum(1 for row in self.result.rows if row.treated_note), 51
        )
        self.assertEqual(
            sum(1 for row in self.result.rows if row.zip_path), 900
        )

    def test_tdoc_dash_is_normalized(self) -> None:
        self.assertIn("S3-263700", {row.tdoc for row in self.result.rows})
        self.assertEqual(self.result.source_timestamp, "2026-10-16T14:37:00")

    def test_edge_kinds(self) -> None:
        kinds = Counter(edge.kind for edge in self.result.edges)
        self.assertEqual(kinds["revision_of"], 186)
        self.assertEqual(kinds["merged_into"], 228)
        self.assertEqual(kinds["based_on"], 28)

    def test_ls_reply_links(self) -> None:
        edges = {(edge.source, edge.kind, edge.target) for edge in self.result.edges}
        self.assertIn(("S3-264191", "based_on", "S3-264341"), edges)
        self.assertIn(("S3-264202", "based_on", "S3-264406"), edges)
        self.assertIn(("S3-264212", "based_on", "S3-264466"), edges)

    def test_only_known_issue_kinds(self) -> None:
        self.assertEqual(
            {issue.kind for issue in self.result.issues},
            {"ambiguous_baseline", "baseline_not_revised"},
        )


if __name__ == "__main__":
    unittest.main()
