from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from dataclasses import MISSING, asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree


CREATIVE_TYPES = {"before_after", "finished_showcase"}
REVIEW_FIELDS = [
    "id",
    "creative_type",
    "scenario",
    "wig_features",
    "main_action",
    "camera",
    "lighting",
    "props",
    "duration",
    "positive_en",
    "positive_zh",
    "quality_status",
    "source_file",
    "notes",
]


class WorkbenchError(RuntimeError):
    """A user-actionable workbench error."""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_corpus_path() -> Path:
    return project_root() / "knowledge" / "samples.jsonl"


def state_dir() -> Path:
    path = project_root() / ".rag-workbench"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class Sample:
    id: str
    creative_type: str
    scenario: str
    wig_features: list[str] = field(default_factory=list)
    main_action: str = ""
    camera: str = ""
    lighting: str = ""
    props: list[str] = field(default_factory=list)
    duration: int = 10
    positive_en: str = ""
    positive_zh: str = ""
    quality_status: str = "draft"
    source_file: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Sample":
        data = dict(raw)
        for key in ("wig_features", "props"):
            value = data.get(key, [])
            if isinstance(value, str):
                value = [item.strip() for item in re.split(r"[;,，；]", value) if item.strip()]
            data[key] = list(value or [])
        try:
            data["duration"] = int(data.get("duration") or 10)
        except (TypeError, ValueError) as exc:
            raise WorkbenchError(f"样例 {data.get('id', '<unknown>')} 的 duration 无效") from exc
        values = {}
        for key, field_info in cls.__dataclass_fields__.items():
            if key in data:
                values[key] = data[key]
            elif field_info.default is not MISSING:
                values[key] = field_info.default
            elif field_info.default_factory is not MISSING:
                values[key] = field_info.default_factory()
        sample = cls(**values)
        sample.validate()
        return sample

    def validate(self) -> None:
        if not self.id.strip():
            raise WorkbenchError("样例 id 不能为空")
        if self.creative_type not in CREATIVE_TYPES:
            raise WorkbenchError(f"样例 {self.id} 的 creative_type 必须是 {sorted(CREATIVE_TYPES)}")
        if self.quality_status not in {"draft", "approved", "rejected"}:
            raise WorkbenchError(f"样例 {self.id} 的 quality_status 无效")
        if not 8 <= self.duration <= 12:
            raise WorkbenchError(f"样例 {self.id} 的 duration 必须在 8–12 秒")
        if self.quality_status == "approved" and not (self.positive_en and self.positive_zh):
            raise WorkbenchError(f"已批准样例 {self.id} 必须同时有中英文正向提示词")

    def retrieval_text(self) -> str:
        return "\n".join(
            [
                f"creative_type: {self.creative_type}",
                f"scenario: {self.scenario}",
                f"wig_features: {', '.join(self.wig_features)}",
                f"main_action: {self.main_action}",
                f"camera: {self.camera}",
                f"lighting: {self.lighting}",
                f"props: {', '.join(self.props)}",
                f"duration: {self.duration}",
                self.positive_en,
                self.positive_zh,
            ]
        )

    def to_dict(self) -> dict:
        return asdict(self)


def load_samples(path: Path | None = None, *, approved_only: bool = False) -> list[Sample]:
    corpus_path = path or default_corpus_path()
    if not corpus_path.exists():
        raise WorkbenchError(f"样例库不存在：{corpus_path}")
    samples: list[Sample] = []
    seen: set[str] = set()
    with corpus_path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                sample = Sample.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                raise WorkbenchError(f"{corpus_path}:{line_number} 不是有效样例") from exc
            if sample.id in seen:
                raise WorkbenchError(f"样例 id 重复：{sample.id}")
            seen.add(sample.id)
            if not approved_only or sample.quality_status == "approved":
                samples.append(sample)
    return samples


def save_samples(samples: Iterable[Sample], path: Path | None = None) -> None:
    corpus_path = path or default_corpus_path()
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(samples, key=lambda item: item.id)
    content = "".join(json.dumps(item.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n" for item in ordered)
    corpus_path.write_text(content, encoding="utf-8")


def corpus_fingerprint(samples: Iterable[Sample]) -> str:
    normalized = "\n".join(
        json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in sorted(samples, key=lambda value: value.id)
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise WorkbenchError(f"无法读取 DOCX：{path}") from exc
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        if text.strip():
            paragraphs.append(text.strip())
    return "\n".join(paragraphs)


def read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".doc":
        raise WorkbenchError(f"旧版 .doc 不受支持，请先另存为 .docx：{path}")
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8-sig")
    raise WorkbenchError(f"不支持的文件类型：{path.suffix}")


def split_source(text: str) -> list[str]:
    explicit = re.split(r"(?im)^\s*---\s*(?:SAMPLE|样例)\s*---\s*$", text)
    chunks = [item.strip() for item in explicit if item.strip()]
    if len(chunks) > 1:
        return chunks
    heading = re.split(r"(?im)^\s*#{1,3}\s*(?:sample|样例)\s*\d*[^\n]*$", text)
    chunks = [item.strip() for item in heading if item.strip()]
    return chunks or ([text.strip()] if text.strip() else [])


def _source_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(
            path for path in input_path.rglob("*") if path.is_file() and path.suffix.lower() in {".docx", ".doc", ".md", ".txt"}
        )
    raise WorkbenchError(f"输入路径不存在：{input_path}")


def _infer_creative_type(text: str) -> str:
    before_after_terms = ("before and after", "transformation", "reveal", "换发", "反差", "转场")
    lowered = text.lower()
    return "before_after" if any(term in lowered for term in before_after_terms) else "finished_showcase"


def ingest_sources(input_path: Path, output_csv: Path) -> int:
    rows: list[dict[str, str | int]] = []
    for source in _source_files(input_path):
        for position, text in enumerate(split_source(read_source(source)), 1):
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            mostly_ascii = sum(character.isascii() for character in text) / max(1, len(text)) > 0.7
            rows.append(
                {
                    "id": f"import-{digest}",
                    "creative_type": _infer_creative_type(text),
                    "scenario": "",
                    "wig_features": "",
                    "main_action": "",
                    "camera": "",
                    "lighting": "",
                    "props": "",
                    "duration": 10,
                    "positive_en": text if mostly_ascii else "",
                    "positive_zh": "" if mostly_ascii else text,
                    "quality_status": "draft",
                    "source_file": f"{source.name}#{position}",
                    "notes": "请人工补齐标签、中英文版本并审核",
                }
            )
    if not rows:
        raise WorkbenchError("没有找到可导入的非空样例")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def promote_review(review_file: Path, corpus_path: Path | None = None) -> tuple[int, int]:
    destination = corpus_path or default_corpus_path()
    existing = {sample.id: sample for sample in load_samples(destination)} if destination.exists() else {}
    promoted = 0
    skipped = 0
    with review_file.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("quality_status", "").strip() != "approved":
                skipped += 1
                continue
            sample = Sample.from_dict(raw)
            existing[sample.id] = sample
            promoted += 1
    if not promoted:
        raise WorkbenchError("审核表中没有 quality_status=approved 的记录")
    save_samples(existing.values(), destination)
    return promoted, skipped
