from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rag_app.index import build_index, index_status, retrieve


class KeywordEmbedder:
    model = "keyword-test"
    terms = ["sofa", "vanity", "doorway", "office", "outdoor", "phone", "curls"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = [float(lowered.count(term)) for term in self.terms]
            if not any(vector):
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                vector = [float(value + 1) for value in digest[: len(self.terms)]]
            vectors.append(vector)
        return vectors


class IndexTests(unittest.TestCase):
    def test_build_status_and_hard_type_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.sqlite3"
            embedder = KeywordEmbedder()
            report = build_index(embedder=embedder, index_path=index_path)
            self.assertGreaterEqual(report["documents"], 6)
            self.assertFalse(index_status(index_path=index_path)["stale"])
            results = retrieve(
                "sofa curls",
                "finished_showcase",
                top_k=3,
                embedder=embedder,
                index_path=index_path,
                auto_index=False,
            )
            self.assertTrue(results)
            self.assertEqual(results[0]["sample"]["id"], "fs-living-room-01")
            self.assertTrue(all(item["sample"]["creative_type"] == "finished_showcase" for item in results))

    def test_index_is_stale_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = index_status(index_path=Path(directory) / "missing.sqlite3")
            self.assertFalse(status["exists"])
            self.assertTrue(status["stale"])


if __name__ == "__main__":
    unittest.main()
