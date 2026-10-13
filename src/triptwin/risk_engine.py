"""Deterministic TripGraph risk rules.

The engine deliberately keeps rule evaluation separate from LLM output so the
same input always produces the same risk decisions.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, time
from decimal import Decimal

from triptwin.models import (
    BudgetStatus,
    BudgetSummary,
    EventType,
    Risk,
    RiskSeverity,
    RiskType,
    Trip,
    TripAnalysis,
    TripEvent,
)


SEVERITY_ORDER = {
    RiskSeverity.CRITICAL: 4,
    RiskSeverity.HIGH: 3,
    RiskSeverity.MEDIUM: 2,
    RiskSeverity.LOW: 1,
}


class RiskEngine:
    """Evaluate explainable schedule, budget, mobility and evidence risks."""

    def analyze(self, trip: Trip) -> TripAnalysis:
        event_by_id = {event.id: event for event in trip.events}
        risks: list[Risk] = []

        risks.extend(self._connection_risks(trip, event_by_id))
        risks.extend(self._schedule_risks(trip, event_by_id))
        for event in trip.events:
            if event.metadata.get("booking_status") in {"refunded", "cancelled", "已退票", "已取消"}:
                risks.append(Risk(
                    id=f"booking:{event.id}", risk_type=RiskType.SCHEDULE,
                    severity=RiskSeverity.HIGH, score=80,
                    title="订单已退票或取消，不能作为有效出行凭证",
                    description="截图记录的是已失效订单，请确认有效车票后再规划出行。",
                    affected_event_ids=[event.id], evidence=["订单状态=" + str(event.metadata["booking_status"])],
                    recommendation="上传当前有效订单；不要据此安排乘车或后续衔接。",
                ))
        risks.extend(self._date_risks(trip))
        budget, budget_risks, warnings = self._budget_analysis(trip)
        inferred_risks, inferred_warnings = self._unlinked_transport_connections(trip)
        risks.extend(inferred_risks)
        warnings.extend(inferred_warnings)
        risks.extend(budget_risks)
        risks.extend(self._mobility_risks(trip))
        weather_risks, weather_warnings = self._weather_risks(trip)
        risks.extend(weather_risks)
        warnings.extend(weather_warnings)
        warnings.extend(
            f"{event.id} 的解析置信度为 {event.confidence:.2f}，建议人工核对。"
            for event in trip.events
            if event.confidence < 0.8
        )

        risks.sort(
            key=lambda risk: (-SEVERITY_ORDER[risk.severity], -risk.score, risk.id)
        )

        return TripAnalysis(
            trip_id=trip.trip_id,
            trip_version=trip.version,
            analyzed_at=datetime.now(UTC),
            risks=risks,
            budget=budget,
            total_risk_score=sum(risk.score for risk in risks),
            data_quality_warnings=warnings,
        )

    def _connection_risks(
        self, trip: Trip, event_by_id: dict[str, TripEvent]
    ) -> list[Risk]:
        risks: list[Risk] = []
        for event in trip.events:
            if not event.transfer_from_event_id:
                continue

            previous = event_by_id[event.transfer_from_event_id]
            available = int((event.start - previous.end).total_seconds() // 60)
            route_evidence = event.metadata.get("amap_route_evidence")
            verified_route = (
                route_evidence
                if isinstance(route_evidence, dict)
                and route_evidence.get("status") == "verified"
                else None
            )
            travel = event.travel_minutes_from_previous or 0
            buffer = (
                event.connection_buffer_minutes
                if event.connection_buffer_minutes is not None
                else trip.constraints.minimum_connection_buffer_minutes
            )
            required = travel + buffer
            if available >= required:
                continue

            deficit = required - available
            severity = RiskSeverity.HIGH if deficit >= 20 else RiskSeverity.MEDIUM
            score = 80 if severity is RiskSeverity.HIGH else 60
            evidence = [
                f"可用间隔={available}分钟",
                f"预计路程={travel}分钟",
                f"安全缓冲={buffer}分钟",
                f"缺口={deficit}分钟",
            ]
            if verified_route:
                evidence.extend(
                    [
                        "路线来源=高德地图 MCP/"
                        + str(verified_route.get("source_tool")),
                        "路线获取时间=" + str(verified_route.get("fetched_at")),
                        "路线距离="
                        + str(verified_route.get("distance_meters"))
                        + "米",
                    ]
                )
            risks.append(
                Risk(
                    id=f"time_connection:{previous.id}:{event.id}",
                    risk_type=RiskType.TIME_CONNECTION,
                    severity=severity,
                    score=score,
                    title="行程衔接时间不足",
                    description=(
                        f"从“{previous.title}”结束到“{event.title}”开始只有 "
                        f"{available} 分钟，至少需要 {required} 分钟。"
                    ),
                    affected_event_ids=[previous.id, event.id],
                    evidence=evidence,
                    recommendation="保留原交通节点，顺延或替换后续活动，并重新校验到达时间。",
                    source_tool=str(verified_route.get("source_tool"))
                    if verified_route
                    else None,
                    fetched_at=verified_route.get("fetched_at")
                    if verified_route
                    else None,
                    verification_status="verified"
                    if verified_route
                    else "local_rule",
                )
            )
        return risks

    def _unlinked_transport_connections(self, trip: Trip) -> tuple[list[Risk], list[str]]:
        """Do not silently skip ticket connections when the extractor omits links."""
        ordered = sorted(trip.events, key=lambda event: event.start)
        risks, warnings = [], []
        for previous, current in zip(ordered, ordered[1:]):
            if previous.event_type is not EventType.TRANSPORT or current.event_type is not EventType.TRANSPORT:
                continue
            if current.start < previous.end:
                continue
            origin, destination = current.origin, previous.destination
            if not origin or not destination:
                warnings.append(f"{previous.title} → {current.title}：缺少衔接站点，交通衔接未核验。")
                continue
            minutes = int((current.start - previous.end).total_seconds() // 60)
            if origin.name != destination.name or origin.city != destination.city:
                if not current.transfer_from_event_id or not current.travel_minutes_from_previous:
                    warnings.append(f"{previous.title} → {current.title}：到达地点 {destination.name} 与下一段出发地点 {origin.name} 不同，间隔 {minutes} 分钟；尚无两地交通耗时证据，衔接未核验。")
            elif not current.transfer_from_event_id and minutes < trip.constraints.minimum_connection_buffer_minutes:
                risks.append(Risk(
                    id=f"time_connection:{previous.id}:{current.id}", risk_type=RiskType.TIME_CONNECTION,
                    severity=RiskSeverity.MEDIUM, score=60, title="同站换乘缓冲不足",
                    description=f"{destination.name} 两段车票间隔仅 {minutes} 分钟，低于设定缓冲。",
                    affected_event_ids=[previous.id, current.id],
                    evidence=[f"可用间隔={minutes}分钟", f"安全缓冲={trip.constraints.minimum_connection_buffer_minutes}分钟"],
                    recommendation="确认站内换乘条件；必要时更换后续车次，不能仅修改票面时间。",
                ))
        return risks, warnings

    def _schedule_risks(
        self, trip: Trip, event_by_id: dict[str, TripEvent]
    ) -> list[Risk]:
        risks: list[Risk] = []
        ordered = sorted(trip.events, key=lambda item: item.start)
        for index, event in enumerate(ordered):
            for other in ordered[index + 1 :]:
                if other.start >= event.end:
                    break
                # Accommodation represents a stay window and is allowed to
                # overlap meals/activities inside that stay.
                if EventType.ACCOMMODATION in {event.event_type, other.event_type}:
                    continue
                risks.append(
                    Risk(
                        id=f"schedule:overlap:{event.id}:{other.id}",
                        risk_type=RiskType.SCHEDULE,
                        severity=RiskSeverity.HIGH,
                        score=75,
                        title="行程时间发生重叠",
                        description=f"“{event.title}”与“{other.title}”在时间上重叠。",
                        affected_event_ids=[event.id, other.id],
                        evidence=[
                            f"{event.id}={event.start.isoformat()} 至 {event.end.isoformat()}",
                            f"{other.id}={other.start.isoformat()} 至 {other.end.isoformat()}",
                        ],
                        recommendation=(
                            "选择保留其中一段有效交通，或查询其他时刻的车次/航班；实际退改请自行办理，不能只修改截图中的时间。"
                            if EventType.TRANSPORT in {event.event_type, other.event_type}
                            else "调整其中一个活动的安排，再重新校验交通与预算。"
                        ),
                    )
                )
            for dependency_id in event.depends_on:
                dependency = event_by_id[dependency_id]
                if event.start < dependency.end:
                    risks.append(
                        Risk(
                            id=f"schedule:dependency_order:{dependency.id}:{event.id}",
                            risk_type=RiskType.SCHEDULE,
                            severity=RiskSeverity.HIGH,
                            score=75,
                            title="依赖事件尚未结束",
                            description=f"“{event.title}”开始时，其前置事件“{dependency.title}”尚未结束。",
                            affected_event_ids=[dependency.id, event.id],
                            evidence=[
                                f"前置结束={dependency.end.isoformat()}",
                                f"当前开始={event.start.isoformat()}",
                            ],
                            recommendation="修正事件顺序或时间，确保前置事件完成后再开始。",
                        )
                    )
        return risks

    def _date_risks(self, trip: Trip) -> list[Risk]:
        risks: list[Risk] = []
        for event in trip.events:
            if event.start < trip.start or event.end > trip.end:
                risks.append(
                    Risk(
                        id=f"date_consistency:outside_trip:{event.id}",
                        risk_type=RiskType.DATE_CONSISTENCY,
                        severity=RiskSeverity.HIGH,
                        score=75,
                        title="事件超出旅行日期范围",
                        description=f"“{event.title}”不在本次旅行起止时间内。",
                        affected_event_ids=[event.id],
                        evidence=[
                            f"旅行范围={trip.start.isoformat()} 至 {trip.end.isoformat()}",
                            f"事件范围={event.start.isoformat()} 至 {event.end.isoformat()}",
                        ],
                        recommendation="核对订单日期，修正事件时间或旅行起止日期。",
                    )
                )

        accommodations = [
            event
            for event in trip.events
            if event.event_type is EventType.ACCOMMODATION
        ]
        missing_nights = [
            night
            for night in self._trip_nights(trip.start.date(), trip.end.date())
            if not any(
                hotel.start.date() <= night < hotel.end.date()
                for hotel in accommodations
            )
            and not any(
                event.event_type is EventType.TRANSPORT
                and event.start < datetime.combine(night + timedelta(days=1), time.min, tzinfo=trip.start.tzinfo) < event.end
                for event in trip.events
            )
        ]
        if missing_nights:
            hotel_ids = [hotel.id for hotel in accommodations]
            risks.append(
                Risk(
                    id="date_consistency:missing_accommodation_nights",
                    risk_type=RiskType.DATE_CONSISTENCY,
                    severity=RiskSeverity.HIGH,
                    score=75,
                    title="住宿日期未覆盖全部过夜日期",
                    description="当前酒店入住/退房日期没有覆盖完整行程。",
                    affected_event_ids=hotel_ids,
                    evidence=[
                        "缺少住宿的夜晚="
                        + ", ".join(night.isoformat() for night in missing_nights)
                    ],
                    recommendation="延长现有住宿或补充缺失日期的住宿，再检查预算。",
                )
            )
        return risks

    def _budget_analysis(
        self, trip: Trip
    ) -> tuple[BudgetSummary, list[Risk], list[str]]:
        known_cost = sum(
            (event.cost_cny for event in trip.events if event.cost_cny is not None),
            start=Decimal("0"),
        )
        extra_cost = sum(
            (event.proposed_extra_cost_cny for event in trip.events),
            start=Decimal("0"),
        )
        unknown_ids = [event.id for event in trip.events if event.cost_cny is None]
        projected = known_cost + extra_cost

        exceeds_total = trip.constraints.budget_cny is not None and projected > trip.constraints.budget_cny
        exceeds_extra = extra_cost > trip.constraints.max_plan_b_extra_cost_cny
        if exceeds_total or exceeds_extra:
            status = BudgetStatus.EXCEEDED
        elif unknown_ids or trip.constraints.budget_cny is None:
            status = BudgetStatus.INDETERMINATE
        else:
            status = BudgetStatus.WITHIN_BUDGET

        summary = BudgetSummary(
            known_cost_cny=known_cost,
            proposed_extra_cost_cny=extra_cost,
            projected_known_total_cny=projected,
            budget_limit_cny=trip.constraints.budget_cny,
            plan_b_extra_limit_cny=trip.constraints.max_plan_b_extra_cost_cny,
            unknown_cost_event_ids=unknown_ids,
            status=status,
        )

        warnings: list[str] = []
        if trip.constraints.budget_cny is None:
            warnings.append("未提供总预算，仅汇总已知价格；总预算是否超限保持未核验。")
        if unknown_ids:
            warnings.append(
                "以下事件价格未知，预算结论不能把 null 当作 0："
                + ", ".join(unknown_ids)
            )

        if status is not BudgetStatus.EXCEEDED:
            return summary, [], warnings

        evidence = [
            f"已知成本={known_cost}元",
            f"Plan B新增成本={extra_cost}元",
            f"已知预计总额={projected}元",
            f"总预算上限={trip.constraints.budget_cny}元",
            f"Plan B新增成本上限={trip.constraints.max_plan_b_extra_cost_cny}元",
        ]
        return (
            summary,
            [
                Risk(
                    id="budget:projected_total",
                    risk_type=RiskType.BUDGET,
                    severity=RiskSeverity.HIGH,
                    score=70,
                    title="预算或 Plan B 增量超限",
                    description="当前已知成本与候选替换成本超过用户约束。",
                    affected_event_ids=[
                        event.id
                        for event in trip.events
                        if event.proposed_extra_cost_cny > 0 or (exceeds_total and event.cost_cny is not None and event.cost_cny > 0)
                    ],
                    evidence=evidence,
                    recommendation="选择更低成本的局部替代项，不改变用户明确要求保留的节点。",
                )
            ],
            warnings,
        )

    def _mobility_risks(self, trip: Trip) -> list[Risk]:
        if not trip.travelers.needs_accessible_pacing:
            return []

        events_by_day: dict[date, list[TripEvent]] = defaultdict(list)
        for event in trip.events:
            events_by_day[event.start.date()].append(event)

        risks: list[Risk] = []
        for day, events in sorted(events_by_day.items()):
            walking = sum(event.walking_minutes for event in events)
            activities = sum(
                event.event_type is EventType.ACTIVITY for event in events
            )
            max_transfers = max((event.transfer_count for event in events), default=0)

            violations: list[str] = []
            if walking > trip.constraints.max_daily_walk_minutes:
                violations.append(
                    f"步行{walking}分钟>上限{trip.constraints.max_daily_walk_minutes}分钟"
                )
            if activities > trip.constraints.max_daily_activities:
                violations.append(
                    f"活动{activities}项>上限{trip.constraints.max_daily_activities}项"
                )
            if max_transfers > trip.constraints.max_transfers_per_leg:
                violations.append(
                    f"单段最多换乘{max_transfers}次>上限"
                    f"{trip.constraints.max_transfers_per_leg}次"
                )
            if not violations:
                continue

            risks.append(
                Risk(
                    id=f"mobility:{day.isoformat()}",
                    risk_type=RiskType.MOBILITY,
                    severity=RiskSeverity.MEDIUM,
                    score=55,
                    title="老人友好度不足",
                    description=f"{day.isoformat()} 的行程强度超过同行人约束。",
                    affected_event_ids=[event.id for event in events],
                    evidence=violations,
                    recommendation="减少步行和换乘，保留休息间隔，并优先选择室内或无障碍候选。",
                )
            )
        return risks

    def _weather_risks(self, trip: Trip) -> tuple[list[Risk], list[str]]:
        risks: list[Risk] = []
        warnings: list[str] = []
        adverse_markers = ("雨", "雪", "雷", "台风", "冰雹", "沙尘")
        for event in trip.events:
            if not event.weather_sensitive:
                continue
            evidence = event.metadata.get("amap_weather_evidence")
            if not isinstance(evidence, dict):
                warnings.append(
                    f"{event.id} 为天气敏感活动，但尚无对应日期的高德天气证据。"
                )
                continue
            if evidence.get("status") != "verified":
                warnings.append(
                    f"{event.id} 的天气未核验："
                    + str(evidence.get("warning") or "工具未返回对应日期。")
                )
                continue
            forecast = evidence.get("forecast")
            if not isinstance(forecast, dict):
                continue
            day = str(forecast.get("dayweather") or "")
            night = str(forecast.get("nightweather") or "")
            if not any(marker in day + night for marker in adverse_markers):
                continue
            risks.append(
                Risk(
                    id=f"weather:{event.id}",
                    risk_type=RiskType.WEATHER,
                    severity=RiskSeverity.HIGH,
                    score=70,
                    title="天气可能影响户外活动",
                    description=(
                        f"“{event.title}”对天气敏感，对应日期预报为"
                        f"{day}/{night}。"
                    ),
                    affected_event_ids=[event.id],
                    evidence=[
                        f"活动日期={evidence.get('event_date')}",
                        f"白天/夜间天气={day}/{night}",
                        "天气来源=高德地图 MCP/maps_weather",
                        f"天气获取时间={evidence.get('fetched_at')}",
                    ],
                    recommendation="确认活动是否开放；必要时换为室内候选并重新校验时间与预算。",
                    source_tool=str(evidence.get("source_tool") or "maps_weather"),
                    fetched_at=evidence.get("fetched_at"),
                    verification_status="verified",
                )
            )
        return risks, warnings

    @staticmethod
    def _trip_nights(start: date, end: date) -> list[date]:
        nights: list[date] = []
        current = start
        while current < end:
            nights.append(current)
            current += timedelta(days=1)
        return nights

