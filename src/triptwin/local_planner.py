"""Generate and replay minimal schedule changes without inventing external offers."""
from copy import deepcopy
from html import escape
from datetime import datetime

from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


def schedule_options(payload):
    trip = Trip.model_validate(payload)
    before = RiskEngine().analyze(trip)
    overlaps = [risk for risk in before.risks if risk.id.startswith("schedule:overlap:")]
    options = []
    removable = {identifier for risk in overlaps for identifier in risk.affected_event_ids}
    for identifier in sorted(removable - trip.constraints.protected_event_ids):
        # Do not silently discard events that other retained events depend on.
        if any(identifier in event.depends_on or event.transfer_from_event_id == identifier for event in trip.events):
            continue
        proposed = deepcopy(payload)
        removed = next(event for event in trip.events if event.id == identifier)
        proposed["events"] = [event for event in proposed["events"] if event["id"] != identifier]
        if not proposed["events"]:
            continue
        kept_trip = Trip.model_validate(proposed)
        proposed["start"] = min(event.start for event in kept_trip.events).isoformat()
        proposed["end"] = max(event.end for event in kept_trip.events).isoformat()
        proposed["version"] = f"{int(trip.version.split('.')[0]) + 1}.0"
        verified = Trip.model_validate(proposed)
        after = RiskEngine().analyze(verified)
        before_ids = {risk.id for risk in before.risks}
        if after.risk_count >= before.risk_count or any(risk.id not in before_ids for risk in after.risks):
            continue
        last = max(verified.events, key=lambda event: event.end)
        destination = last.destination or last.location
        options.append({
            "id": identifier, "label": "保留前往" + (destination.name if destination else last.title) + "的行程",
            "removed_title": removed.title, "trip": verified.model_dump(mode="json"),
            "before_risks": before.risk_count, "after_risks": after.risk_count,
            "known_cost": str(after.budget.known_cost_cny), "arrival": last.end.isoformat(),
            "protected": sorted(trip.constraints.protected_event_ids),
        })
    return options


def options_markdown(payload, options):
    original = RiskEngine().analyze(Trip.model_validate(payload))
    lines = ["### 可选择的 Plan B · 已完成本地回放复检", "",
             f"原方案：{len(payload['events'])} 段行程，{original.risk_count} 个风险，已知票面金额 ¥{original.budget.known_cost_cny}。",
             "同一时刻前往不同目的地，需要您先选择保留哪个目的地。以下方案只调整页面上的行程，不实际退改订单。", "",
             "| 方案 | 从计划中移除 | 最后到达时间 | 保留行程票面金额 | 本地风险变化 |",
             "|---|---|---|---|---|"]
    for option in options:
        arrival = datetime.fromisoformat(option["arrival"]).strftime("%m/%d %H:%M")
        lines.append(f"| {escape(option['label'])} | {escape(option['removed_title'])} | {arrival} | ¥{option['known_cost']} | {option['before_risks']} → {option['after_risks']} |")
    lines += ["", "- 两个方案均保留受保护行程；结构、引用、日期、预算及衔接规则已重新检查。",
              "- 未新增购票费用；移除订单的实际退款和手续费未知，上表不是退款后实际支出。",
              "- 这些是现有行程的局部调整方案，没有查询新车次余票、天气或实时交通。",
              "- 如果两座城市都必须去，需要查询新的车次并核验时刻、价格与余票，不能只把截图里的出发时间改晚。",
              "", "选择下方方案并点击“应用到当前行程”，会更新行程、时间线和风险卡片；原方案仍可通过重新载入示例恢复。"]
    return "\n".join(lines)
