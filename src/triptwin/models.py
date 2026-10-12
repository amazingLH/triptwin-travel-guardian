"""Typed TripGraph models used by the deterministic risk engine."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class EventType(StrEnum):
    TRANSPORT = "transport"
    ACCOMMODATION = "accommodation"
    ACTIVITY = "activity"
    MEAL = "meal"
    TRANSFER = "transfer"


class RiskType(StrEnum):
    TIME_CONNECTION = "time_connection"
    DATE_CONSISTENCY = "date_consistency"
    BUDGET = "budget"
    MOBILITY = "mobility"
    WEATHER = "weather"


class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BudgetStatus(StrEnum):
    WITHIN_BUDGET = "within_budget"
    EXCEEDED = "exceeded"
    INDETERMINATE = "indeterminate"


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TravelerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)
    seniors: int = Field(default=0, ge=0)
    mobility_limitations: list[str] = Field(default_factory=list)

    @property
    def needs_accessible_pacing(self) -> bool:
        return self.seniors > 0 or bool(self.mobility_limitations)


class TripConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_cny: Decimal = Field(gt=0)
    max_plan_b_extra_cost_cny: Decimal = Field(default=Decimal("500"), ge=0)
    minimum_connection_buffer_minutes: int = Field(default=20, ge=0)
    max_daily_walk_minutes: int = Field(default=60, ge=0)
    max_daily_activities: int = Field(default=3, ge=1)
    max_transfers_per_leg: int = Field(default=1, ge=0)
    protected_event_ids: set[str] = Field(default_factory=set)
    preferences: list[str] = Field(default_factory=list)
    avoidances: list[str] = Field(default_factory=list)


class TripEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    event_type: EventType
    title: str = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime
    origin: Location | None = None
    destination: Location | None = None
    location: Location | None = None
    cost_cny: Decimal | None = Field(default=None, ge=0)
    source: str = Field(default="user", min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    depends_on: list[str] = Field(default_factory=list)
    transfer_from_event_id: str | None = None
    travel_minutes_from_previous: int | None = Field(default=None, ge=0)
    connection_buffer_minutes: int | None = Field(default=None, ge=0)
    walking_minutes: int = Field(default=0, ge=0)
    transfer_count: int = Field(default=0, ge=0)
    proposed_extra_cost_cny: Decimal = Field(default=Decimal("0"), ge=0)
    weather_sensitive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_window(self) -> TripEvent:
        if self.end <= self.start:
            raise ValueError("event end must be later than event start")
        if self.transfer_from_event_id and self.travel_minutes_from_previous is None:
            raise ValueError(
                "travel_minutes_from_previous is required when "
                "transfer_from_event_id is set"
            )
        return self


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    risk_type: RiskType
    severity: RiskSeverity
    score: int = Field(ge=0, le=100)
    title: str
    description: str
    affected_event_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    recommendation: str
    source_tool: str | None = None
    fetched_at: AwareDatetime | None = None
    verification_status: str = "local_rule"


class BudgetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    known_cost_cny: Decimal = Field(ge=0)
    proposed_extra_cost_cny: Decimal = Field(ge=0)
    projected_known_total_cny: Decimal = Field(ge=0)
    budget_limit_cny: Decimal = Field(gt=0)
    plan_b_extra_limit_cny: Decimal = Field(ge=0)
    unknown_cost_event_ids: list[str] = Field(default_factory=list)
    status: BudgetStatus


class Trip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+$")
    title: str = Field(min_length=1)
    start: AwareDatetime
    end: AwareDatetime
    travelers: TravelerProfile
    constraints: TripConstraints
    events: list[TripEvent] = Field(min_length=1)
    risks: list[Risk] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> Trip:
        if self.end <= self.start:
            raise ValueError("trip end must be later than trip start")

        event_ids = [event.id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event ids must be unique")

        known_ids = set(event_ids)
        for event in self.events:
            references = set(event.depends_on)
            if event.transfer_from_event_id:
                references.add(event.transfer_from_event_id)
            unknown = sorted(references - known_ids)
            if unknown:
                raise ValueError(
                    f"event {event.id!r} references unknown event ids: {unknown}"
                )
            if event.id in references:
                raise ValueError(f"event {event.id!r} cannot depend on itself")

        return self


class TripAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip_id: str
    trip_version: str
    analyzed_at: datetime
    risks: list[Risk]
    budget: BudgetSummary
    total_risk_score: int = Field(ge=0)
    data_quality_warnings: list[str] = Field(default_factory=list)

    @property
    def risk_count(self) -> int:
        return len(self.risks)

