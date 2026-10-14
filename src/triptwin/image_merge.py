"""Merge independently transcribed images without asking an LLM to drop conflicts."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from typing import Any


def merge_image_records(records: list[dict], image_hashes: list[str]) -> tuple[dict, list[dict]]:
    """Every image must own a nonempty extraction; only identical files deduplicate."""
    count = len(image_hashes)
    indices = [item.get("image_index") for item in records]
    if len(indices) != count or set(indices) != set(range(1, count + 1)):
        missing = sorted(set(range(1, count + 1)) - set(indices))
        detail = "、".join(f"第 {i} 张" for i in missing) or "图片编号重复或不对应"
        raise ValueError(f"上传 {count} 张图片，但逐图解析未核齐（{detail}）；未生成完整行程，请重新解析或分开上传。")
    records = sorted(records, key=lambda item: item["image_index"])
    base = copy.deepcopy(records[0]["trip"])
    base["trip_id"] = "images-" + image_hashes[0][:12]
    base["title"] = f"我的旅行行程（{count} 张截图）"
    base["events"] = []
    base["risks"] = []
    confidence, low_fields, notes, report = {}, [], [], []
    protected = []
    # Equal journeys in DIFFERENT images may be different passengers' orders.
    # Do not collapse them by departure time, route, model judgement or filename.
    duplicate_files: dict[str, tuple[str, list[int]]] = {}
    global_values: dict[str, list[Any]] = {}
    for record in records:
        index = record["image_index"]
        trip = record["trip"]
        events = trip.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError(f"第 {index} 张图片没有识别到行程，请裁剪订单主体后重新上传；不能忽略该图片并报告 0 风险。")
        original_ids = [event.get("id") for event in events]
        if len(set(original_ids)) != len(original_ids):
            raise ValueError(f"第 {index} 张图片的行程编号重复，请重新解析。")
        id_map = {event["id"]: f"img{index}-event{pos + 1}" for pos, event in enumerate(events)}
        final_positions = []
        facts = _record_facts(events)
        prior = duplicate_files.get(image_hashes[index - 1])
        if prior is not None:
            if facts != prior[0]:
                raise ValueError(f"第 {index} 张图片与前面的文件完全相同，但识别内容不一致；请移除重复图片后重新解析。")
            final_positions = list(prior[1])
            for event, position in zip(events, final_positions):
                base["events"][position]["metadata"]["source_image_indices"].append(index)
                id_map[event["id"]] = base["events"][position]["id"]
        else:
            for event in events:
                current = copy.deepcopy(event)
                current["id"] = id_map[event["id"]]
                current["metadata"] = {**(current.get("metadata") or {}), "source_image_indices": [index]}
                current["depends_on"] = [id_map.get(ref, ref) for ref in current.get("depends_on", [])]
                if current.get("transfer_from_event_id"):
                    current["transfer_from_event_id"] = id_map.get(current["transfer_from_event_id"], current["transfer_from_event_id"])
                final_positions.append(len(base["events"]))
                base["events"].append(current)
            duplicate_files[image_hashes[index - 1]] = (facts, final_positions)
        report.append({"image_index": index, "event_indices": sorted(set(final_positions))})
        protected.extend(id_map.get(ref, ref) for ref in trip.get("constraints", {}).get("protected_event_ids", []))
        for key, value in record.get("field_confidence", {}).items():
            mapped = _map_path(key, final_positions)
            if mapped:
                confidence[mapped] = min(value, confidence.get(mapped, 1.0))
        low_fields.extend(_map_path(key, final_positions) or f"第 {index} 张：{key}"
                          for key in record.get("low_confidence_fields", []))
        notes.extend(f"第 {index} 张：{note}" for note in record.get("notes", []))
        for section in ("constraints", "travelers"):
            for key, value in trip.get(section, {}).items():
                if value is not None and key != "protected_event_ids":
                    global_values.setdefault(f"{section}.{key}", []).append(value)
    for path, values in global_values.items():
        section, key = path.split(".", 1)
        distinct = {json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values}
        if len(distinct) == 1:
            base.setdefault(section, {})[key] = copy.deepcopy(values[0])
        else:
            base.setdefault(section, {})[key] = None
            notes.append(f"多张图片中的 {path} 不一致，请手动补全并确认，不自动选择其中一个值。")
            confidence[path] = 0.0
            low_fields.append(path)
    base.setdefault("constraints", {})["protected_event_ids"] = sorted(set(protected))
    try:
        base["start"] = min((e["start"] for e in base["events"]), key=datetime.fromisoformat)
        base["end"] = max((e["end"] for e in base["events"]), key=datetime.fromisoformat)
    except (KeyError, TypeError, ValueError):
        base["start"] = base["end"] = None
    if len({event["id"] for event in base["events"]}) != len(base["events"]):
        raise ValueError("合并后行程编号重复，未生成完整行程，请重新解析。")
    return {"trip": base, "field_confidence": confidence,
            "low_confidence_fields": list(dict.fromkeys(low_fields)), "notes": notes}, report


def _map_path(path: str, positions: list[int]) -> str | None:
    match = re.match(r"^(?:trip\.)?events(?:\[(\d+)\]|\.(\d+))\.(.+)$", path)
    if match:
        index = int(match.group(1) or match.group(2))
        return f"events[{positions[index]}].{match.group(3)}" if index < len(positions) else None
    return path.removeprefix("trip.")


def _record_facts(events: list[dict]) -> str:
    """Compare whole duplicate files, preserving multiplicity within each image."""
    ids = {event["id"]: index for index, event in enumerate(events)}
    result = []
    for event in events:
        item = {key: value for key, value in event.items() if key not in {"id", "confidence", "metadata"}}
        item["depends_on"] = [ids.get(ref, ref) for ref in item.get("depends_on", [])]
        if item.get("transfer_from_event_id"):
            item["transfer_from_event_id"] = ids.get(item["transfer_from_event_id"], item["transfer_from_event_id"])
        item["metadata"] = {key: value for key, value in (event.get("metadata") or {}).items() if key in {"booking_status", "nights"}}
        result.append(item)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
