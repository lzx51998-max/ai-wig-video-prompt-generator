from __future__ import annotations

import json
import re
from pathlib import Path

from .core import WorkbenchError, project_root


HEADINGS = [
    "## 素材引用说明",
    "## English Positive Prompt",
    "## 中文正向提示词",
    "## English Negative Prompt",
    "## 中文负面提示词",
]

FORBIDDEN_EN = (
    "install the wig",
    "wig installation",
    "apply glue",
    "glue application",
    "trim the lace",
    "cut the lace",
    "discount",
    "coupon",
    "buy now",
    "purchase button",
    "price tag",
)
FORBIDDEN_ZH = ("安装假发", "涂胶", "修剪蕾丝", "揭 lace", "价格", "折扣", "优惠券", "购买按钮")


def fixed_rules() -> tuple[str, str]:
    root = project_root()
    return (
        (root / "rules" / "fixed_negative_en.txt").read_text(encoding="utf-8").strip(),
        (root / "rules" / "fixed_negative_zh.txt").read_text(encoding="utf-8").strip(),
    )


def _sections(text: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    positions = [text.find(heading) for heading in HEADINGS]
    if any(position < 0 for position in positions):
        missing = [heading for heading, position in zip(HEADINGS, positions, strict=True) if position < 0]
        errors.append("缺少章节：" + "、".join(missing))
        return {}, errors
    if positions != sorted(positions):
        errors.append("五个章节顺序不符合 PRD")
        return {}, errors
    result: dict[str, str] = {}
    for index, heading in enumerate(HEADINGS):
        start = positions[index] + len(heading)
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        result[heading] = text[start:end].strip()
    return result, errors


def _unfence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:text)?\s*\n(.*?)\n```", stripped, flags=re.DOTALL)
    return match.group(1).strip() if match else stripped


def _timeline_errors(positive_en: str, expected_duration: int | None) -> list[str]:
    ranges = [
        (int(start), int(end))
        for start, end in re.findall(r"(?i)(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*(?:seconds?|secs?|s)\b", positive_en)
    ]
    if not ranges:
        return ["英文正向提示词缺少可识别的分秒时间轴，例如 0-3 seconds"]
    unique = sorted(set(ranges))
    if unique[0][0] != 0:
        return ["时间轴必须从 0 秒开始"]
    for (_, previous_end), (next_start, _) in zip(unique, unique[1:]):
        if next_start != previous_end:
            return ["时间轴存在空白或重叠，必须连续覆盖完整视频"]
    duration = expected_duration if expected_duration is not None else unique[-1][1]
    errors: list[str] = []
    if not 8 <= duration <= 12:
        errors.append("视频时长必须在 8–12 秒")
    if unique[-1][1] != duration:
        errors.append(f"时间轴必须覆盖到 {duration} 秒")
    return errors


def validate_document(text: str, expected_duration: int | None = None) -> dict:
    errors: list[str] = []
    sections, section_errors = _sections(text)
    errors.extend(section_errors)
    if not sections:
        return {"valid": False, "errors": errors}
    if "@人物参考图" not in text or "@背景参考图" not in text:
        errors.append("必须同时包含 @人物参考图 和 @背景参考图")
    positive_en = _unfence(sections["## English Positive Prompt"])
    positive_zh = _unfence(sections["## 中文正向提示词"])
    if len(positive_en) < 120:
        errors.append("英文正向提示词过短")
    if len(positive_zh) < 60:
        errors.append("中文正向提示词过短")
    lower_en = positive_en.lower()
    for term in FORBIDDEN_EN:
        if term in lower_en:
            errors.append(f"英文正向提示词包含禁止内容：{term}")
    for term in FORBIDDEN_ZH:
        if term.lower() in positive_zh.lower():
            errors.append(f"中文正向提示词包含禁止内容：{term}")
    errors.extend(_timeline_errors(positive_en, expected_duration))
    expected_en, expected_zh = fixed_rules()
    if _unfence(sections["## English Negative Prompt"]) != expected_en:
        errors.append("固定英文负面提示词被删减、改写或重新排序")
    if _unfence(sections["## 中文负面提示词"]) != expected_zh:
        errors.append("固定中文负面提示词被删减、改写或重新排序")
    return {"valid": not errors, "errors": errors}


def assemble_document(request: dict, draft: dict) -> str:
    try:
        duration = int(request.get("duration", 10))
    except (TypeError, ValueError) as exc:
        raise WorkbenchError("request.duration 必须是整数") from exc
    if not 8 <= duration <= 12:
        raise WorkbenchError("request.duration 必须在 8–12 秒")
    creative_type = request.get("creative_type")
    if creative_type not in {"before_after", "finished_showcase"}:
        raise WorkbenchError("request.creative_type 无效")
    positive_en = str(draft.get("positive_en", "")).strip()
    positive_zh = str(draft.get("positive_zh", "")).strip()
    if not positive_en or not positive_zh:
        raise WorkbenchError("draft 必须包含 positive_en 和 positive_zh")
    negative_en, negative_zh = fixed_rules()
    type_zh = "换发前后反差" if creative_type == "before_after" else "成品造型展示"
    material = (
        f"创意类型：{type_zh}；时长：{duration} 秒。\n"
        "@人物参考图 是唯一主角及目标假发的唯一视觉依据；@背景参考图 是场景、空间和光线的唯一视觉依据。"
    )
    return (
        f"## 素材引用说明\n\n{material}\n\n"
        f"## English Positive Prompt\n\n```text\n{positive_en}\n```\n\n"
        f"## 中文正向提示词\n\n```text\n{positive_zh}\n```\n\n"
        f"## English Negative Prompt\n\n```text\n{negative_en}\n```\n\n"
        f"## 中文负面提示词\n\n```text\n{negative_zh}\n```\n"
    )


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkbenchError(f"无法读取 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise WorkbenchError(f"JSON 顶层必须是对象：{path}")
    return value
