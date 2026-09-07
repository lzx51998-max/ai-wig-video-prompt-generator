from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from .core import Sample, WorkbenchError, corpus_fingerprint, load_samples, state_dir
from .embeddings import OllamaEmbedder


INDEX_SCHEMA_VERSION = "1"


def default_index_path() -> Path:
    return state_dir() / "index.sqlite3"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            sample_id TEXT PRIMARY KEY,
            creative_type TEXT NOT NULL,
            sample_json TEXT NOT NULL,
            vector_json TEXT NOT NULL
        );
        """
    )
    return connection


def build_index(
    *,
    embedder: OllamaEmbedder | object | None = None,
    index_path: Path | None = None,
    corpus_path: Path | None = None,
) -> dict:
    samples = load_samples(corpus_path, approved_only=True)
    if not samples:
        raise WorkbenchError("没有 approved 样例，无法建立索引")
    provider = embedder or OllamaEmbedder()
    vectors = provider.embed([sample.retrieval_text() for sample in samples])
    if len(vectors) != len(samples):
        raise WorkbenchError("嵌入数量与样例数量不一致")
    fingerprint = corpus_fingerprint(samples)
    destination = index_path or default_index_path()
    with closing(_connect(destination)) as connection:
        with connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM metadata")
            connection.executemany(
                "INSERT INTO documents(sample_id, creative_type, sample_json, vector_json) VALUES (?, ?, ?, ?)",
                [
                    (
                        sample.id,
                        sample.creative_type,
                        json.dumps(asdict(sample), ensure_ascii=False),
                        json.dumps(vector),
                    )
                    for sample, vector in zip(samples, vectors, strict=True)
                ],
            )
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("schema_version", INDEX_SCHEMA_VERSION),
                    ("corpus_fingerprint", fingerprint),
                    ("embedding_model", getattr(provider, "model", "test")),
                    ("document_count", str(len(samples))),
                ],
            )
    return {"documents": len(samples), "fingerprint": fingerprint, "index": str(destination)}


def index_status(index_path: Path | None = None, corpus_path: Path | None = None) -> dict:
    destination = index_path or default_index_path()
    approved = load_samples(corpus_path, approved_only=True)
    current_fingerprint = corpus_fingerprint(approved)
    if not destination.exists():
        return {
            "exists": False,
            "stale": True,
            "documents": 0,
            "approved_samples": len(approved),
            "fingerprint": current_fingerprint,
        }
    try:
        with closing(sqlite3.connect(destination)) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise WorkbenchError(f"本地索引损坏，请删除后重建：{destination}") from exc
    stale = (
        metadata.get("schema_version") != INDEX_SCHEMA_VERSION
        or metadata.get("corpus_fingerprint") != current_fingerprint
        or int(documents) != len(approved)
    )
    return {
        "exists": True,
        "stale": stale,
        "documents": int(documents),
        "approved_samples": len(approved),
        "fingerprint": current_fingerprint,
        "indexed_fingerprint": metadata.get("corpus_fingerprint"),
        "embedding_model": metadata.get("embedding_model"),
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return -1.0
    return dot / (left_norm * right_norm)


def retrieve(
    query: str,
    creative_type: str,
    *,
    top_k: int = 3,
    embedder: OllamaEmbedder | object | None = None,
    index_path: Path | None = None,
    corpus_path: Path | None = None,
    auto_index: bool = True,
) -> list[dict]:
    if creative_type not in {"before_after", "finished_showcase"}:
        raise WorkbenchError("creative_type 必须是 before_after 或 finished_showcase")
    if not query.strip():
        raise WorkbenchError("检索 query 不能为空")
    if not 1 <= top_k <= 10:
        raise WorkbenchError("top_k 必须在 1–10 之间")
    provider = embedder or OllamaEmbedder()
    status = index_status(index_path, corpus_path)
    if status["stale"]:
        if not auto_index:
            raise WorkbenchError("本地索引缺失或已过期，请运行 python -m rag_app index")
        build_index(embedder=provider, index_path=index_path, corpus_path=corpus_path)
    query_vector = provider.embed([query])[0]
    destination = index_path or default_index_path()
    with closing(sqlite3.connect(destination)) as connection:
        rows = connection.execute(
            "SELECT sample_json, vector_json FROM documents WHERE creative_type = ?",
            (creative_type,),
        ).fetchall()
    ranked: list[tuple[float, Sample]] = []
    for sample_json, vector_json in rows:
        sample = Sample.from_dict(json.loads(sample_json))
        score = _cosine(query_vector, [float(value) for value in json.loads(vector_json)])
        ranked.append((score, sample))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [
        {"rank": rank, "score": round(score, 6), "sample": sample.to_dict()}
        for rank, (score, sample) in enumerate(ranked[:top_k], 1)
    ]
