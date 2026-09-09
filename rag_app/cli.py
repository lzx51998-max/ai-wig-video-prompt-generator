from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .core import (
    CREATIVE_TYPES,
    WorkbenchError,
    default_corpus_path,
    ingest_sources,
    load_samples,
    project_root,
    promote_review,
)
from .embeddings import OllamaEmbedder
from .index import build_index, index_status, retrieve
from .session import asset_descriptor, load_session, prepare_request, save_session
from .validator import assemble_document, load_json, validate_document


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_doctor(_: argparse.Namespace) -> int:
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    record("python", sys.version_info >= (3, 11), platform.python_version())
    record("git", shutil.which("git") is not None, shutil.which("git") or "未找到")
    for relative in ("PRD.md", "AGENTS.md", "提示词模板.md", "rules/fixed_negative_en.txt", "rules/fixed_negative_zh.txt"):
        exists = (project_root() / relative).exists()
        record(relative, exists, "存在" if exists else "缺失")
    try:
        samples = load_samples(approved_only=True)
        record("approved_samples", bool(samples), str(len(samples)))
    except WorkbenchError as exc:
        record("approved_samples", False, str(exc))
    try:
        models = OllamaEmbedder().available_models()
        has_model = any(name == "embeddinggemma" or name.startswith("embeddinggemma:") for name in models)
        record("ollama", True, "本地 API 可用")
        record("embeddinggemma", has_model, "已安装" if has_model else "请运行 ollama pull embeddinggemma")
    except WorkbenchError as exc:
        record("ollama", False, str(exc))
        record("embeddinggemma", False, "Ollama 不可用")
    try:
        status = index_status()
        record("index", status["exists"] and not status["stale"], json.dumps(status, ensure_ascii=False))
    except WorkbenchError as exc:
        record("index", False, str(exc))
    _json({"ok": all(check["ok"] for check in checks), "checks": checks})
    return 0 if all(check["ok"] for check in checks) else 1


def command_status(_: argparse.Namespace) -> int:
    all_samples = load_samples()
    counts = {"approved": 0, "draft": 0, "rejected": 0}
    types = {creative_type: 0 for creative_type in sorted(CREATIVE_TYPES)}
    for sample in all_samples:
        counts[sample.quality_status] += 1
        if sample.quality_status == "approved":
            types[sample.creative_type] += 1
    _json({"corpus": str(default_corpus_path()), "samples": counts, "approved_by_type": types, "index": index_status()})
    return 0


