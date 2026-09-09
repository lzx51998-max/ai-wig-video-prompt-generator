from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import CREATIVE_TYPES, WorkbenchError, state_dir


SESSION_FIELDS = (
    "subject_asset",
    "background_asset",
    "subject_observation",
    "background_observation",
    "usable_props",
    "movement_constraints",
    "uncertainties",
    "overrides",
    "resolved_request",
)


def default_session_path() -> Path:
    return state_dir() / "session_state.json"


def empty_session() -> dict[str, Any]:
    return {
        "subject_asset": {},
        "background_asset": {},
        "subject_observation": {},
        "background_observation": {},
        "usable_props": [],
        "movement_constraints": [],
        "uncertainties": [],
        "overrides": {"subject": {}, "background": {}, "generation": {}, "exclusions": []},
        "resolved_request": {},
    }


def asset_descriptor(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise WorkbenchError(f"参考图不存在：{path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"asset_id": digest, "source_name": path.name}


def load_session(path: Path | None = None) -> dict[str, Any]:
    target = path or default_session_path()
    if not target.exists():
        return empty_session()
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkbenchError(f"无法读取会话状态：{target}") from exc
    if not isinstance(raw, dict):
        raise WorkbenchError("会话状态顶层必须是对象")
    state = empty_session()
    state.update({key: raw[key] for key in SESSION_FIELDS if key in raw})
    state["overrides"] = _normalize_overrides(state.get("overrides"))
    return state


def save_session(state: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _normalize_overrides(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    return {
        "subject": dict(raw.get("subject") or {}),
        "background": dict(raw.get("background") or {}),
        "generation": dict(raw.get("generation") or {}),
        "exclusions": list(raw.get("exclusions") or []),
    }


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def update_session(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(current)
    old_subject = str((state.get("subject_asset") or {}).get("asset_id", ""))
    old_background = str((state.get("background_asset") or {}).get("asset_id", ""))
    new_subject = str((incoming.get("subject_asset") or {}).get("asset_id", old_subject))
    new_background = str((incoming.get("background_asset") or {}).get("asset_id", old_background))

    if old_subject and new_subject and old_subject != new_subject:
        state["subject_observation"] = {}
        state["overrides"]["subject"] = {}
    if old_background and new_background and old_background != new_background:
        state["background_observation"] = {}
        state["usable_props"] = []
        state["movement_constraints"] = []
        state["overrides"]["background"] = {}

    for key in SESSION_FIELDS:
        if key in incoming and key != "overrides":
            state[key] = deepcopy(incoming[key])
    if "overrides" in incoming:
        supplied = _normalize_overrides(incoming["overrides"])
        for scope in ("subject", "background", "generation"):
            state["overrides"][scope] = _deep_merge(state["overrides"][scope], supplied[scope])
        state["overrides"]["exclusions"] = list(dict.fromkeys(state["overrides"]["exclusions"] + supplied["exclusions"]))
    return state


def _blocking_uncertainties(items: Any) -> list[dict[str, Any]]:
    return [item for item in (items or []) if isinstance(item, dict) and item.get("blocks_generation") is True]


def prepare_request(incoming: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = update_session(state, incoming)
    subject = updated.get("subject_observation") or {}
    background = updated.get("background_observation") or {}
    generation = updated["overrides"]["generation"]
    exclusions = set(updated["overrides"]["exclusions"])

    explicit = dict(incoming.get("request") or {})
    image_type = background.get("creative_type")
    if isinstance(image_type, dict):
        image_type = image_type.get("value")
    creative_type = generation.get("creative_type", explicit.get("creative_type", image_type or "indoor"))
    if creative_type not in CREATIVE_TYPES:
        raise WorkbenchError("creative_type 必须是 indoor 或 outdoor")

    props = generation.get("props", explicit.get("props", updated.get("usable_props") or []))
    props = [item for item in props if item not in exclusions]
    resolved = {
        "creative_type": creative_type,
        "duration": int(generation.get("duration", explicit.get("duration", 10))),
        "wig_focus": generation.get("wig_focus", explicit.get("wig_focus", ["overall silhouette", "hair ends"])),
        "body_action": generation.get("body_action", explicit.get("body_action", subject.get("default_body_action", "slight side turn"))),
        "hair_action": generation.get("hair_action", explicit.get("hair_action", subject.get("default_hair_action", "gently arrange the hair once"))),
        "props": props,
        "camera": generation.get("camera", explicit.get("camera", "centered half-body main shot")),
        "movement_constraints": updated.get("movement_constraints") or [],
    }
    if not 8 <= resolved["duration"] <= 12:
        raise WorkbenchError("duration 必须在 8–12 秒")
    blockers = _blocking_uncertainties(updated.get("uncertainties")) + list(incoming.get("conflicts") or [])
    updated["resolved_request"] = resolved
    return updated, {"resolved_request": resolved, "requires_confirmation": bool(blockers), "blockers": blockers}
