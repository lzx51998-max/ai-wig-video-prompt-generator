from __future__ import annotations

import json
import re
from pathlib import Path

from .core import CREATIVE_TYPES, WorkbenchError, project_root


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


def _creative_type_from_material(sections: dict[str, str]) -> str | None:
    material = sections.get("## 素材引用说明", "")
    if "创意类型：室内" in material:
        return "indoor"
    if "创意类型：室外" in material:
        return "outdoor"
    return None


def validate_document(text: str, expected_duration: int | None = None) -> dict:
    errors: list[str] = []
    sections, section_errors = _sections(text)
    errors.extend(section_errors)
    if not sections:
        return {"valid": False, "errors": errors}
    positive_en = _unfence(sections["## English Positive Prompt"])
    positive_zh = _unfence(sections["## 中文正向提示词"])
    transition_reveal = "转场模式：遮挡变装" in sections.get("## 素材引用说明", "")
    if "@背景参考图" not in text:
        errors.append("必须包含 @背景参考图")
    if transition_reveal:
        if "@转场前人物参考图" not in positive_en or "@转场后人物参考图" not in positive_en:
            errors.append("遮挡变装英文正向提示词必须同时引用 @转场前人物参考图 和 @转场后人物参考图")
        if not re.search(r"(?i)(fully|completely)\s+(?:covers?|occludes?)", positive_en):
            errors.append("遮挡变装必须明确镜头被完全遮挡")
        if not re.search(r"(?i)(?:change|switch|transition)[^.]{0,100}(?:only|exclusively)[^.]{0,100}(?:occlusion|covered)", positive_en):
            errors.append("遮挡变装必须明确发型变化只发生在完全遮挡期间")
    elif "@人物参考图" not in text:
        errors.append("普通模式必须包含 @人物参考图")
    if len(positive_en) < 120:
        errors.append("英文正向提示词过短")
    if len(positive_zh) < 60:
        errors.append("中文正向提示词过短")
    lower_en = positive_en.lower()
    for term in FORBIDDEN_EN:
        if term in lower_en and f"no {term}" not in lower_en and f"without {term}" not in lower_en:
            errors.append(f"英文正向提示词包含禁止内容：{term}")
    for term in FORBIDDEN_ZH:
        if term.lower() in positive_zh.lower():
            errors.append(f"中文正向提示词包含禁止内容：{term}")
    errors.extend(_timeline_errors(positive_en, expected_duration))
    creative_type = _creative_type_from_material(sections)
    if creative_type not in CREATIVE_TYPES:
        errors.append("素材引用说明中的创意类型必须是室内或室外")
    if transition_reveal and creative_type == "outdoor":
        errors.append("遮挡变装仅支持室内，室外必须使用普通模式")
    continuous_take = re.search(r"\b(?:one|single)\s+continuous\b[^.]{0,45}\b(?:take|shot)\b", lower_en)
    if creative_type == "outdoor" and not continuous_take:
        errors.append("室外英文正向提示词必须明确一镜到底")
    expected_en, expected_zh = fixed_rules()
    if _unfence(sections["## English Negative Prompt"]) != expected_en:
        errors.append("固定英文负面提示词被删减、改写或重新排序")
    if _unfence(sections["## 中文负面提示词"]) != expected_zh:
        errors.append("固定中文负面提示词被删减、改写或重新排序")
    return {"valid": not errors, "errors": errors}


def normalize_request(request: dict) -> dict:
    resolved = request.get("resolved_request")
    if isinstance(resolved, dict):
        return resolved
    nested = request.get("request")
    if isinstance(nested, dict):
        return nested
    return request


def assemble_document(request: dict, draft: dict) -> str:
    request = normalize_request(request)
    try:
        duration = int(request.get("duration", 10))
    except (TypeError, ValueError) as exc:
        raise WorkbenchError("request.duration 必须是整数") from exc
    if not 8 <= duration <= 12:
        raise WorkbenchError("request.duration 必须在 8–12 秒")
    creative_type = request.get("creative_type")
    if creative_type not in CREATIVE_TYPES:
        raise WorkbenchError("request.creative_type 无效")
    positive_en = str(draft.get("positive_en", "")).strip()
    positive_zh = str(draft.get("positive_zh", "")).strip()
    if not positive_en or not positive_zh:
        raise WorkbenchError("draft 必须包含 positive_en 和 positive_zh")
    negative_en, negative_zh = fixed_rules()
    type_zh = "室内" if creative_type == "indoor" else "室外"
    transition_mode = request.get("transition_mode", "none")
    if transition_mode not in {"none", "occlusion_reveal"}:
        raise WorkbenchError("request.transition_mode 无效")
    if transition_mode == "occlusion_reveal" and creative_type != "indoor":
        raise WorkbenchError("遮挡变装模式仅支持室内")
    if transition_mode == "occlusion_reveal":
        material = (
            f"创意类型：{type_zh}；时长：{duration} 秒；转场模式：遮挡变装。\n"
            "@转场前人物参考图 与 @转场后人物参考图 分别锁定遮挡前后造型，且必须是同一人物；"
            "@背景参考图 是场景、空间和光线的唯一视觉依据。"
        )
    else:
        material = (
            f"创意类型：{type_zh}；时长：{duration} 秒；转场模式：无。\n"
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
