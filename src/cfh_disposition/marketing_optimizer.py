from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .ai_campaign import DEFAULT_OPENAI_MODEL, OPENAI_RESPONSES_URL
from .analytics import ClickEvent
from .channels import CHANNELS, CHANNELS_BY_KEY
from .models import OwnerFinanceProperty
from .storage import SupabaseSettings

MARKETING_OPTIMIZER_BUCKET = "cfh-marketing-optimizer"
MARKETING_OPTIMIZER_PATH = "marketing-optimizer/performance-ledger.json"
MARKETING_OPTIMIZER_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_OPTIMIZER_DAYS = 30
DEFAULT_TIMEOUT_SECONDS = 90
OPENAI_REQUEST_ATTEMPTS = 2

PROHIBITED_OPTIMIZER_PHRASES = (
    "guaranteed approval",
    "everyone approved",
    "no credit check",
    "instant approval",
    "perfect for families",
    "safe neighborhood",
    "crime-free",
    "best schools",
    "preferred buyer",
    "move-in ready",
    "move in ready",
)

ALLOWED_TEST_METRICS = {
    "Tracked Dwelyx clicks",
    "Click-through rate",
    "Inquiries",
    "Applications",
    "Cost per inquiry",
    "Cost per application",
    "Contracts",
}


class MarketingOptimizerError(RuntimeError):
    """Raised when the AI marketing optimizer cannot complete an operation."""


class RecommendationAction(StrEnum):
    SCALE = "Scale"
    KEEP = "Keep Running"
    REPAIR = "Repair Funnel"
    PAUSE = "Pause Spend"
    TEST = "Launch Test"
    COLLECT = "Collect More Data"


class MarketingPerformanceRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    period_start: date
    period_end: date
    property_id: str
    property_address: str = Field(min_length=2, max_length=300)
    channel_key: str
    impressions: int = Field(default=0, ge=0)
    reported_clicks: int = Field(default=0, ge=0)
    inquiries: int = Field(default=0, ge=0)
    applications: int = Field(default=0, ge=0)
    contracts: int = Field(default=0, ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str = Field(default="", max_length=1500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_record(self) -> MarketingPerformanceRecord:
        if self.period_end < self.period_start:
            raise ValueError("Period end must be on or after period start")
        if self.channel_key not in CHANNELS_BY_KEY:
            raise ValueError("Unknown marketing channel")
        return self


class MarketingOptimizerLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    records: list[MarketingPerformanceRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChannelPerformance:
    channel_key: str
    channel_name: str
    impressions: int
    reported_clicks: int
    tracked_clicks: int
    usable_clicks: int
    inquiries: int
    applications: int
    contracts: int
    spend: Decimal
    click_through_rate: float | None
    click_to_inquiry_rate: float | None
    inquiry_to_application_rate: float | None
    cost_per_inquiry: Decimal | None
    cost_per_application: Decimal | None
    action: RecommendationAction
    reason: str
    confidence: str


class MarketingChannelDecision(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel_key: str
    action: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=8, max_length=700)
    seven_day_test: str = Field(min_length=8, max_length=1000)


class MarketingPropertyPriority(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_id: str
    property_address: str = Field(min_length=2, max_length=300)
    priority: str = Field(min_length=2, max_length=50)
    reason: str = Field(min_length=8, max_length=700)
    primary_channel: str
    secondary_channel: str


class MarketingCreativeTest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel_key: str
    test_name: str = Field(min_length=3, max_length=150)
    control_angle: str = Field(min_length=8, max_length=700)
    challenger_angle: str = Field(min_length=8, max_length=700)
    primary_metric: str
    stop_rule: str = Field(min_length=8, max_length=500)


class AIMarketingPlan(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    executive_summary: str = Field(min_length=20, max_length=1600)
    immediate_actions: list[str] = Field(min_length=1, max_length=8)
    channel_decisions: list[MarketingChannelDecision] = Field(min_length=1, max_length=15)
    property_priorities: list[MarketingPropertyPriority] = Field(default_factory=list, max_length=12)
    creative_tests: list[MarketingCreativeTest] = Field(min_length=1, max_length=10)
    measurement_gaps: list[str] = Field(default_factory=list, max_length=10)


MARKETING_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "executive_summary": {"type": "string"},
        "immediate_actions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 8,
        },
        "channel_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "channel_key": {"type": "string"},
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                    "seven_day_test": {"type": "string"},
                },
                "required": ["channel_key", "action", "reason", "seven_day_test"],
            },
            "minItems": 1,
            "maxItems": 15,
        },
        "property_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "property_id": {"type": "string"},
                    "property_address": {"type": "string"},
                    "priority": {"type": "string"},
                    "reason": {"type": "string"},
                    "primary_channel": {"type": "string"},
                    "secondary_channel": {"type": "string"},
                },
                "required": [
                    "property_id",
                    "property_address",
                    "priority",
                    "reason",
                    "primary_channel",
                    "secondary_channel",
                ],
            },
            "maxItems": 12,
        },
        "creative_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "channel_key": {"type": "string"},
                    "test_name": {"type": "string"},
                    "control_angle": {"type": "string"},
                    "challenger_angle": {"type": "string"},
                    "primary_metric": {"type": "string"},
                    "stop_rule": {"type": "string"},
                },
                "required": [
                    "channel_key",
                    "test_name",
                    "control_angle",
                    "challenger_angle",
                    "primary_metric",
                    "stop_rule",
                ],
            },
            "minItems": 1,
            "maxItems": 10,
        },
        "measurement_gaps": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
    },
    "required": [
        "executive_summary",
        "immediate_actions",
        "channel_decisions",
        "property_priorities",
        "creative_tests",
        "measurement_gaps",
    ],
}


