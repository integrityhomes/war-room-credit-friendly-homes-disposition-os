from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analytics import ClickEvent
from .channels import CHANNELS_BY_KEY
from .dwelyx import build_dwelyx_url
from .models import OwnerFinanceProperty
from .storage import SupabaseSettings

CREATIVE_TEST_BUCKET = "cfh-creative-testing"
CREATIVE_TEST_PATH = "creative-testing/ledger.json"
CREATIVE_TEST_MAX_BYTES = 3 * 1024 * 1024
DEFAULT_MIN_IMPRESSIONS = 100
DEFAULT_MIN_CLICKS = 10
DEFAULT_LIFT_THRESHOLD = Decimal("0.20")
SUPPORTED_CREATIVE_CHANNELS = (
    "email",
    "sms",
    "facebook_groups",
    "meta_ads",
    "google_ads",
    "instagram",
    "tiktok",
    "youtube",
    "classifieds",
)
PRIMARY_METRICS = (
    "Tracked Dwelyx clicks",
    "Inquiries",
    "Applications",
    "Contracts",
)
PROHIBITED_CREATIVE_PHRASES = (
    "guaranteed approval",
    "everyone approved",
    "no credit check",
    "instant approval",
    "safe neighborhood",
    "crime-free",
    "perfect for families",
    "best schools",
    "preferred buyer",
    "move-in ready",
    "move in ready",
)


class CreativeTestingError(RuntimeError):
    """Raised when a creative test cannot be created, scored, or saved."""


class ExperimentStatus(StrEnum):
    DRAFT = "Draft"
    RUNNING = "Running"
    WINNER_READY = "Winner Ready"
    WINNER_APPROVED = "Winner Approved"
    PAUSED = "Paused"
    COMPLETED = "Completed"


class VariantStatus(StrEnum):
    ACTIVE = "Active"
    WINNER = "Winner"
    RETIRED = "Retired"


