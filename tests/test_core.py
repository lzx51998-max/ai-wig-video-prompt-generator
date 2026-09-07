from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from rag_app.core import WorkbenchError, ingest_sources, load_samples, promote_review, read_source


class CoreTests(unittest.TestCase):
    def test_shared_corpus_contains_approved_samples_for_both_types(self) -> None:
        samples = load_samples(approved_only=True)
        self.assertGreaterEqual(len(samples), 6)
        self.assertEqual({sample.creative_type for sample in samples}, {"before_after", "finished_showcase"})

    def test_ingest_markdown_creates_draft_review_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "samples.md"
            source.write_text(
                "# Sample 1\nA finished showcase in a living room.\n\n# Sample 2\nA transformation reveal near a mirror.",
                encoding="utf-8",
            )
            review = root / "review.csv"
            count = ingest_sources(source, review)
            self.assertEqual(count, 2)
            with review.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(all(row["quality_status"] == "draft" for row in rows))
            self.assertEqual(rows[1]["creative_type"], "before_after")

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
            review.write_text(
                "id,creative_type,scenario,wig_features,main_action,camera,lighting,props,duration,positive_en,positive_zh,quality_status,source_file,notes\n"
                "x,finished_showcase,room,,turn,,, ,10,English,中文,draft,file,\n",
                encoding="utf-8-sig",
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