@dataclass(frozen=True, slots=True)
class MarketingOptimizerSettings:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> MarketingOptimizerSettings:
        return cls(
            api_key=str(values.get("OPENAI_API_KEY", "")).strip(),
            model=str(values.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)).strip()
            or DEFAULT_OPENAI_MODEL,
        )


def upsert_performance_record(
    ledger: MarketingOptimizerLedger,
    *,
    period_start: date,
    period_end: date,
    property_id: str,
    property_address: str,
    channel_key: str,
    impressions: int = 0,
    reported_clicks: int = 0,
    inquiries: int = 0,
    applications: int = 0,
    contracts: int = 0,
    spend: Decimal | int | float | str = Decimal("0"),
    notes: str = "",
    now: datetime | None = None,
) -> MarketingOptimizerLedger:
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    existing = next(
        (
            record
            for record in ledger.records
            if record.period_start == period_start
            and record.period_end == period_end
            and record.property_id == str(property_id)
            and record.channel_key == channel_key
        ),
        None,
    )
    values = {
        "period_start": period_start,
        "period_end": period_end,
        "property_id": str(property_id),
        "property_address": property_address,
        "channel_key": channel_key,
        "impressions": impressions,
        "reported_clicks": reported_clicks,
        "inquiries": inquiries,
        "applications": applications,
        "contracts": contracts,
        "spend": Decimal(str(spend)),
        "notes": notes,
        "updated_at": timestamp.astimezone(UTC),
    }
    if existing:
        replacement = existing.model_copy(update=values)
        records = [
            replacement if record.record_id == existing.record_id else record
            for record in ledger.records
        ]
    else:
        replacement = MarketingPerformanceRecord(
            **values,
            created_at=timestamp.astimezone(UTC),
        )
        records = [*ledger.records, replacement]
    return ledger.model_copy(
        update={
            "records": records,
            "updated_at": timestamp.astimezone(UTC),
        }
    )


def records_in_period(
    ledger: MarketingOptimizerLedger,
    period_start: date,
    period_end: date,
    property_ids: set[str] | None = None,
) -> list[MarketingPerformanceRecord]:
    return [
        record
        for record in ledger.records
        if record.period_end >= period_start
        and record.period_start <= period_end
        and (property_ids is None or record.property_id in property_ids)
    ]


def clicks_in_period(
    events: Sequence[ClickEvent],
    period_start: date,
    period_end: date,
    property_ids: set[str] | None = None,
) -> list[ClickEvent]:
    return [
        event
        for event in events
        if period_start <= event.occurred_at.date() <= period_end
        and (
            property_ids is None
            or (event.property_id is not None and event.property_id in property_ids)
        )
    ]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _cost(spend: Decimal, outcomes: int) -> Decimal | None:
    return spend / outcomes if outcomes > 0 else None


