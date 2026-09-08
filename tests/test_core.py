from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from rag_app.core import REVIEW_FIELDS, WorkbenchError, ingest_sources, load_samples, promote_review, read_source


class CoreTests(unittest.TestCase):
    def test_shared_corpus_contains_approved_samples_for_both_types(self) -> None:
        samples = load_samples(approved_only=True)
        self.assertGreaterEqual(len(samples), 6)
        self.assertEqual({sample.creative_type for sample in samples}, {"indoor", "outdoor"})

    def test_ingest_markdown_creates_draft_review_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "samples.md"
            source.write_text(
                "# Sample 1\nA finished showcase in a living room.\n\n# Sample 2\nAn outdoor transformation reveal on a garden path.",
                encoding="utf-8",
            )
            review = root / "review.csv"
            count = ingest_sources(source, review)
            self.assertEqual(count, 2)
            with review.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(all(row["quality_status"] == "draft" for row in rows))
            self.assertEqual(rows[1]["creative_type"], "outdoor")

    def test_read_minimal_docx(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body><w:p><w:r><w:t>DOCX prompt sample</w:t></w:r></w:p></w:body>
        </w:document>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            self.assertEqual(read_source(path), "DOCX prompt sample")

    def test_promote_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "review.csv"
            with review.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
                writer.writeheader()
                writer.writerow(
                    {
                        "id": "x",
                        "creative_type": "indoor",
                        "scene": json.dumps({"summary": "room"}),
                        "wig_focus": "[]",
                        "action_plan": json.dumps({"summary": "turn"}),
                        "timeline": "[]",
                        "camera": json.dumps({"continuity_mode": "one_take"}),
                        "lighting": "{}",
                        "props": "[]",
                        "continuity": "{}",
                        "technical": json.dumps({"duration_seconds": 10}),
                        "audio": "{}",
                        "positive_en": "English",
                        "positive_zh": "中文",
                        "quality_status": "draft",
                        "source_file": "file",
                        "notes": "",
                    }
                )
            with self.assertRaises(WorkbenchError):
                promote_review(review, root / "samples.jsonl")

    def test_invalid_creative_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            path.write_text(json.dumps({"id": "bad", "creative_type": "other"}), encoding="utf-8")
            with self.assertRaises(WorkbenchError):
                load_samples(path)


if __name__ == "__main__":
    unittest.main()
