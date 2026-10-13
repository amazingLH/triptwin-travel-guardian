"""Locally reviewed, redacted railway examples. No live query is implied."""
from pathlib import Path
from triptwin.models import Trip

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "multi": ["沈阳到大连.png", "大连到秦皇岛.png"],
    "conflict": ["沈阳到大连.png", "大连到秦皇岛.png", "大连到葫芦岛.png"],
}


def example_paths(kind):
    return [ROOT / "assets" / name for name in FILES[kind]]


def example_kind(paths):
    for kind in FILES:
        expected = example_paths(kind)
        if len(paths) == len(expected) and all(path.is_file() for path in expected):
            # Byte matching also handles Gradio's cached copy of the selected examples.
            import hashlib
            signature = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
            if signature == sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in expected):
                return kind
    return None


def example_trip(kind):
    def event(identifier, train, origin, origin_city, dest, dest_city, start, end, price):
        return dict(id=identifier, event_type="transport", title=f"{train} {origin} → {dest}",
                    origin=dict(name=origin + "站", city=origin_city),
                    destination=dict(name=dest + "站", city=dest_city),
                    start=f"2026-10-26T{start}:00+08:00", end=f"2026-10-26T{end}:00+08:00",
                    cost_cny=price, metadata={"booking_status": "confirmed", "evidence": "脱敏截图人工核对"})
    events = [event("train-sy-dl", "K550", "沈阳", "沈阳", "大连", "大连", "01:56", "06:50", "54.5"),
              event("train-dl-qhd", "K715", "大连", "大连", "秦皇岛", "秦皇岛", "09:54", "21:00", "112")]
    events[1].update(depends_on=[events[0]["id"]], transfer_from_event_id=events[0]["id"], travel_minutes_from_previous=0)
    if kind == "conflict":
        events.append(event("train-dl-hld", "车次待确认", "大连", "大连", "葫芦岛", "葫芦岛", "09:54", "19:00", "93"))
        events[-1].update(depends_on=[events[0]["id"]], transfer_from_event_id=events[0]["id"], travel_minutes_from_previous=0)
    return Trip.model_validate(dict(
        trip_id="railway-example-" + kind, version="1.0", title="铁路衔接" + ("冲突" if kind == "conflict" else "正常") + "功能示例",
        start=events[0]["start"], end=events[1]["end"], travelers={"adults": 1},
        constraints={"budget_cny": "2000", "protected_event_ids": [events[0]["id"]]}, events=events,
    )).model_dump(mode="json")


def field_description(path, trip=None):
    import re
    names = {"budget_cny": "用户设定的旅行总预算", "cost_cny": "该项订单或活动价格",
             "start": "开始或出发时间", "end": "结束或到达时间", "title": "行程项目名称",
             "adults": "成人数", "children": "儿童数", "seniors": "老人数",
             "city": "所在城市", "name": "站点或地点名称", "confidence": "该事件的解析可信程度"}
    key = path.split(".")[-1]
    note = names.get(key, "此字段用于描述行程信息，请结合参数名称与结构化行程核对")
    match = re.search(r"events(?:\[(\d+)\]|\.(\d+))", path)
    if match:
        index = int(match.group(1) or match.group(2))
        events = (trip or {}).get("events", [])
        title = events[index].get("title", "") if index < len(events) else ""
        note = f"第 {index + 1} 项行程" + (f"（{title}）" if title else "") + "：" + note
    return note