def recommendation_for_metrics(
    *,
    impressions: int,
    usable_clicks: int,
    inquiries: int,
    applications: int,
    contracts: int,
    spend: Decimal,
) -> tuple[RecommendationAction, str, str]:
    if contracts > 0:
        return (
            RecommendationAction.SCALE,
            "This channel has produced a contract. Increase volume carefully while preserving the current tracking and follow-up path.",
            "High",
        )
    if applications >= 3 and inquiries >= 5:
        return (
            RecommendationAction.SCALE,
            "This channel is producing multiple applications and enough inquiry volume to justify a controlled increase.",
            "High",
        )
    if spend >= Decimal("150") and inquiries == 0:
        return (
            RecommendationAction.PAUSE,
            "Meaningful spend has not produced an inquiry. Stop additional spend until the audience, offer, landing path, or tracking is repaired.",
            "High",
        )
    if usable_clicks >= 20 and inquiries == 0:
        return (
            RecommendationAction.REPAIR,
            "Traffic is reaching the buyer destination but is not turning into inquiries. Test the offer presentation, call to action, and follow-up path.",
            "Medium",
        )
    if impressions >= 500 and usable_clicks < 5:
        return (
            RecommendationAction.REPAIR,
            "The channel has enough exposure to show that the creative or message is not earning attention.",
            "Medium",
        )
    if inquiries >= 3 or applications > 0:
        return (
            RecommendationAction.KEEP,
            "The channel is producing buyer activity. Keep it running while testing one controlled improvement.",
            "Medium",
        )
    if impressions == 0 and usable_clicks == 0 and inquiries == 0 and spend == 0:
        return (
            RecommendationAction.TEST,
            "No measurable campaign activity is recorded. Launch a small tracked test before judging this channel.",
            "Low",
        )
    return (
        RecommendationAction.COLLECT,
        "There is some activity, but not enough outcome data to make a confident scale-or-stop decision.",
        "Low",
    )


def build_channel_performance(
    records: Sequence[MarketingPerformanceRecord],
    click_events: Sequence[ClickEvent],
) -> list[ChannelPerformance]:
    records_by_channel: dict[str, list[MarketingPerformanceRecord]] = defaultdict(list)
    for record in records:
        records_by_channel[record.channel_key].append(record)
    tracked_counts = Counter(event.medium for event in click_events)

    results: list[ChannelPerformance] = []
    for channel in CHANNELS:
        channel_records = records_by_channel.get(channel.key, [])
        impressions = sum(record.impressions for record in channel_records)
        reported_clicks = sum(record.reported_clicks for record in channel_records)
        tracked_clicks = int(tracked_counts.get(channel.key, 0))
        usable_clicks = max(reported_clicks, tracked_clicks)
        inquiries = sum(record.inquiries for record in channel_records)
        applications = sum(record.applications for record in channel_records)
        contracts = sum(record.contracts for record in channel_records)
        spend = sum((record.spend for record in channel_records), Decimal("0"))
        action, reason, confidence = recommendation_for_metrics(
            impressions=impressions,
            usable_clicks=usable_clicks,
            inquiries=inquiries,
            applications=applications,
            contracts=contracts,
            spend=spend,
        )
        results.append(
            ChannelPerformance(
                channel_key=channel.key,
                channel_name=channel.name,
                impressions=impressions,
                reported_clicks=reported_clicks,
                tracked_clicks=tracked_clicks,
                usable_clicks=usable_clicks,
                inquiries=inquiries,
                applications=applications,
                contracts=contracts,
                spend=spend,
                click_through_rate=_rate(usable_clicks, impressions),
                click_to_inquiry_rate=_rate(inquiries, usable_clicks),
                inquiry_to_application_rate=_rate(applications, inquiries),
                cost_per_inquiry=_cost(spend, inquiries),
                cost_per_application=_cost(spend, applications),
                action=action,
                reason=reason,
                confidence=confidence,
            )
        )
    priority = {
        RecommendationAction.SCALE: 0,
        RecommendationAction.REPAIR: 1,
        RecommendationAction.PAUSE: 2,
        RecommendationAction.KEEP: 3,
        RecommendationAction.TEST: 4,
        RecommendationAction.COLLECT: 5,
    }
    return sorted(
        results,
        key=lambda row: (
            priority[row.action],
            -row.contracts,
            -row.applications,
            -row.inquiries,
            -row.usable_clicks,
            row.channel_name,
        ),
    )