def command_ingest(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else project_root() / "knowledge" / f"review-{datetime.now():%Y%m%d-%H%M%S}.csv"
    count = ingest_sources(Path(args.input), output)
    _json({"imported": count, "review_file": str(output), "status": "draft"})
    return 0


def command_promote(args: argparse.Namespace) -> int:
    promoted, skipped = promote_review(Path(args.review_file))
    _json({"promoted": promoted, "skipped": skipped, "corpus": str(default_corpus_path())})
    return 0


def command_index(args: argparse.Namespace) -> int:
    promoted = None
    if args.review_file:
        promoted = promote_review(Path(args.review_file))
    result = build_index()
    if promoted:
        result["review"] = {"promoted": promoted[0], "skipped": promoted[1]}
    _json(result)
    return 0


def command_retrieve(args: argparse.Namespace) -> int:
    results = retrieve(args.query, args.creative_type, top_k=args.top_k, auto_index=not args.no_auto_index)
    _json({"query": args.query, "creative_type": args.creative_type, "results": results})
    return 0


def command_assemble(args: argparse.Namespace) -> int:
    request = load_json(Path(args.request))
    draft = load_json(Path(args.draft))
    document = assemble_document(request, draft)
    report = validate_document(document, int(request.get("duration", 10)))
    if not report["valid"]:
        raise WorkbenchError("组装后的提示词未通过校验：" + "；".join(report["errors"]))
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(document, encoding="utf-8")
        _json({"valid": True, "output": str(output)})
    else:
        print(document)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    report = validate_document(Path(args.input).read_text(encoding="utf-8-sig"), args.duration)
    _json(report)
    return 0 if report["valid"] else 1


def command_evaluate(args: argparse.Namespace) -> int:
    cases_path = Path(args.cases) if args.cases else project_root() / "evaluation" / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    passed = 0
    details = []
    for case in cases:
        results = retrieve(case["query"], case["creative_type"], top_k=3)
        expected = {str(tag).lower() for tag in case.get("expected_tags", [])}
        haystack = " ".join(
            str(result["sample"]["scene"].get("summary", ""))
            + " "
            + str(result["sample"]["action_plan"].get("summary", ""))
            + " "
            + " ".join(result["sample"]["wig_focus"] + result["sample"]["props"])
            for result in results
        ).lower()
        ok = bool(results) and all(result["sample"]["creative_type"] == case["creative_type"] for result in results)
        if expected:
            ok = ok and any(tag in haystack for tag in expected)
        passed += int(ok)
        details.append({"id": case["id"], "passed": ok, "result_ids": [item["sample"]["id"] for item in results]})
    total = len(cases)
    score = passed / total if total else 0.0
    report = {"passed": passed, "total": total, "score": round(score, 3), "target": 0.8, "details": details}
    _json(report)
    return 0 if score >= 0.8 else 1


def command_prepare(args: argparse.Namespace) -> int:
    incoming = load_json(Path(args.request))
    if args.subject_image:
        incoming["subject_asset"] = asset_descriptor(Path(args.subject_image))
    if args.background_image:
        incoming["background_asset"] = asset_descriptor(Path(args.background_image))
    state_path = Path(args.state) if args.state else None
    state = load_session(state_path)
    updated, report = prepare_request(incoming, state)
    target = save_session(updated, state_path)
    report["session_state"] = str(target)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["output"] = str(output)
    _json(report)
    return 1 if report["requires_confirmation"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wig-rag", description="AI 假发提示词 RAG 工作台")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查本地运行环境")
    doctor.set_defaults(func=command_doctor)
    status = subparsers.add_parser("status", help="查看语料与索引状态")
    status.set_defaults(func=command_status)

    ingest = subparsers.add_parser("ingest", help="把 DOCX/Markdown/TXT 转成待审核 CSV")
    ingest.add_argument("--input", required=True)
    ingest.add_argument("--output")
    ingest.set_defaults(func=command_ingest)

    promote = subparsers.add_parser("promote", help="把审核通过的 CSV 记录合并到共享语料")
    promote.add_argument("--review-file", required=True)
    promote.set_defaults(func=command_promote)

    index = subparsers.add_parser("index", help="建立或重建本地向量索引")
    index.add_argument("--review-file")
    index.set_defaults(func=command_index)

    retrieve_parser = subparsers.add_parser("retrieve", help="检索已审核样例")
    retrieve_parser.add_argument("--creative-type", required=True, choices=sorted(CREATIVE_TYPES))
    retrieve_parser.add_argument("--query", required=True)
    retrieve_parser.add_argument("--top-k", type=int, default=3)
    retrieve_parser.add_argument("--no-auto-index", action="store_true")
    retrieve_parser.set_defaults(func=command_retrieve)

    prepare = subparsers.add_parser("prepare", help="合并图片观察、用户要求和跨轮纠错")
    prepare.add_argument("--request", required=True)
    prepare.add_argument("--subject-image")
    prepare.add_argument("--background-image")
    prepare.add_argument("--state")
    prepare.add_argument("--output")
    prepare.set_defaults(func=command_prepare)

    assemble = subparsers.add_parser("assemble", help="拼接固定规则并校验 Codex 草稿")
    assemble.add_argument("--request", required=True)
    assemble.add_argument("--draft", required=True)
    assemble.add_argument("--output")
    assemble.set_defaults(func=command_assemble)

    validate = subparsers.add_parser("validate", help="校验最终 Markdown")
    validate.add_argument("--input", required=True)
    validate.add_argument("--duration", type=int)
    validate.set_defaults(func=command_validate)

    evaluate = subparsers.add_parser("evaluate", help="运行 10 个标准检索案例")
    evaluate.add_argument("--cases")
    evaluate.set_defaults(func=command_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (WorkbenchError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
