from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analytics import ClickEvent
from .channels import CHANNELS, CHANNELS_BY_KEY
from .dwelyx import build_dwelyx_url
from .dwelyx_attribution import (
    STAGE_RANK,
    DwelyxAttributionEvent,
    JourneyStage,
    build_journeys,
)
from .models import OwnerFinanceProperty, PropertyStatus
from .storage import SupabaseSettings

TERMS_TEST_BUCKET = "cfh-property-terms-testing"
TERMS_TEST_PATH = "property-terms-testing/ledger.json"
TERMS_TEST_MAX_BYTES = 4 * 1024 * 1024
ACTIVE_TEST_STATUSES = {
    "Draft",
    "Approved",
    "Active",
    "Review Ready",
    "Revert Approved",
}
PRIMARY_METRICS = ("Registrations", "Applications", "Showings", "Contracts")


class TermsTestingError(RuntimeError):
    """Raised when a property-terms experiment cannot be created or updated."""


class TermsField(StrEnum):
    TOTAL_PRICE = "Total Price"
    DOWN_PAYMENT = "Down Payment"
    MONTHLY_PAYMENT = "Monthly Payment"
    INTEREST_RATE = "Interest Rate"
    TERM_MONTHS = "Term Months"


FIELD_ATTRIBUTE: dict[TermsField, str] = {
    TermsField.TOTAL_PRICE: "total_price",
    TermsField.DOWN_PAYMENT: "down_payment",
    TermsField.MONTHLY_PAYMENT: "monthly_payment",
    TermsField.INTEREST_RATE: "interest_rate",
    TermsField.TERM_MONTHS: "term_months",
}


class TermsExperimentStatus(StrEnum):
    DRAFT = "Draft"
    APPROVED = "Approved"
    ACTIVE = "Active"
    REVIEW_READY = "Review Ready"
    KEEP_APPROVED = "Keep Approved"
    REVERT_APPROVED = "Revert Approved"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class TestPhase(StrEnum):
    CONTROL = "Control"
    CHALLENGER = "Challenger"


class RelaunchTaskStatus(StrEnum):
    READY = "Ready"
    IN_PROGRESS = "In Progress"
    CONFIRMED = "Confirmed"
    FAILED = "Failed"
    NOT_APPLICABLE = "Not Applicable"


class TermsRecommendation(StrEnum):
    KEEP = "Keep Challenger"
    REVERT = "Revert to Original Terms"
    EXTEND = "Extend Test"
    INSUFFICIENT = "Insufficient Data"
    PROTECT_CONTRACT = "Protect Signed Contract"


class TermsSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    total_price: Decimal | None = Field(default=None, ge=0)
    down_payment: Decimal | None = Field(default=None, ge=0)
    monthly_payment: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    term_months: int | None = Field(default=None, ge=1, le=600)


class RelaunchTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel_key: str
    channel_name: str
    operation: str = Field(default="Apply Challenger", max_length=80)
    status: RelaunchTaskStatus = RelaunchTaskStatus.READY
    instruction: str = Field(min_length=5, max_length=1200)
    updated_by: str = Field(default="", max_length=120)
    updated_at: datetime | None = None
    notes: str = Field(default="", max_length=1500)


class TermsOutcomeRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    experiment_id: str
    phase: TestPhase
    period_start: date
    period_end: date
    impressions: int = Field(default=0, ge=0)
    reported_clicks: int = Field(default=0, ge=0)
    inquiries: int = Field(default=0, ge=0)
    registrations: int = Field(default=0, ge=0)
    applications: int = Field(default=0, ge=0)
    showings: int = Field(default=0, ge=0)
    contracts: int = Field(default=0, ge=0)
    filled: int = Field(default=0, ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str = Field(default="", max_length=1500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_period(self) -> TermsOutcomeRecord:
        if self.period_end < self.period_start:
            raise ValueError("Period end must be on or after period start")
        if self.applications > self.registrations and self.registrations > 0:
            raise ValueError("Applications cannot exceed registrations")
        if self.showings > self.applications and self.applications > 0:
            raise ValueError("Showings cannot exceed applications")
        if self.contracts > self.showings and self.showings > 0:
            raise ValueError("Contracts cannot exceed showings")
        if self.filled > self.contracts and self.contracts > 0:
            raise ValueError("Filled homes cannot exceed contracts")
        return self


class TermsExperiment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=3, max_length=220)
    property_id: str
    property_address: str = Field(min_length=2, max_length=320)
    tested_field: TermsField
    control_terms: TermsSnapshot
    challenger_terms: TermsSnapshot
    primary_metric: str = "Applications"
    baseline_start: date
    baseline_end: date
    minimum_test_days: int = Field(default=7, ge=1, le=90)
    minimum_clicks: int = Field(default=10, ge=1, le=100000)
    minimum_registrations: int = Field(default=3, ge=1, le=100000)
    minimum_lift: Decimal = Field(default=Decimal("0.20"), ge=0, le=5)
    objective: str = Field(default="Fill the property faster without weakening the deal unnecessarily.", max_length=1500)
    campaign: str = Field(min_length=3, max_length=180)
    tracked_link: str = Field(min_length=8, max_length=1200)
    status: TermsExperimentStatus = TermsExperimentStatus.DRAFT
    approved_by: str = Field(default="", max_length=120)
    approval_reason: str = Field(default="", max_length=1500)
    approved_at: datetime | None = None
    applied_by: str = Field(default="", max_length=120)
    applied_at: datetime | None = None
    decision: str = Field(default="", max_length=100)
    decision_reason: str = Field(default="", max_length=2000)
    decided_by: str = Field(default="", max_length=120)
    decided_at: datetime | None = None
    rollback_by: str = Field(default="", max_length=120)
    rollback_at: datetime | None = None
    relaunch_tasks: list[RelaunchTask] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_experiment(self) -> TermsExperiment:
        if self.primary_metric not in PRIMARY_METRICS:
            raise ValueError("Unsupported primary metric")
        if self.baseline_end < self.baseline_start:
            raise ValueError("Baseline end must be on or after baseline start")
        changed = changed_terms_fields(self.control_terms, self.challenger_terms)
        expected = FIELD_ATTRIBUTE[self.tested_field]
        if changed != [expected]:
            raise ValueError("A terms experiment must change exactly one selected offer variable")
        keys = [task.channel_key for task in self.relaunch_tasks]
        if self.relaunch_tasks and (len(keys) != len(CHANNELS) or set(keys) != set(CHANNELS_BY_KEY)):
            raise ValueError("Relaunch tasks must contain every current marketing channel")
        validate_terms_snapshot(self.challenger_terms)
        return self


class TermsTestingLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    experiments: list[TermsExperiment] = Field(default_factory=list)
    outcomes: list[TermsOutcomeRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PhaseMetrics:
    phase: TestPhase
    days: int
    impressions: int
    tracked_clicks: int
    reported_clicks: int
    usable_clicks: int
    inquiries: int
    registrations: int
    applications: int
    showings: int
    contracts: int
    filled: int
    spend: Decimal
    primary_total: int
    primary_rate: float
    cost_per_application: Decimal | None


@dataclass(frozen=True, slots=True)
class TermsRecommendationResult:
    recommendation: TermsRecommendation
    sample_ready: bool
    lift_percent: float
    control: PhaseMetrics
    challenger: PhaseMetrics
    reason: str
    confidence: str


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def capture_terms(property_record: OwnerFinanceProperty) -> TermsSnapshot:
    return TermsSnapshot(
        total_price=property_record.total_price,
        down_payment=property_record.down_payment,
        monthly_payment=property_record.monthly_payment,
        interest_rate=property_record.interest_rate,
        term_months=property_record.term_months,
    )


def changed_terms_fields(control: TermsSnapshot, challenger: TermsSnapshot) -> list[str]:
    fields = ("total_price", "down_payment", "monthly_payment", "interest_rate", "term_months")
    return [field for field in fields if getattr(control, field) != getattr(challenger, field)]


def validate_terms_snapshot(snapshot: TermsSnapshot) -> None:
    if snapshot.total_price is not None and snapshot.down_payment is not None:
        if snapshot.down_payment >= snapshot.total_price:
            raise TermsTestingError("Down payment must be lower than total price")
    if snapshot.monthly_payment is not None and snapshot.monthly_payment <= 0:
        raise TermsTestingError("Monthly payment must be greater than zero")
    if snapshot.term_months is not None and snapshot.term_months < 1:
        raise TermsTestingError("Term months must be at least one")


def _coerce_challenger_value(field: TermsField, value: Decimal | int | str) -> Decimal | int:
    if field == TermsField.TERM_MONTHS:
        resolved = int(value)
        if resolved < 1 or resolved > 600:
            raise TermsTestingError("Term months must be between 1 and 600")
        return resolved
    resolved_decimal = Decimal(str(value))
    if resolved_decimal < 0:
        raise TermsTestingError(f"{field.value} cannot be negative")
    if field == TermsField.INTEREST_RATE and resolved_decimal > 100:
        raise TermsTestingError("Interest rate cannot exceed 100 percent")
    if field == TermsField.MONTHLY_PAYMENT and resolved_decimal <= 0:
        raise TermsTestingError("Monthly payment must be greater than zero")
    return resolved_decimal


def _channel_instruction(channel_key: str, channel_name: str, operation: str) -> str:
    if channel_key == "property_page":
        return f"Confirm the saved property record and public page show the {operation.lower()} terms."
    if channel_key == "marketplace":
        return f"Manually update the active Facebook Marketplace listing to the {operation.lower()} terms and confirm the old terms are gone."
    if channel_key == "facebook_groups":
        return f"Update, comment on, or replace active Facebook Group posts so buyers see only the {operation.lower()} terms."
    if channel_key == "nextdoor":
        return f"Update the Nextdoor Business Post and paid housing ad to the {operation.lower()} terms; confirm organic and paid placements separately."
    if channel_key == "classifieds":
        return f"Update each active classified listing to the {operation.lower()} terms and record the listing location."
    return f"Refresh {channel_name} with the approved {operation.lower()} terms and verify the old terms no longer appear."


def build_relaunch_tasks(operation: str, *, now: datetime | None = None) -> list[RelaunchTask]:
    current = _current(now)
    tasks: list[RelaunchTask] = []
    for channel in CHANNELS:
        internal = channel.key == "property_page"
        tasks.append(
            RelaunchTask(
                channel_key=channel.key,
                channel_name=channel.name,
                operation=operation,
                status=(RelaunchTaskStatus.CONFIRMED if internal else RelaunchTaskStatus.READY),
                instruction=_channel_instruction(channel.key, channel.name, operation),
                updated_by=("System" if internal else ""),
                updated_at=(current if internal else None),
                notes=("Property record controls the public page." if internal else ""),
            )
        )
    return tasks


def build_terms_experiment(
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
    *,
    tested_field: TermsField,
    challenger_value: Decimal | int | str,
    baseline_start: date,
    baseline_end: date,
    primary_metric: str = "Applications",
    minimum_test_days: int = 7,
    minimum_clicks: int = 10,
    minimum_registrations: int = 3,
    minimum_lift: Decimal | str = Decimal("0.20"),
    objective: str = "",
    name: str = "",
    now: datetime | None = None,
) -> TermsExperiment:
    if property_record.status not in {PropertyStatus.READY, PropertyStatus.LIVE, PropertyStatus.PAUSED}:
        raise TermsTestingError("Only launch-ready, live, or paused properties can enter a terms test")
    if baseline_end < baseline_start:
        raise TermsTestingError("Baseline end must be on or after baseline start")
    if primary_metric not in PRIMARY_METRICS:
        raise TermsTestingError("Choose registrations, applications, showings, or contracts")
    control = capture_terms(property_record)
    attribute = FIELD_ATTRIBUTE[tested_field]
    current_value = getattr(control, attribute)
    if current_value is None:
        raise TermsTestingError(f"The property needs a saved {tested_field.value.lower()} before testing it")
    resolved = _coerce_challenger_value(tested_field, challenger_value)
    if resolved == current_value:
        raise TermsTestingError("The challenger value must be different from the current value")
    challenger = control.model_copy(update={attribute: resolved})
    validate_terms_snapshot(challenger)
    experiment_id = str(uuid4())
    campaign = f"terms_{experiment_id[:8]}_{attribute}"
    tracked_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="property_terms_test",
        campaign=campaign,
        property_id=property_record.property_id,
    )
    timestamp = _current(now)
    return TermsExperiment(
        experiment_id=experiment_id,
        name=name.strip() or f"{tested_field.value} test — {property_record.display_address}",
        property_id=str(property_record.property_id),
        property_address=property_record.display_address,
        tested_field=tested_field,
        control_terms=control,
        challenger_terms=challenger,
        primary_metric=primary_metric,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        minimum_test_days=minimum_test_days,
        minimum_clicks=minimum_clicks,
        minimum_registrations=minimum_registrations,
        minimum_lift=Decimal(str(minimum_lift)),
        objective=objective.strip() or "Fill the property faster without weakening the deal unnecessarily.",
        campaign=campaign,
        tracked_link=tracked_link,
        relaunch_tasks=build_relaunch_tasks("Apply Challenger", now=timestamp),
        created_at=timestamp,
        updated_at=timestamp,
    )


def create_experiment(
    ledger: TermsTestingLedger,
    experiment: TermsExperiment,
    *,
    now: datetime | None = None,
) -> TermsTestingLedger:
    duplicate = next(
        (
            item
            for item in ledger.experiments
            if item.property_id == experiment.property_id
            and item.tested_field == experiment.tested_field
            and item.status.value in ACTIVE_TEST_STATUSES
        ),
        None,
    )
    if duplicate:
        raise TermsTestingError("An active test already exists for this property and offer variable")
    current = _current(now)
    return ledger.model_copy(
        update={"experiments": [*ledger.experiments, experiment], "updated_at": current}
    )


def find_experiment(ledger: TermsTestingLedger, experiment_id: str) -> TermsExperiment | None:
    return next((item for item in ledger.experiments if item.experiment_id == experiment_id), None)


def _replace_experiment(
    ledger: TermsTestingLedger,
    updated: TermsExperiment,
    *,
    now: datetime | None = None,
) -> TermsTestingLedger:
    current = _current(now)
    experiments = [updated if item.experiment_id == updated.experiment_id else item for item in ledger.experiments]
    return ledger.model_copy(update={"experiments": experiments, "updated_at": current})


def approve_experiment(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    approved_by: str,
    approval_reason: str,
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status != TermsExperimentStatus.DRAFT:
        raise TermsTestingError("Only a draft terms experiment can be approved")
    if len(approved_by.strip()) < 2:
        raise TermsTestingError("Enter the manager approving this terms test")
    if len(approval_reason.strip()) < 5:
        raise TermsTestingError("Enter the business reason for approving this terms test")
    current = _current(now)
    updated = experiment.model_copy(
        update={
            "status": TermsExperimentStatus.APPROVED,
            "approved_by": approved_by.strip(),
            "approval_reason": approval_reason.strip(),
            "approved_at": current,
            "updated_at": current,
        }
    )
    return _replace_experiment(ledger, updated, now=current)


def _property_matches_snapshot(property_record: OwnerFinanceProperty, snapshot: TermsSnapshot) -> bool:
    return capture_terms(property_record) == snapshot


def property_with_terms(
    property_record: OwnerFinanceProperty,
    snapshot: TermsSnapshot,
    *,
    now: datetime | None = None,
) -> OwnerFinanceProperty:
    validate_terms_snapshot(snapshot)
    return property_record.model_copy(
        update={
            "total_price": snapshot.total_price,
            "down_payment": snapshot.down_payment,
            "monthly_payment": snapshot.monthly_payment,
            "interest_rate": snapshot.interest_rate,
            "term_months": snapshot.term_months,
            "updated_at": _current(now),
        }
    )


def apply_challenger(
    ledger: TermsTestingLedger,
    property_record: OwnerFinanceProperty,
    *,
    experiment_id: str,
    applied_by: str,
    now: datetime | None = None,
) -> tuple[TermsTestingLedger, OwnerFinanceProperty]:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status != TermsExperimentStatus.APPROVED:
        raise TermsTestingError("The challenger must be approved before it can be applied")
    if str(property_record.property_id) != experiment.property_id:
        raise TermsTestingError("The selected property does not match this experiment")
    if not _property_matches_snapshot(property_record, experiment.control_terms):
        raise TermsTestingError("The saved property terms changed after this test was created; create a new test from the current record")
    if len(applied_by.strip()) < 2:
        raise TermsTestingError("Enter the team member applying the approved terms")
    current = _current(now)
    updated_property = property_with_terms(property_record, experiment.challenger_terms, now=current)
    updated_experiment = experiment.model_copy(
        update={
            "status": TermsExperimentStatus.ACTIVE,
            "applied_by": applied_by.strip(),
            "applied_at": current,
            "relaunch_tasks": build_relaunch_tasks("Apply Challenger", now=current),
            "updated_at": current,
        }
    )
    return _replace_experiment(ledger, updated_experiment, now=current), updated_property


def rollback_to_control(
    ledger: TermsTestingLedger,
    property_record: OwnerFinanceProperty,
    *,
    experiment_id: str,
    rollback_by: str,
    now: datetime | None = None,
) -> tuple[TermsTestingLedger, OwnerFinanceProperty]:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status != TermsExperimentStatus.REVERT_APPROVED:
        raise TermsTestingError("Management must approve the revert before the original terms can be restored")
    if str(property_record.property_id) != experiment.property_id:
        raise TermsTestingError("The selected property does not match this experiment")
    if not _property_matches_snapshot(property_record, experiment.challenger_terms):
        raise TermsTestingError("The saved property no longer matches the challenger; review the record before rollback")
    if len(rollback_by.strip()) < 2:
        raise TermsTestingError("Enter the team member restoring the original terms")
    current = _current(now)
    restored = property_with_terms(property_record, experiment.control_terms, now=current)
    updated_experiment = experiment.model_copy(
        update={
            "status": TermsExperimentStatus.COMPLETED,
            "rollback_by": rollback_by.strip(),
            "rollback_at": current,
            "relaunch_tasks": build_relaunch_tasks("Restore Original", now=current),
            "updated_at": current,
        }
    )
    return _replace_experiment(ledger, updated_experiment, now=current), restored


def update_relaunch_task(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    channel_key: str,
    status: RelaunchTaskStatus,
    updated_by: str,
    notes: str = "",
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if channel_key not in CHANNELS_BY_KEY:
        raise TermsTestingError("The selected marketing channel is not registered")
    current = _current(now)
    matched = False
    tasks: list[RelaunchTask] = []
    for task in experiment.relaunch_tasks:
        if task.channel_key == channel_key:
            matched = True
            tasks.append(
                task.model_copy(
                    update={
                        "status": status,
                        "updated_by": updated_by.strip(),
                        "updated_at": current,
                        "notes": notes.strip(),
                    }
                )
            )
        else:
            tasks.append(task)
    if not matched:
        raise TermsTestingError("The selected relaunch task could not be found")
    updated = experiment.model_copy(update={"relaunch_tasks": tasks, "updated_at": current})
    return _replace_experiment(ledger, updated, now=current)


def upsert_outcome(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    phase: TestPhase,
    period_start: date,
    period_end: date,
    impressions: int = 0,
    reported_clicks: int = 0,
    inquiries: int = 0,
    registrations: int = 0,
    applications: int = 0,
    showings: int = 0,
    contracts: int = 0,
    filled: int = 0,
    spend: Decimal | str = Decimal("0"),
    notes: str = "",
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    current = _current(now)
    existing = next(
        (
            row
            for row in ledger.outcomes
            if row.experiment_id == experiment_id
            and row.phase == phase
            and row.period_start == period_start
            and row.period_end == period_end
        ),
        None,
    )
    replacement = TermsOutcomeRecord(
        outcome_id=existing.outcome_id if existing else str(uuid4()),
        experiment_id=experiment_id,
        phase=phase,
        period_start=period_start,
        period_end=period_end,
        impressions=impressions,
        reported_clicks=reported_clicks,
        inquiries=inquiries,
        registrations=registrations,
        applications=applications,
        showings=showings,
        contracts=contracts,
        filled=filled,
        spend=Decimal(str(spend or 0)),
        notes=notes,
        created_at=existing.created_at if existing else current,
        updated_at=current,
    )
    outcomes = [
        replacement if existing and row.outcome_id == existing.outcome_id else row
        for row in ledger.outcomes
    ]
    if not existing:
        outcomes.append(replacement)
    return ledger.model_copy(update={"outcomes": outcomes, "updated_at": current})


def _phase_window(
    experiment: TermsExperiment,
    phase: TestPhase,
    *,
    now: datetime,
) -> tuple[datetime, datetime]:
    if phase == TestPhase.CONTROL:
        start = datetime.combine(experiment.baseline_start, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(experiment.baseline_end, datetime.max.time(), tzinfo=UTC)
        return start, end
    start = experiment.applied_at or now
    return _current(start), now


def _journey_counts(events: Sequence[DwelyxAttributionEvent]) -> dict[str, int]:
    journeys = build_journeys([event for event in events if not event.test_mode])
    return {
        "registrations": sum(STAGE_RANK[item.stage] >= STAGE_RANK[JourneyStage.REGISTERED] for item in journeys),
        "applications": sum(STAGE_RANK[item.stage] >= STAGE_RANK[JourneyStage.APPLICATION_SUBMITTED] for item in journeys),
        "showings": sum(STAGE_RANK[item.stage] >= STAGE_RANK[JourneyStage.SHOWING_SCHEDULED] for item in journeys),
        "contracts": sum(STAGE_RANK[item.stage] >= STAGE_RANK[JourneyStage.CONTRACT_SIGNED] for item in journeys),
        "filled": sum(STAGE_RANK[item.stage] >= STAGE_RANK[JourneyStage.FILLED] for item in journeys),
    }


def phase_metrics(
    ledger: TermsTestingLedger,
    experiment: TermsExperiment,
    phase: TestPhase,
    *,
    click_events: Sequence[ClickEvent] = (),
    attribution_events: Sequence[DwelyxAttributionEvent] = (),
    now: datetime | None = None,
) -> PhaseMetrics:
    current = _current(now)
    start, end = _phase_window(experiment, phase, now=current)
    property_clicks = [
        event
        for event in click_events
        if event.property_id == experiment.property_id and start <= event.occurred_at <= end
    ]
    if phase == TestPhase.CHALLENGER:
        property_clicks = [event for event in property_clicks if event.campaign == experiment.campaign]
    tracked_clicks = len(property_clicks)

    events = [
        event
        for event in attribution_events
        if event.cfh_property_id == experiment.property_id and start <= event.occurred_at <= end
    ]
    if phase == TestPhase.CHALLENGER:
        events = [event for event in events if event.campaign == experiment.campaign]
    else:
        events = [event for event in events if event.campaign != experiment.campaign]
    automatic = _journey_counts(events)

    manual = [
        row
        for row in ledger.outcomes
        if row.experiment_id == experiment.experiment_id and row.phase == phase
    ]
    impressions = sum(row.impressions for row in manual)
    reported_clicks = sum(row.reported_clicks for row in manual)
    inquiries = sum(row.inquiries for row in manual)
    registrations = max(automatic["registrations"], sum(row.registrations for row in manual))
    applications = max(automatic["applications"], sum(row.applications for row in manual))
    showings = max(automatic["showings"], sum(row.showings for row in manual))
    contracts = max(automatic["contracts"], sum(row.contracts for row in manual))
    filled = max(automatic["filled"], sum(row.filled for row in manual))
    spend = sum((row.spend for row in manual), Decimal("0"))
    usable_clicks = max(tracked_clicks, reported_clicks)
    primary_mapping = {
        "Registrations": registrations,
        "Applications": applications,
        "Showings": showings,
        "Contracts": contracts,
    }
    primary_total = primary_mapping[experiment.primary_metric]
    denominator = usable_clicks if usable_clicks else impressions
    primary_rate = primary_total / denominator if denominator else 0.0
    days = max(1, int((end - start).total_seconds() // 86400) + 1)
    return PhaseMetrics(
        phase=phase,
        days=days,
        impressions=impressions,
        tracked_clicks=tracked_clicks,
        reported_clicks=reported_clicks,
        usable_clicks=usable_clicks,
        inquiries=inquiries,
        registrations=registrations,
        applications=applications,
        showings=showings,
        contracts=contracts,
        filled=filled,
        spend=spend,
        primary_total=primary_total,
        primary_rate=primary_rate,
        cost_per_application=(spend / applications if applications else None),
    )


def recommendation_for_experiment(
    ledger: TermsTestingLedger,
    experiment: TermsExperiment,
    *,
    click_events: Sequence[ClickEvent] = (),
    attribution_events: Sequence[DwelyxAttributionEvent] = (),
    now: datetime | None = None,
) -> TermsRecommendationResult:
    current = _current(now)
    control = phase_metrics(
        ledger,
        experiment,
        TestPhase.CONTROL,
        click_events=click_events,
        attribution_events=attribution_events,
        now=current,
    )
    challenger = phase_metrics(
        ledger,
        experiment,
        TestPhase.CHALLENGER,
        click_events=click_events,
        attribution_events=attribution_events,
        now=current,
    )
    test_days = (
        max(0, int((current - experiment.applied_at).total_seconds() // 86400))
        if experiment.applied_at
        else 0
    )
    sample_ready = test_days >= experiment.minimum_test_days and (
        challenger.usable_clicks >= experiment.minimum_clicks
        or challenger.registrations >= experiment.minimum_registrations
    )
    if challenger.contracts > 0:
        return TermsRecommendationResult(
            recommendation=TermsRecommendation.PROTECT_CONTRACT,
            sample_ready=True,
            lift_percent=0.0,
            control=control,
            challenger=challenger,
            reason="The challenger produced a signed contract. Finish the buyer file before considering another terms change.",
            confidence="High",
        )
    if not experiment.applied_at:
        return TermsRecommendationResult(
            recommendation=TermsRecommendation.INSUFFICIENT,
            sample_ready=False,
            lift_percent=0.0,
            control=control,
            challenger=challenger,
            reason="The approved challenger has not been applied yet.",
            confidence="Low",
        )
    if not sample_ready:
        return TermsRecommendationResult(
            recommendation=TermsRecommendation.EXTEND,
            sample_ready=False,
            lift_percent=0.0,
            control=control,
            challenger=challenger,
            reason=(
                f"Run the challenger for at least {experiment.minimum_test_days} days and collect either "
                f"{experiment.minimum_clicks} usable clicks or {experiment.minimum_registrations} registrations."
            ),
            confidence="Low",
        )
    if control.primary_rate > 0:
        lift = challenger.primary_rate / control.primary_rate - 1
    elif challenger.primary_total > 0:
        lift = 1.0
    else:
        lift = 0.0
    threshold = float(experiment.minimum_lift)
    if challenger.primary_total == 0 and control.primary_total > 0:
        recommendation = TermsRecommendation.REVERT
        reason = "The challenger reached the minimum sample but produced no primary outcomes while the original terms did."
    elif lift >= threshold:
        recommendation = TermsRecommendation.KEEP
        reason = f"The challenger improved the {experiment.primary_metric.lower()} rate by {lift:.1%}, above the required lift."
    elif lift <= -threshold:
        recommendation = TermsRecommendation.REVERT
        reason = f"The challenger reduced the {experiment.primary_metric.lower()} rate by {abs(lift):.1%}."
    else:
        recommendation = TermsRecommendation.EXTEND
        reason = "The result is inside the decision threshold; extend the test or collect a larger sample."
    confidence = "High" if challenger.usable_clicks >= experiment.minimum_clicks * 2 else "Medium"
    return TermsRecommendationResult(
        recommendation=recommendation,
        sample_ready=True,
        lift_percent=lift,
        control=control,
        challenger=challenger,
        reason=reason,
        confidence=confidence,
    )


def approve_decision(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    decision: TermsRecommendation,
    decided_by: str,
    decision_reason: str,
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status not in {TermsExperimentStatus.ACTIVE, TermsExperimentStatus.REVIEW_READY}:
        raise TermsTestingError("Only an active or review-ready test can receive a management decision")
    if decision not in {TermsRecommendation.KEEP, TermsRecommendation.REVERT}:
        raise TermsTestingError("Management can approve only Keep Challenger or Revert to Original Terms")
    if len(decided_by.strip()) < 2:
        raise TermsTestingError("Enter the manager approving the final decision")
    if len(decision_reason.strip()) < 5:
        raise TermsTestingError("Enter the business reason for the final decision")
    current = _current(now)
    status = (
        TermsExperimentStatus.COMPLETED
        if decision == TermsRecommendation.KEEP
        else TermsExperimentStatus.REVERT_APPROVED
    )
    updated = experiment.model_copy(
        update={
            "status": status,
            "decision": decision.value,
            "decision_reason": decision_reason.strip(),
            "decided_by": decided_by.strip(),
            "decided_at": current,
            "updated_at": current,
        }
    )
    return _replace_experiment(ledger, updated, now=current)


def mark_review_ready(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status != TermsExperimentStatus.ACTIVE:
        raise TermsTestingError("Only an active test can be marked review ready")
    current = _current(now)
    updated = experiment.model_copy(
        update={"status": TermsExperimentStatus.REVIEW_READY, "updated_at": current}
    )
    return _replace_experiment(ledger, updated, now=current)


def cancel_experiment(
    ledger: TermsTestingLedger,
    *,
    experiment_id: str,
    now: datetime | None = None,
) -> TermsTestingLedger:
    experiment = find_experiment(ledger, experiment_id)
    if not experiment:
        raise TermsTestingError("The selected terms experiment could not be found")
    if experiment.status not in {TermsExperimentStatus.DRAFT, TermsExperimentStatus.APPROVED}:
        raise TermsTestingError("Only a draft or unapplied approved test can be cancelled")
    current = _current(now)
    updated = experiment.model_copy(
        update={"status": TermsExperimentStatus.CANCELLED, "updated_at": current}
    )
    return _replace_experiment(ledger, updated, now=current)


def snapshot_rows(experiment: TermsExperiment) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    labels = {
        "total_price": "Total Price",
        "down_payment": "Down Payment",
        "monthly_payment": "Monthly Payment",
        "interest_rate": "Interest Rate",
        "term_months": "Term Months",
    }
    for field, label in labels.items():
        control = getattr(experiment.control_terms, field)
        challenger = getattr(experiment.challenger_terms, field)
        if field in {"total_price", "down_payment", "monthly_payment"}:
            control_text = f"${control:,.0f}" if control is not None else "—"
            challenger_text = f"${challenger:,.0f}" if challenger is not None else "—"
        elif field == "interest_rate":
            control_text = f"{control}%" if control is not None else "—"
            challenger_text = f"{challenger}%" if challenger is not None else "—"
        else:
            control_text = str(control) if control is not None else "—"
            challenger_text = str(challenger) if challenger is not None else "—"
        rows.append(
            {
                "Term": label,
                "Original": control_text,
                "Challenger": challenger_text,
                "Changed": "Yes" if control != challenger else "No",
            }
        )
    return rows


def phase_metric_rows(result: TermsRecommendationResult) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for item in (result.control, result.challenger):
        rows.append(
            {
                "Phase": item.phase.value,
                "Days": item.days,
                "Impressions": item.impressions,
                "Usable Clicks": item.usable_clicks,
                "Registrations": item.registrations,
                "Applications": item.applications,
                "Showings": item.showings,
                "Contracts": item.contracts,
                "Filled": item.filled,
                "Primary Outcomes": item.primary_total,
                "Primary Rate": f"{item.primary_rate:.1%}",
                "Spend": f"${item.spend:,.2f}",
            }
        )
    return rows


def relaunch_task_rows(experiment: TermsExperiment) -> list[dict[str, str]]:
    return [
        {
            "Channel": task.channel_name,
            "Operation": task.operation,
            "Status": task.status.value,
            "Instruction": task.instruction,
            "Updated By": task.updated_by or "—",
            "Updated At": task.updated_at.astimezone().strftime("%Y-%m-%d %I:%M %p") if task.updated_at else "—",
            "Notes": task.notes or "—",
        }
        for task in experiment.relaunch_tasks
    ]


def experiment_history_rows(ledger: TermsTestingLedger) -> list[dict[str, str]]:
    return [
        {
            "Created": item.created_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Property": item.property_address,
            "Test": item.tested_field.value,
            "Status": item.status.value,
            "Approved By": item.approved_by or "—",
            "Applied By": item.applied_by or "—",
            "Decision": item.decision or "—",
            "Decided By": item.decided_by or "—",
            "Rollback By": item.rollback_by or "—",
            "Campaign": item.campaign,
        }
        for item in sorted(ledger.experiments, key=lambda row: row.created_at, reverse=True)
    ]


class TermsTestingStore:
    """Private Supabase Storage ledger for approved property-terms experiments."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise TermsTestingError("Supabase is not configured for property terms testing")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise TermsTestingError("Supabase client is not installed") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(TERMS_TEST_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    TERMS_TEST_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": TERMS_TEST_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise TermsTestingError("Could not create the private terms-testing bucket") from exc
        self._bucket_ready = True

    def load(self) -> TermsTestingLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(TERMS_TEST_BUCKET).download(TERMS_TEST_PATH)
        except Exception:
            return TermsTestingLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return TermsTestingLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise TermsTestingError("The saved terms-testing ledger could not be read") from exc

    def save(self, ledger: TermsTestingLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > TERMS_TEST_MAX_BYTES:
            raise TermsTestingError("The terms-testing ledger is too large to save")
        try:
            self._client.storage.from_(TERMS_TEST_BUCKET).upload(
                path=TERMS_TEST_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise TermsTestingError("Could not save the terms-testing ledger") from exc