def _decimal_text(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _percent_text(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def channel_performance_rows(
    rows: Sequence[ChannelPerformance],
) -> list[dict[str, str | int]]:
    return [
        {
            "Channel": row.channel_name,
            "Decision": row.action.value,
            "Confidence": row.confidence,
            "Impressions": row.impressions,
            "Reported Clicks": row.reported_clicks,
            "Tracked Dwelyx Clicks": row.tracked_clicks,
            "Usable Clicks": row.usable_clicks,
            "Inquiries": row.inquiries,
            "Applications": row.applications,
            "Contracts": row.contracts,
            "Spend": f"${row.spend:,.2f}",
            "CTR": _percent_text(row.click_through_rate),
            "Click → Inquiry": _percent_text(row.click_to_inquiry_rate),
            "Inquiry → Application": _percent_text(
                row.inquiry_to_application_rate
            ),
            "Cost / Inquiry": _decimal_text(row.cost_per_inquiry),
            "Cost / Application": _decimal_text(row.cost_per_application),
            "Why": row.reason,
        }
        for row in rows
    ]


def _property_click_counts(events: Sequence[ClickEvent]) -> Counter[str]:
    return Counter(
        event.property_id for event in events if event.property_id is not None
    )


def optimizer_context(
    properties: Sequence[OwnerFinanceProperty],
    channel_rows: Sequence[ChannelPerformance],
    records: Sequence[MarketingPerformanceRecord],
    click_events: Sequence[ClickEvent],
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    property_clicks = _property_click_counts(click_events)
    record_counts = Counter(record.property_id for record in records)
    return {
        "analysis_period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "business_goal": (
            "Generate qualified buyer traffic and inquiries for owner-finance homes, "
            "then direct buyers to create or log in to a Dwelyx buyer account."
        ),
        "channel_performance": [
            {
                "channel_key": row.channel_key,
                "channel_name": row.channel_name,
                "impressions": row.impressions,
                "reported_clicks": row.reported_clicks,
                "tracked_dwelyx_clicks": row.tracked_clicks,
                "usable_clicks": row.usable_clicks,
                "inquiries": row.inquiries,
                "applications": row.applications,
                "contracts": row.contracts,
                "spend": str(row.spend),
                "click_through_rate": row.click_through_rate,
                "click_to_inquiry_rate": row.click_to_inquiry_rate,
                "inquiry_to_application_rate": row.inquiry_to_application_rate,
                "cost_per_inquiry": (
                    str(row.cost_per_inquiry)
                    if row.cost_per_inquiry is not None
                    else None
                ),
                "cost_per_application": (
                    str(row.cost_per_application)
                    if row.cost_per_application is not None
                    else None
                ),
                "deterministic_decision": row.action.value,
                "deterministic_reason": row.reason,
                "confidence": row.confidence,
            }
            for row in channel_rows
        ],
        "properties": [
            {
                "property_id": str(item.property_id),
                "address": item.display_address,
                "bedrooms": item.bedrooms,
                "bathrooms": (
                    str(item.bathrooms) if item.bathrooms is not None else None
                ),
                "down_payment": (
                    str(item.down_payment) if item.down_payment is not None else None
                ),
                "monthly_payment": (
                    str(item.monthly_payment)
                    if item.monthly_payment is not None
                    else None
                ),
                "condition_summary": item.condition_summary,
                "repairs_needed": item.repairs_needed,
                "public_disclosures": item.public_disclosures,
                "tracked_dwelyx_clicks": property_clicks.get(
                    str(item.property_id), 0
                ),
                "performance_records": record_counts.get(
                    str(item.property_id), 0
                ),
            }
            for item in properties
        ],
        "hard_rules": [
            "Use only the supplied data. Do not invent performance, property facts, or buyer outcomes.",
            "Do not target, exclude, or prefer protected classes or family types.",
            "Do not use neighborhood safety, crime, school-quality, or preferred-buyer claims.",
            "Do not promise approval, a credit outcome, financing, or acceptance.",
            "Do not recommend deceptive engagement, fake accounts, browser bots, spam, or policy evasion.",
            "Do not recommend automatic posting to member-only Facebook Groups.",
            "Keep Facebook Marketplace, Facebook Group, classifieds, and Nextdoor final publishing manual.",
            "Treat Nextdoor paid housing advertising as approval-controlled spending and do not recommend protected-class, hardship, or ZIP-code targeting.",
            "Use tracked Dwelyx links where the platform allows external links.",
            "Recommend one-variable tests with a clear primary metric and stop rule.",
        ],
    }


def _extract_output_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output", []) or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, Mapping):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise MarketingOptimizerError("OpenAI returned no marketing plan text.")


def _request_openai(request: Request, timeout_seconds: int) -> Mapping[str, Any]:
    last_error: URLError | TimeoutError | None = None
    for _attempt in range(OPENAI_REQUEST_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise MarketingOptimizerError(
                f"OpenAI marketing optimizer request failed ({exc.code}): "
                f"{detail[:500]}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise MarketingOptimizerError(
                "OpenAI returned an unreadable marketing plan response."
            ) from exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
    raise MarketingOptimizerError(
        "OpenAI was temporarily unavailable after two attempts. "
        "The deterministic channel decisions remain available."
    ) from last_error


def validate_ai_marketing_plan(
    plan: AIMarketingPlan,
    properties: Sequence[OwnerFinanceProperty],
) -> list[str]:
    errors: list[str] = []
    property_lookup = {
        str(item.property_id): item.display_address for item in properties
    }
    all_text = json.dumps(plan.model_dump(), ensure_ascii=False).casefold()
    for phrase in PROHIBITED_OPTIMIZER_PHRASES:
        if phrase in all_text:
            errors.append(f"Prohibited marketing phrase detected: {phrase}")

    seen_channels: set[str] = set()
    for decision in plan.channel_decisions:
        if decision.channel_key not in CHANNELS_BY_KEY:
            errors.append(
                f"Unknown channel in AI decision: {decision.channel_key}"
            )
        if decision.channel_key in seen_channels:
            errors.append(
                f"Duplicate channel decision: {decision.channel_key}"
            )
        seen_channels.add(decision.channel_key)

    for priority in plan.property_priorities:
        expected_address = property_lookup.get(priority.property_id)
        if expected_address is None:
            errors.append(
                f"Unknown property in AI priority: {priority.property_id}"
            )
        elif priority.property_address != expected_address:
            errors.append(
                f"Property address mismatch for {priority.property_id}"
            )
        for channel_key in (
            priority.primary_channel,
            priority.secondary_channel,
        ):
            if channel_key not in CHANNELS_BY_KEY:
                errors.append(
                    f"Unknown property-priority channel: {channel_key}"
                )

    for test in plan.creative_tests:
        if test.channel_key not in CHANNELS_BY_KEY:
            errors.append(f"Unknown creative-test channel: {test.channel_key}")
        if test.primary_metric not in ALLOWED_TEST_METRICS:
            errors.append(
                f"Unsupported creative-test metric: {test.primary_metric}"
            )
    return sorted(set(errors))


def generate_ai_marketing_plan(
    properties: Sequence[OwnerFinanceProperty],
    channel_rows: Sequence[ChannelPerformance],
    records: Sequence[MarketingPerformanceRecord],
    click_events: Sequence[ClickEvent],
    *,
    period_start: date,
    period_end: date,
    settings: MarketingOptimizerSettings,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> AIMarketingPlan:
    if not settings.configured:
        raise MarketingOptimizerError("OPENAI_API_KEY is not configured.")
    context = optimizer_context(
        properties,
        channel_rows,
        records,
        click_events,
        period_start=period_start,
        period_end=period_end,
    )
    developer_prompt = (
        "You are the Credit Friendly Homes AI marketing optimization director. "
        "Turn the supplied measured results into a practical seven-day marketing plan. "
        "Use only supplied facts and metrics. Do not invent impressions, clicks, inquiries, "
        "applications, contracts, costs, property facts, or platform capabilities. "
        "Preserve every property ID and exact address. Use only channel keys included in the data. "
        "Prioritize buyer traffic, qualified inquiries, applications, contracts, and efficient team work. "
        "Give one decision per channel included in channel_decisions, concise reasons, and one-variable tests. "
        "Use only these primary metrics for creative tests: Tracked Dwelyx clicks, Click-through rate, "
        "Inquiries, Applications, Cost per inquiry, Cost per application, or Contracts. "
        "Never recommend protected-class targeting, family targeting, neighborhood safety claims, crime claims, "
        "school-quality claims, approval guarantees, credit promises, deceptive engagement, fake accounts, "
        "browser automation, spam, policy evasion, automatic posting into member-only Facebook Groups, or "
        "protected-class, hardship, or ZIP-code targeting for Nextdoor housing ads. "
        "Facebook Marketplace, member-only Facebook Group, classifieds, and Nextdoor publication must remain manual. "
        "Nextdoor paid housing-ad spending requires manager approval. Use calm, direct, execution-focused language."
    )
    payload = {
        "model": settings.model,
        "input": [
            {
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": developer_prompt}
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(context, ensure_ascii=False),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "credit_friendly_homes_marketing_plan",
                "description": "A measured seven-day marketing optimization plan.",
                "strict": True,
                "schema": MARKETING_PLAN_SCHEMA,
            }
        },
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response = _request_openai(request, timeout_seconds)
    try:
        raw = json.loads(_extract_output_text(response))
        if not isinstance(raw, Mapping):
            raise TypeError("AI marketing plan was not an object")
        plan = AIMarketingPlan.model_validate(raw)
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        raise MarketingOptimizerError(
            f"OpenAI returned an invalid marketing plan: {exc}"
        ) from exc
    errors = validate_ai_marketing_plan(plan, properties)
    if errors:
        raise MarketingOptimizerError(
            "AI marketing fact guard blocked the plan: " + "; ".join(errors)
        )
    return plan


def build_fallback_marketing_plan(
    properties: Sequence[OwnerFinanceProperty],
    channel_rows: Sequence[ChannelPerformance],
    click_events: Sequence[ClickEvent],
) -> AIMarketingPlan:
    top_rows = list(channel_rows[:5])
    channel_decisions = [
        MarketingChannelDecision(
            channel_key=row.channel_key,
            action=row.action.value,
            reason=row.reason,
            seven_day_test=(
                "Run one tracked version for seven days, change only the opening message or call to action, "
                "and compare the primary outcome against the current version."
            ),
        )
        for row in channel_rows
    ]
    property_clicks = _property_click_counts(click_events)
    primary = top_rows[0].channel_key if top_rows else "facebook_groups"
    secondary = top_rows[1].channel_key if len(top_rows) > 1 else "email"
    property_priorities = [
        MarketingPropertyPriority(
            property_id=str(item.property_id),
            property_address=item.display_address,
            priority=(
                "Protect Momentum"
                if property_clicks.get(str(item.property_id), 0) > 0
                else "Create Demand"
            ),
            reason=(
                "This property has tracked buyer traffic and should receive a focused follow-up test."
                if property_clicks.get(str(item.property_id), 0) > 0
                else "This property has no tracked buyer traffic in the selected period and needs a measured launch test."
            ),
            primary_channel=primary,
            secondary_channel=secondary,
        )
        for item in properties[:12]
    ]
    creative_tests = [
        MarketingCreativeTest(
            channel_key=row.channel_key,
            test_name=f"{row.channel_name} message test",
            control_angle="Use the current factual property presentation and tracked buyer destination.",
            challenger_angle="Lead with the exact down payment and monthly owner-finance payment, then state the condition and next step clearly.",
            primary_metric="Tracked Dwelyx clicks",
            stop_rule="Stop or revise the challenger after a full seven-day run if it produces no improvement and no qualified inquiry signal.",
        )
        for row in top_rows[:3]
    ]
    if not creative_tests:
        creative_tests = [
            MarketingCreativeTest(
                channel_key="facebook_groups",
                test_name="Facebook Group opening-line test",
                control_angle="Use the current fact-safe group post.",
                challenger_angle="Open with the property address, exact down payment, and exact monthly owner-finance payment before the condition details.",
                primary_metric="Tracked Dwelyx clicks",
                stop_rule="Review after seven days and keep only the version that creates more tracked buyer activity without increasing complaints or review issues.",
            )
        ]
    immediate_actions = [
        f"{row.channel_name}: {row.action.value}. {row.reason}"
        for row in top_rows[:5]
    ] or [
        "Launch tracked tests on the channels the team can execute consistently, then enter inquiries, applications, contracts, and spend so the optimizer can make stronger decisions."
    ]
    measurement_gaps: list[str] = []
    if not any(row.inquiries for row in channel_rows):
        measurement_gaps.append(
            "No inquiries are recorded for the selected period. Enter each channel's inquiry count before increasing spend."
        )
    if not any(row.applications for row in channel_rows):
        measurement_gaps.append(
            "No applications are recorded for the selected period. Connect application outcomes back to the originating channel."
        )
    if not any(row.contracts for row in channel_rows):
        measurement_gaps.append(
            "No contracts are attributed to a channel. Record the original source when a buyer converts."
        )
    return AIMarketingPlan(
        executive_summary=(
            "The current plan ranks each marketing channel using tracked Dwelyx clicks and the outcome data entered by the team. "
            "Scale only where buyer outcomes support it, repair traffic that does not convert, and launch small tracked tests where data is missing."
        ),
        immediate_actions=immediate_actions,
        channel_decisions=channel_decisions,
        property_priorities=property_priorities,
        creative_tests=creative_tests,
        measurement_gaps=measurement_gaps,
    )


def history_rows(
    ledger: MarketingOptimizerLedger,
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for record in sorted(
        ledger.records,
        key=lambda item: (item.period_end, item.updated_at),
        reverse=True,
    ):
        rows.append(
            {
                "Start": record.period_start.isoformat(),
                "End": record.period_end.isoformat(),
                "Property": record.property_address,
                "Channel": CHANNELS_BY_KEY[record.channel_key].name,
                "Impressions": record.impressions,
                "Reported Clicks": record.reported_clicks,
                "Inquiries": record.inquiries,
                "Applications": record.applications,
                "Contracts": record.contracts,
                "Spend": f"${record.spend:,.2f}",
                "Notes": record.notes or "—",
            }
        )
    return rows


class MarketingOptimizerStore:
    """Private Supabase-backed marketing performance ledger."""

    def __init__(
        self,
        values: Mapping[str, Any],
        client: Any | None = None,
    ) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise MarketingOptimizerError(
                "Supabase is not configured for the marketing optimizer."
            )
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise MarketingOptimizerError(
                    "Supabase client is not installed."
                ) from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(MARKETING_OPTIMIZER_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    MARKETING_OPTIMIZER_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": MARKETING_OPTIMIZER_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise MarketingOptimizerError(
                    "Could not create the private marketing optimizer bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> MarketingOptimizerLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(
                MARKETING_OPTIMIZER_BUCKET
            ).download(MARKETING_OPTIMIZER_PATH)
        except Exception:
            return MarketingOptimizerLedger()
        try:
            payload = json.loads(
                raw.decode() if isinstance(raw, bytes) else str(raw)
            )
            return MarketingOptimizerLedger.model_validate(payload)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MarketingOptimizerError(
                "The saved marketing performance ledger could not be read."
            ) from exc

    def save(self, ledger: MarketingOptimizerLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > MARKETING_OPTIMIZER_MAX_BYTES:
            raise MarketingOptimizerError(
                "The marketing performance ledger is too large to save."
            )
        try:
            self._client.storage.from_(MARKETING_OPTIMIZER_BUCKET).upload(
                path=MARKETING_OPTIMIZER_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise MarketingOptimizerError(
                "Could not save the marketing performance ledger."
            ) from exc


def default_analysis_period(days: int = DEFAULT_OPTIMIZER_DAYS) -> tuple[date, date]:
    end = datetime.now(UTC).date()
    bounded_days = max(1, min(days, 365))
    return end - timedelta(days=bounded_days - 1), end