class CreativeVariant(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    variant_id: str = Field(default_factory=lambda: str(uuid4()))
    key: str = Field(min_length=1, max_length=8)
    label: str = Field(min_length=2, max_length=120)
    angle: str = Field(min_length=2, max_length=180)
    copy: str = Field(min_length=10, max_length=6000)
    tracked_link: str = Field(min_length=8, max_length=1000)
    campaign: str = Field(min_length=3, max_length=160)
    allocation_percent: int = Field(default=25, ge=0, le=100)
    is_control: bool = False
    status: VariantStatus = VariantStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreativeOutcomeRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    experiment_id: str
    variant_id: str
    period_start: date
    period_end: date
    impressions: int = Field(default=0, ge=0)
    reported_clicks: int = Field(default=0, ge=0)
    inquiries: int = Field(default=0, ge=0)
    applications: int = Field(default=0, ge=0)
    contracts: int = Field(default=0, ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str = Field(default="", max_length=1200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_dates(self) -> CreativeOutcomeRecord:
        if self.period_end < self.period_start:
            raise ValueError("Period end must be on or after period start")
        return self


class CreativeExperiment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=3, max_length=180)
    property_id: str
    property_address: str = Field(min_length=2, max_length=300)
    channel_key: str
    channel_name: str
    test_element: str = Field(default="opening_angle", min_length=3, max_length=100)
    primary_metric: str = "Tracked Dwelyx clicks"
    status: ExperimentStatus = ExperimentStatus.DRAFT
    variants: list[CreativeVariant] = Field(min_length=2, max_length=4)
    minimum_impressions_per_variant: int = Field(default=DEFAULT_MIN_IMPRESSIONS, ge=10, le=1000000)
    minimum_clicks_per_variant: int = Field(default=DEFAULT_MIN_CLICKS, ge=1, le=100000)
    winner_lift_threshold: Decimal = Field(default=DEFAULT_LIFT_THRESHOLD, ge=0, le=5)
    winner_variant_id: str = ""
    winner_approved_by: str = ""
    winner_approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_experiment(self) -> CreativeExperiment:
        if self.channel_key not in SUPPORTED_CREATIVE_CHANNELS:
            raise ValueError("This marketing channel is not supported by the creative testing engine")
        if self.primary_metric not in PRIMARY_METRICS:
            raise ValueError("Unsupported winner metric")
        keys = [variant.key for variant in self.variants]
        if len(set(keys)) != len(keys):
            raise ValueError("Creative variant keys must be unique")
        if sum(variant.allocation_percent for variant in self.variants) != 100:
            raise ValueError("Creative variant allocations must total 100 percent")
        return self


class CreativeTestingLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    experiments: list[CreativeExperiment] = Field(default_factory=list)
    outcomes: list[CreativeOutcomeRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    variant_id: str
    key: str
    label: str
    impressions: int
    reported_clicks: int
    tracked_clicks: int
    usable_clicks: int
    inquiries: int
    applications: int
    contracts: int
    spend: Decimal
    primary_total: int
    primary_rate: float
    cost_per_inquiry: Decimal | None
    cost_per_application: Decimal | None


@dataclass(frozen=True, slots=True)
class WinnerRecommendation:
    ready: bool
    winner_variant_id: str
    winner_key: str
    runner_up_key: str
    lift_percent: float
    confidence: str
    reason: str
    metrics: tuple[VariantMetrics, ...]


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def _safe_facts(property_record: OwnerFinanceProperty) -> dict[str, str]:
    return {
        "address": property_record.display_address,
        "down": _money(property_record.down_payment),
        "monthly": _money(property_record.monthly_payment),
        "condition": property_record.condition_summary
        or "Buyers should independently inspect and verify the property's condition.",
        "repairs": property_record.repairs_needed
        or "No repair statement was provided; buyers should verify needed work.",
        "disclosures": property_record.public_disclosures
        or "Property information, condition, terms, and availability must be verified.",
    }


def _variant_opening(angle_index: int, facts: Mapping[str, str]) -> str:
    openings = (
        f"Owner-finance home available at {facts['address']}.",
        f"Current owner-finance payment shown for {facts['address']}: {facts['monthly']} per month.",
        f"Current down payment shown for {facts['address']}: {facts['down']}.",
        f"Condition-first review for {facts['address']}: {facts['condition']}",
    )
    return openings[angle_index % len(openings)]


def _email_copy(opening: str, facts: Mapping[str, str], tracked_link: str) -> str:
    subject = opening[:150].rstrip(".")
    return (
        f"Subject: {subject}\n\n"
        f"{opening}\n\n"
        f"Down payment: {facts['down']}\n"
        f"Monthly owner-finance payment: {facts['monthly']}\n"
        "The monthly payment shown is not rent.\n\n"
        f"Condition: {facts['condition']}\n"
        f"Known repairs or work needed: {facts['repairs']}\n"
        f"Disclosures: {facts['disclosures']}\n\n"
        f"Review current details and availability through your Dwelyx buyer account: {tracked_link}\n\n"
        "Approval, terms, property condition, and availability are subject to review and verification. "
        "Equal Housing Opportunity. Use the sender's unsubscribe process to stop email updates."
    )


def _sms_copy(opening: str, facts: Mapping[str, str], tracked_link: str) -> str:
    return (
        f"{opening} {facts['down']} down; {facts['monthly']}/mo owner-finance payment, not rent. "
        f"Review current details: {tracked_link} Reply STOP to opt out."
    )


def _social_copy(opening: str, facts: Mapping[str, str], tracked_link: str) -> str:
    return (
        f"{opening}\n\n"
        f"Down payment: {facts['down']}\n"
        f"Monthly owner-finance payment: {facts['monthly']}\n"
        "The monthly payment shown is not rent.\n\n"
        f"Condition: {facts['condition']}\n"
        f"Known repairs or work needed: {facts['repairs']}\n"
        f"Disclosures: {facts['disclosures']}\n\n"
        f"Review current details and availability through Dwelyx: {tracked_link}\n\n"
        "Approval, terms, property condition, and availability are subject to review and verification. "
        "Equal Housing Opportunity."
    )


def _video_copy(opening: str, facts: Mapping[str, str], tracked_link: str) -> str:
    return (
        f"Video hook: {opening}\n\n"
        f"Script: This property currently shows {facts['down']} down and a {facts['monthly']} monthly "
        "owner-finance payment. That monthly payment is not rent. "
        f"The recorded condition is: {facts['condition']} Known work: {facts['repairs']} "
        f"Review current details and availability through Dwelyx at {tracked_link}. "
        "Approval, terms, property condition, and availability are subject to review and verification. "
        "Equal Housing Opportunity."
    )


def _copy_for_channel(
    channel_key: str,
    opening: str,
    facts: Mapping[str, str],
    tracked_link: str,
) -> str:
    if channel_key == "email":
        return _email_copy(opening, facts, tracked_link)
    if channel_key == "sms":
        return _sms_copy(opening, facts, tracked_link)
    if channel_key in {"tiktok", "youtube"}:
        return _video_copy(opening, facts, tracked_link)
    return _social_copy(opening, facts, tracked_link)


def validate_variant_copy(
    variant: CreativeVariant,
    property_record: OwnerFinanceProperty,
) -> list[str]:
    errors: list[str] = []
    lowered = variant.copy.casefold()
    facts = _safe_facts(property_record)
    if facts["address"].casefold() not in lowered:
        errors.append("The complete property address is missing.")
    if property_record.down_payment is None or facts["down"] not in variant.copy:
        errors.append("The exact down payment is missing.")
    if property_record.monthly_payment is None or facts["monthly"] not in variant.copy:
        errors.append("The exact monthly payment is missing.")
    if "not rent" not in lowered:
        errors.append('The copy must state that the monthly payment is "not rent."')
    if property_record.total_price is not None and _money(property_record.total_price) in variant.copy:
        errors.append("The total purchase price must not appear in public test copy.")
    if variant.copy.count(variant.tracked_link) != 1:
        errors.append("The tracked Dwelyx link must appear exactly once.")
    for phrase in PROHIBITED_CREATIVE_PHRASES:
        if phrase in lowered:
            errors.append(f"Prohibited phrase detected: {phrase}")
    return sorted(set(errors))


def build_creative_experiment(
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
    *,
    channel_key: str,
    primary_metric: str = "Tracked Dwelyx clicks",
    test_element: str = "opening_angle",
    minimum_impressions_per_variant: int = DEFAULT_MIN_IMPRESSIONS,
    minimum_clicks_per_variant: int = DEFAULT_MIN_CLICKS,
    winner_lift_threshold: Decimal | str = DEFAULT_LIFT_THRESHOLD,
    name: str = "",
    now: datetime | None = None,
) -> CreativeExperiment:
    if channel_key not in SUPPORTED_CREATIVE_CHANNELS:
        raise CreativeTestingError("Choose a supported email, SMS, social, ad, video, or classified channel.")
    if channel_key == "marketplace":
        raise CreativeTestingError("Facebook Marketplace is excluded from automatic creative rotation.")
    if primary_metric not in PRIMARY_METRICS:
        raise CreativeTestingError("Choose a supported business outcome metric.")
    if property_record.down_payment is None or property_record.monthly_payment is None:
        raise CreativeTestingError("The property needs exact down payment and monthly payment before testing copy.")

    timestamp = now or datetime.now(UTC)
    experiment_id = str(uuid4())
    facts = _safe_facts(property_record)
    angles = (
        "Address first",
        "Monthly payment first",
        "Down payment first",
        "Condition transparency first",
    )
    variants: list[CreativeVariant] = []
    for index, angle in enumerate(angles):
        key = chr(ord("A") + index)
        campaign = f"creative_{experiment_id[:8]}_{key.lower()}"
        tracked_link = build_dwelyx_url(
            dwelyx_url,
            source="credit_friendly_homes",
            medium=channel_key,
            campaign=campaign,
            property_id=property_record.property_id,
        )
        opening = _variant_opening(index, facts)
        variant = CreativeVariant(
            key=key,
            label=f"Variant {key}",
            angle=angle,
            copy=_copy_for_channel(channel_key, opening, facts, tracked_link),
            tracked_link=tracked_link,
            campaign=campaign,
            allocation_percent=25,
            is_control=index == 0,
            created_at=timestamp,
        )
        errors = validate_variant_copy(variant, property_record)
        if errors:
            raise CreativeTestingError("Creative fact guard blocked a variant: " + "; ".join(errors))
        variants.append(variant)

    channel_name = CHANNELS_BY_KEY[channel_key].name
    return CreativeExperiment(
        experiment_id=experiment_id,
        name=name.strip() or f"{channel_name} opening-angle test — {property_record.display_address}",
        property_id=str(property_record.property_id),
        property_address=property_record.display_address,
        channel_key=channel_key,
        channel_name=channel_name,
        test_element=test_element,
        primary_metric=primary_metric,
        variants=variants,
        minimum_impressions_per_variant=minimum_impressions_per_variant,
        minimum_clicks_per_variant=minimum_clicks_per_variant,
        winner_lift_threshold=Decimal(str(winner_lift_threshold)),
        created_at=timestamp,
        updated_at=timestamp,
    )


def create_experiment(
    ledger: CreativeTestingLedger,
    experiment: CreativeExperiment,
    *,
    now: datetime | None = None,
) -> CreativeTestingLedger:
    active_statuses = {
        ExperimentStatus.DRAFT,
        ExperimentStatus.RUNNING,
        ExperimentStatus.WINNER_READY,
        ExperimentStatus.WINNER_APPROVED,
        ExperimentStatus.PAUSED,
    }
    duplicate = next(
        (
            item
            for item in ledger.experiments
            if item.property_id == experiment.property_id
            and item.channel_key == experiment.channel_key
            and item.test_element == experiment.test_element
            and item.status in active_statuses
        ),
        None,
    )
    if duplicate:
        raise CreativeTestingError(
            "An active creative test already exists for this property, channel, and test element."
        )
    timestamp = now or datetime.now(UTC)
    return ledger.model_copy(
        update={
            "experiments": [*ledger.experiments, experiment],
            "updated_at": timestamp,
        }
    )


def find_experiment(
    ledger: CreativeTestingLedger,
    experiment_id: str,
) -> CreativeExperiment | None:
    return next(
        (item for item in ledger.experiments if item.experiment_id == experiment_id),
        None,
    )


def update_experiment_status(
    ledger: CreativeTestingLedger,
    *,
    experiment_id: str,
    status: ExperimentStatus,
    now: datetime | None = None,
) -> CreativeTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise CreativeTestingError("The selected creative experiment could not be found.")
    timestamp = now or datetime.now(UTC)
    updated = experiment.model_copy(update={"status": status, "updated_at": timestamp})
    experiments = [
        updated if item.experiment_id == experiment_id else item
        for item in ledger.experiments
    ]
    return ledger.model_copy(update={"experiments": experiments, "updated_at": timestamp})


def upsert_outcome(
    ledger: CreativeTestingLedger,
    *,
    experiment_id: str,
    variant_id: str,
    period_start: date,
    period_end: date,
    impressions: int = 0,
    reported_clicks: int = 0,
    inquiries: int = 0,
    applications: int = 0,
    contracts: int = 0,
    spend: Decimal | str = Decimal("0"),
    notes: str = "",
    now: datetime | None = None,
) -> CreativeTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise CreativeTestingError("The selected creative experiment could not be found.")
    if not any(variant.variant_id == variant_id for variant in experiment.variants):
        raise CreativeTestingError("The selected creative variant is not part of this experiment.")
    timestamp = now or datetime.now(UTC)
    existing = next(
        (
            row
            for row in ledger.outcomes
            if row.experiment_id == experiment_id
            and row.variant_id == variant_id
            and row.period_start == period_start
            and row.period_end == period_end
        ),
        None,
    )
    replacement = CreativeOutcomeRecord(
        outcome_id=existing.outcome_id if existing else str(uuid4()),
        experiment_id=experiment_id,
        variant_id=variant_id,
        period_start=period_start,
        period_end=period_end,
        impressions=impressions,
        reported_clicks=reported_clicks,
        inquiries=inquiries,
        applications=applications,
        contracts=contracts,
        spend=Decimal(str(spend or 0)),
        notes=notes,
        created_at=existing.created_at if existing else timestamp,
        updated_at=timestamp,
    )
    outcomes = [
        replacement if existing and row.outcome_id == existing.outcome_id else row
        for row in ledger.outcomes
    ]
    if not existing:
        outcomes.append(replacement)
    return ledger.model_copy(update={"outcomes": outcomes, "updated_at": timestamp})


def _tracked_clicks_by_campaign(
    click_events: Sequence[ClickEvent],
    property_id: str,
) -> Counter[str]:
    return Counter(
        event.campaign
        for event in click_events
        if (not event.property_id or event.property_id == property_id)
    )


def _primary_total(metric: str, *, clicks: int, inquiries: int, applications: int, contracts: int) -> int:
    mapping = {
        "Tracked Dwelyx clicks": clicks,
        "Inquiries": inquiries,
        "Applications": applications,
        "Contracts": contracts,
    }
    return mapping[metric]


def experiment_variant_metrics(
    ledger: CreativeTestingLedger,
    experiment: CreativeExperiment,
    click_events: Sequence[ClickEvent] = (),
) -> tuple[VariantMetrics, ...]:
    click_counts = _tracked_clicks_by_campaign(click_events, experiment.property_id)
    metrics: list[VariantMetrics] = []
    for variant in experiment.variants:
        records = [
            row
            for row in ledger.outcomes
            if row.experiment_id == experiment.experiment_id
            and row.variant_id == variant.variant_id
        ]
        impressions = sum(row.impressions for row in records)
        reported_clicks = sum(row.reported_clicks for row in records)
        tracked_clicks = click_counts.get(variant.campaign, 0)
        usable_clicks = max(reported_clicks, tracked_clicks)
        inquiries = sum(row.inquiries for row in records)
        applications = sum(row.applications for row in records)
        contracts = sum(row.contracts for row in records)
        spend = sum((row.spend for row in records), Decimal("0"))
        primary_total = _primary_total(
            experiment.primary_metric,
            clicks=usable_clicks,
            inquiries=inquiries,
            applications=applications,
            contracts=contracts,
        )
        denominator = impressions if impressions > 0 else max(usable_clicks, 1)
        primary_rate = primary_total / denominator
        metrics.append(
            VariantMetrics(
                variant_id=variant.variant_id,
                key=variant.key,
                label=variant.label,
                impressions=impressions,
                reported_clicks=reported_clicks,
                tracked_clicks=tracked_clicks,
                usable_clicks=usable_clicks,
                inquiries=inquiries,
                applications=applications,
                contracts=contracts,
                spend=spend,
                primary_total=primary_total,
                primary_rate=primary_rate,
                cost_per_inquiry=(spend / inquiries if inquiries else None),
                cost_per_application=(spend / applications if applications else None),
            )
        )
    return tuple(metrics)


def winner_recommendation(
    ledger: CreativeTestingLedger,
    experiment: CreativeExperiment,
    click_events: Sequence[ClickEvent] = (),
) -> WinnerRecommendation:
    metrics = experiment_variant_metrics(ledger, experiment, click_events)
    active = [
        row
        for row in metrics
        if next(
            variant.status for variant in experiment.variants if variant.variant_id == row.variant_id
        )
        != VariantStatus.RETIRED
    ]
    if len(active) < 2:
        return WinnerRecommendation(
            ready=False,
            winner_variant_id="",
            winner_key="",
            runner_up_key="",
            lift_percent=0,
            confidence="Low",
            reason="At least two active variants are required.",
            metrics=metrics,
        )

    sample_ready = all(
        row.impressions >= experiment.minimum_impressions_per_variant
        or row.usable_clicks >= experiment.minimum_clicks_per_variant
        for row in active
    )
    ranked = sorted(
        active,
        key=lambda row: (
            row.primary_rate,
            row.primary_total,
            row.contracts,
            row.applications,
            row.inquiries,
            row.usable_clicks,
        ),
        reverse=True,
    )
    winner, runner_up = ranked[0], ranked[1]
    if runner_up.primary_rate > 0:
        lift = (winner.primary_rate - runner_up.primary_rate) / runner_up.primary_rate
    elif winner.primary_rate > 0:
        lift = 1.0
    else:
        lift = 0.0

    minimum_business_outcome = {
        "Tracked Dwelyx clicks": winner.usable_clicks >= experiment.minimum_clicks_per_variant,
        "Inquiries": winner.inquiries >= 2,
        "Applications": winner.applications >= 2,
        "Contracts": winner.contracts >= 1,
    }[experiment.primary_metric]
    lift_ready = Decimal(str(max(lift, 0))) >= experiment.winner_lift_threshold
    ready = sample_ready and minimum_business_outcome and lift_ready

    total_impressions = sum(row.impressions for row in active)
    total_primary = sum(row.primary_total for row in active)
    confidence = (
        "High"
        if ready and total_impressions >= experiment.minimum_impressions_per_variant * len(active) * 3
        and total_primary >= 20
        else "Medium"
        if ready
        else "Low"
    )
    if not sample_ready:
        reason = (
            "Keep the test running until every active variant reaches the minimum impression or click sample."
        )
    elif not minimum_business_outcome:
        reason = (
            f"Variant {winner.key} currently leads, but it has not produced enough "
            f"{experiment.primary_metric.lower()} to promote safely."
        )
    elif not lift_ready:
        reason = (
            f"Variant {winner.key} leads by {lift * 100:.1f}%, below the required "
            f"{float(experiment.winner_lift_threshold) * 100:.1f}% lift."
        )
    else:
        reason = (
            f"Variant {winner.key} leads Variant {runner_up.key} by {lift * 100:.1f}% on "
            f"{experiment.primary_metric} and has met the sample rule. Manager approval is required."
        )
    return WinnerRecommendation(
        ready=ready,
        winner_variant_id=winner.variant_id if ready else "",
        winner_key=winner.key if ready else "",
        runner_up_key=runner_up.key,
        lift_percent=max(lift, 0) * 100,
        confidence=confidence,
        reason=reason,
        metrics=metrics,
    )


def mark_winner_ready(
    ledger: CreativeTestingLedger,
    *,
    experiment_id: str,
    click_events: Sequence[ClickEvent] = (),
    now: datetime | None = None,
) -> CreativeTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise CreativeTestingError("The selected creative experiment could not be found.")
    recommendation = winner_recommendation(ledger, experiment, click_events)
    if not recommendation.ready:
        raise CreativeTestingError(recommendation.reason)
    timestamp = now or datetime.now(UTC)
    updated = experiment.model_copy(
        update={
            "status": ExperimentStatus.WINNER_READY,
            "winner_variant_id": recommendation.winner_variant_id,
            "updated_at": timestamp,
        }
    )
    experiments = [
        updated if item.experiment_id == experiment_id else item
        for item in ledger.experiments
    ]
    return ledger.model_copy(update={"experiments": experiments, "updated_at": timestamp})


def approve_winner(
    ledger: CreativeTestingLedger,
    *,
    experiment_id: str,
    approved_by: str,
    click_events: Sequence[ClickEvent] = (),
    now: datetime | None = None,
) -> CreativeTestingLedger:
    if not approved_by.strip():
        raise CreativeTestingError("Manager name is required to approve a winner.")
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise CreativeTestingError("The selected creative experiment could not be found.")
    recommendation = winner_recommendation(ledger, experiment, click_events)
    winner_id = experiment.winner_variant_id or recommendation.winner_variant_id
    if not recommendation.ready and not winner_id:
        raise CreativeTestingError(recommendation.reason)
    timestamp = now or datetime.now(UTC)
    active_count = sum(variant.status != VariantStatus.RETIRED for variant in experiment.variants)
    challenger_allocation = 0 if active_count <= 1 else 30 // (active_count - 1)
    remainder = 100 - 70 - challenger_allocation * max(active_count - 1, 0)
    variants: list[CreativeVariant] = []
    remainder_assigned = False
    for variant in experiment.variants:
        if variant.status == VariantStatus.RETIRED:
            variants.append(variant.model_copy(update={"allocation_percent": 0}))
        elif variant.variant_id == winner_id:
            variants.append(
                variant.model_copy(
                    update={
                        "status": VariantStatus.WINNER,
                        "allocation_percent": 70 + remainder,
                    }
                )
            )
            remainder_assigned = True
        else:
            variants.append(
                variant.model_copy(
                    update={
                        "status": VariantStatus.ACTIVE,
                        "allocation_percent": challenger_allocation,
                    }
                )
            )
    if not remainder_assigned:
        raise CreativeTestingError("The recommended winner variant could not be found.")
    updated = experiment.model_copy(
        update={
            "status": ExperimentStatus.WINNER_APPROVED,
            "winner_variant_id": winner_id,
            "winner_approved_by": approved_by.strip(),
            "winner_approved_at": timestamp,
            "variants": variants,
            "updated_at": timestamp,
        }
    )
    experiments = [
        updated if item.experiment_id == experiment_id else item
        for item in ledger.experiments
    ]
    return ledger.model_copy(update={"experiments": experiments, "updated_at": timestamp})


def assigned_variant(
    experiment: CreativeExperiment,
    recipient_key: UUID | str,
) -> CreativeVariant:
    active = [variant for variant in experiment.variants if variant.allocation_percent > 0]
    if not active:
        raise CreativeTestingError("The experiment has no active creative allocation.")
    digest = hashlib.sha256(
        f"{experiment.experiment_id}|{recipient_key}".encode()
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    cumulative = 0
    for variant in active:
        cumulative += variant.allocation_percent
        if bucket < cumulative:
            return variant
    return active[-1]


def allocation_rows(experiment: CreativeExperiment) -> list[dict[str, str | int]]:
    return [
        {
            "Variant": variant.key,
            "Angle": variant.angle,
            "Status": variant.status.value,
            "Traffic Allocation": f"{variant.allocation_percent}%",
            "Campaign": variant.campaign,
        }
        for variant in experiment.variants
    ]


def metric_rows(recommendation: WinnerRecommendation) -> list[dict[str, str | int | float]]:
    rows: list[dict[str, str | int | float]] = []
    for item in recommendation.metrics:
        rows.append(
            {
                "Variant": item.key,
                "Impressions": item.impressions,
                "Reported Clicks": item.reported_clicks,
                "Tracked Clicks": item.tracked_clicks,
                "Usable Clicks": item.usable_clicks,
                "Inquiries": item.inquiries,
                "Applications": item.applications,
                "Contracts": item.contracts,
                "Primary Total": item.primary_total,
                "Primary Rate": round(item.primary_rate * 100, 3),
                "Spend": float(item.spend),
            }
        )
    return rows


class CreativeTestingStore:
    """Private Supabase Storage ledger for creative experiments and outcomes."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise CreativeTestingError("Supabase is not configured for creative testing records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise CreativeTestingError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(CREATIVE_TEST_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    CREATIVE_TEST_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": CREATIVE_TEST_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise CreativeTestingError(
                    "Could not create the private creative-testing bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> CreativeTestingLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(CREATIVE_TEST_BUCKET).download(CREATIVE_TEST_PATH)
        except Exception:
            return CreativeTestingLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return CreativeTestingLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CreativeTestingError("The saved creative-testing ledger could not be read.") from exc

    def save(self, ledger: CreativeTestingLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > CREATIVE_TEST_MAX_BYTES:
            raise CreativeTestingError("The creative-testing ledger is too large to save.")
        try:
            self._client.storage.from_(CREATIVE_TEST_BUCKET).upload(
                path=CREATIVE_TEST_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise CreativeTestingError("Could not save creative-testing records.") from exc
