from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .dwelyx import build_dwelyx_url
from .facebook_group_variations import (
    build_facebook_group_variation,
    validate_facebook_group_variation,
)
from .facebook_groups import (
    FacebookGroupError,
    FacebookGroupLedger,
    business_now,
    facebook_group_post_status,
    record_facebook_group_post,
)
from .models import OwnerFinanceProperty
from .storage import SupabaseSettings

ASSIGNMENT_BUCKET = "cfh-facebook-assignment-dashboard"
ASSIGNMENT_LEDGER_PATH = "facebook/assignment-ledger.json"
ASSIGNMENT_MAX_BYTES = 2 * 1024 * 1024
MAX_DAILY_ASSIGNMENTS = 500


class FacebookAssignmentError(RuntimeError):
    """Raised when the Facebook assignment dashboard cannot complete an operation."""


class AssignmentStatus(StrEnum):
    QUEUED = "Queued"
    IN_PROGRESS = "In Progress"
    POSTED = "Posted"
    SKIPPED = "Skipped"
    NEEDS_REVIEW = "Needs Review"


class PostingOperator(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    operator_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=120)
    daily_goal: int = Field(default=20, ge=1, le=200)
    active: bool = True
    notes: str = Field(default="", max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FacebookPostingAssignment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    assignment_id: str = Field(default_factory=lambda: str(uuid4()))
    assignment_date: date
    property_id: str
    property_address: str
    group_id: str
    group_name: str
    group_url: str = ""
    assigned_to_id: str
    assigned_to_name: str
    campaign: str = "owner_finance_homes"
    tracked_link: str
    variation_label: str
    post_copy: str
    priority: int = Field(default=100, ge=1, le=999)
    status: AssignmentStatus = AssignmentStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by: str = ""
    notes: str = Field(default="", max_length=2000)


class FacebookAssignmentLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    operators: list[PostingOperator] = Field(default_factory=list)
    assignments: list[FacebookPostingAssignment] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AssignmentGenerationResult:
    ledger: FacebookAssignmentLedger
    created: int
    duplicate_skipped: int
    cooldown_skipped: int
    validation_skipped: int
    capacity_skipped: int


@dataclass(frozen=True, slots=True)
class DailyAssignmentSummary:
    total: int
    queued: int
    in_progress: int
    posted: int
    skipped: int
    needs_review: int
    remaining: int
    completion_percent: int


def active_operators(ledger: FacebookAssignmentLedger) -> list[PostingOperator]:
    return sorted(
        [operator for operator in ledger.operators if operator.active],
        key=lambda operator: operator.name.casefold(),
    )


def find_operator(
    ledger: FacebookAssignmentLedger,
    operator_id: str,
) -> PostingOperator | None:
    return next(
        (operator for operator in ledger.operators if operator.operator_id == operator_id),
        None,
    )


def upsert_operator(
    ledger: FacebookAssignmentLedger,
    *,
    name: str,
    daily_goal: int,
    notes: str = "",
    operator_id: str | None = None,
    now: datetime | None = None,
) -> FacebookAssignmentLedger:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    existing = find_operator(ledger, operator_id) if operator_id else None
    if not existing:
        existing = next(
            (
                operator
                for operator in ledger.operators
                if operator.name.strip().casefold() == name.strip().casefold()
            ),
            None,
        )

    if existing:
        replacement = existing.model_copy(
            update={
                "name": name,
                "daily_goal": daily_goal,
                "notes": notes,
                "active": True,
                "updated_at": timestamp,
            }
        )
        operators = [
            replacement if operator.operator_id == existing.operator_id else operator
            for operator in ledger.operators
        ]
    else:
        operators = [
            *ledger.operators,
            PostingOperator(
                name=name,
                daily_goal=daily_goal,
                notes=notes,
                created_at=timestamp,
                updated_at=timestamp,
            ),
        ]

    return ledger.model_copy(
        update={"operators": operators, "updated_at": timestamp}
    )


def deactivate_operator(
    ledger: FacebookAssignmentLedger,
    *,
    operator_id: str,
    now: datetime | None = None,
) -> FacebookAssignmentLedger:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    found = False
    operators: list[PostingOperator] = []
    for operator in ledger.operators:
        if operator.operator_id == operator_id:
            found = True
            operators.append(
                operator.model_copy(
                    update={"active": False, "updated_at": timestamp}
                )
            )
        else:
            operators.append(operator)
    if not found:
        raise FacebookAssignmentError("The selected team member could not be found.")
    return ledger.model_copy(
        update={"operators": operators, "updated_at": timestamp}
    )


def assignments_for_date(
    ledger: FacebookAssignmentLedger,
    assignment_date: date,
) -> list[FacebookPostingAssignment]:
    return sorted(
        [
            assignment
            for assignment in ledger.assignments
            if assignment.assignment_date == assignment_date
        ],
        key=lambda assignment: (
            assignment.assigned_to_name.casefold(),
            assignment.priority,
            assignment.group_name.casefold(),
        ),
    )


def _operator_loads(
    ledger: FacebookAssignmentLedger,
    assignment_date: date,
) -> dict[str, int]:
    loads: dict[str, int] = {}
    for assignment in assignments_for_date(ledger, assignment_date):
        if assignment.status == AssignmentStatus.SKIPPED:
            continue
        loads[assignment.assigned_to_id] = loads.get(assignment.assigned_to_id, 0) + 1
    return loads


def _prior_group_post_count(
    group_ledger: FacebookGroupLedger,
    *,
    property_id: UUID | str,
    group_id: str,
) -> int:
    wanted_property = str(property_id)
    return sum(
        1
        for post in group_ledger.posts
        if post.property_id == wanted_property and post.group_id == group_id
    )


def generate_daily_assignments(
    ledger: FacebookAssignmentLedger,
    group_ledger: FacebookGroupLedger,
    properties: Sequence[OwnerFinanceProperty],
    *,
    operator_ids: Sequence[str],
    assignment_date: date,
    dwelyx_url: str,
    campaign: str = "owner_finance_homes",
    now: datetime | None = None,
) -> AssignmentGenerationResult:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    selected_operators = [
        operator
        for operator_id in operator_ids
        if (operator := find_operator(ledger, operator_id)) and operator.active
    ]
    if not selected_operators:
        raise FacebookAssignmentError("Select at least one active team member.")
    selected_properties = sorted(
        properties,
        key=lambda property_record: property_record.display_address.casefold(),
    )
    if not selected_properties:
        raise FacebookAssignmentError("Select at least one property.")

    loads = _operator_loads(ledger, assignment_date)
    remaining_capacity = {
        operator.operator_id: max(operator.daily_goal - loads.get(operator.operator_id, 0), 0)
        for operator in selected_operators
    }
    total_capacity = min(sum(remaining_capacity.values()), MAX_DAILY_ASSIGNMENTS)
    if total_capacity <= 0:
        return AssignmentGenerationResult(
            ledger=ledger,
            created=0,
            duplicate_skipped=0,
            cooldown_skipped=0,
            validation_skipped=0,
            capacity_skipped=0,
        )

    existing_for_date = assignments_for_date(ledger, assignment_date)
    existing_pairs = {
        (assignment.property_id, assignment.group_id)
        for assignment in existing_for_date
        if assignment.status != AssignmentStatus.SKIPPED
    }
    groups_used_today = {
        assignment.group_id
        for assignment in existing_for_date
        if assignment.status != AssignmentStatus.SKIPPED
    }

    active_groups = sorted(
        [group for group in group_ledger.groups if group.active],
        key=lambda group: group.name.casefold(),
    )
    new_assignments: list[FacebookPostingAssignment] = []
    duplicate_skipped = 0
    cooldown_skipped = 0
    validation_skipped = 0
    capacity_skipped = 0
    operator_cursor = 0

    for group_index, group in enumerate(active_groups):
        if len(new_assignments) >= total_capacity:
            capacity_skipped += len(active_groups) - group_index
            break
        if group.group_id in groups_used_today:
            duplicate_skipped += 1
            continue

        selected_property: OwnerFinanceProperty | None = None
        for property_offset in range(len(selected_properties)):
            candidate = selected_properties[
                (group_index + property_offset) % len(selected_properties)
            ]
            pair = (str(candidate.property_id), group.group_id)
            if pair in existing_pairs:
                duplicate_skipped += 1
                continue
            status = facebook_group_post_status(
                group_ledger,
                property_id=candidate.property_id,
                group_id=group.group_id,
                now=timestamp,
            )
            if not status.eligible:
                cooldown_skipped += 1
                continue
            selected_property = candidate
            break

        if selected_property is None:
            continue

        eligible_operators = [
            operator
            for operator in selected_operators
            if remaining_capacity.get(operator.operator_id, 0) > 0
        ]
        if not eligible_operators:
            capacity_skipped += 1
            break
        operator = eligible_operators[operator_cursor % len(eligible_operators)]
        operator_cursor += 1

        tracked_link = build_dwelyx_url(
            dwelyx_url,
            source="credit_friendly_homes",
            medium="facebook_groups",
            campaign=f"{campaign}_{assignment_date.isoformat()}_{group.group_id[:8]}",
            property_id=selected_property.property_id,
        )
        variation = build_facebook_group_variation(
            selected_property,
            tracked_link,
            group_id=group.group_id,
            prior_post_count=_prior_group_post_count(
                group_ledger,
                property_id=selected_property.property_id,
                group_id=group.group_id,
            ),
        )
        validation_errors = validate_facebook_group_variation(
            variation,
            selected_property,
            tracked_link,
        )
        if validation_errors:
            validation_skipped += 1
            continue

        priority = 100 + len(new_assignments)
        new_assignments.append(
            FacebookPostingAssignment(
                assignment_date=assignment_date,
                property_id=str(selected_property.property_id),
                property_address=selected_property.display_address,
                group_id=group.group_id,
                group_name=group.name,
                group_url=group.group_url,
                assigned_to_id=operator.operator_id,
                assigned_to_name=operator.name,
                campaign=campaign,
                tracked_link=tracked_link,
                variation_label=variation.label,
                post_copy=variation.copy,
                priority=priority,
                created_at=timestamp,
            )
        )
        remaining_capacity[operator.operator_id] -= 1
        existing_pairs.add((str(selected_property.property_id), group.group_id))
        groups_used_today.add(group.group_id)

    updated = ledger.model_copy(
        update={
            "assignments": [*ledger.assignments, *new_assignments],
            "updated_at": timestamp,
        }
    )
    return AssignmentGenerationResult(
        ledger=updated,
        created=len(new_assignments),
        duplicate_skipped=duplicate_skipped,
        cooldown_skipped=cooldown_skipped,
        validation_skipped=validation_skipped,
        capacity_skipped=capacity_skipped,
    )


def find_assignment(
    ledger: FacebookAssignmentLedger,
    assignment_id: str,
) -> FacebookPostingAssignment | None:
    return next(
        (
            assignment
            for assignment in ledger.assignments
            if assignment.assignment_id == assignment_id
        ),
        None,
    )


def update_assignment_status(
    ledger: FacebookAssignmentLedger,
    *,
    assignment_id: str,
    status: AssignmentStatus,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> FacebookAssignmentLedger:
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    found = False
    assignments: list[FacebookPostingAssignment] = []
    for assignment in ledger.assignments:
        if assignment.assignment_id != assignment_id:
            assignments.append(assignment)
            continue
        found = True
        started_at = assignment.started_at
        completed_at = assignment.completed_at
        completed_by = assignment.completed_by
        if status == AssignmentStatus.IN_PROGRESS and not started_at:
            started_at = timestamp
        if status in {
            AssignmentStatus.POSTED,
            AssignmentStatus.SKIPPED,
            AssignmentStatus.NEEDS_REVIEW,
        }:
            completed_at = timestamp
            completed_by = actor
        elif status == AssignmentStatus.QUEUED:
            started_at = None
            completed_at = None
            completed_by = ""
        assignments.append(
            assignment.model_copy(
                update={
                    "status": status,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "completed_by": completed_by,
                    "notes": notes or assignment.notes,
                }
            )
        )
    if not found:
        raise FacebookAssignmentError("The selected assignment could not be found.")
    return ledger.model_copy(
        update={"assignments": assignments, "updated_at": timestamp}
    )


def complete_assignment_and_record_group_post(
    assignment_ledger: FacebookAssignmentLedger,
    group_ledger: FacebookGroupLedger,
    *,
    assignment_id: str,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> tuple[FacebookAssignmentLedger, FacebookGroupLedger]:
    assignment = find_assignment(assignment_ledger, assignment_id)
    if not assignment:
        raise FacebookAssignmentError("The selected assignment could not be found.")
    if assignment.status == AssignmentStatus.POSTED:
        raise FacebookAssignmentError("This assignment is already marked posted.")
    timestamp = business_now(now)
    try:
        updated_group_ledger = record_facebook_group_post(
            group_ledger,
            property_id=assignment.property_id,
            property_address=assignment.property_address,
            group_id=assignment.group_id,
            posted_by=actor,
            campaign=assignment.campaign,
            tracked_link=assignment.tracked_link,
            notes=notes,
            now=timestamp,
        )
    except FacebookGroupError as exc:
        raise FacebookAssignmentError(str(exc)) from exc
    updated_assignment_ledger = update_assignment_status(
        assignment_ledger,
        assignment_id=assignment_id,
        status=AssignmentStatus.POSTED,
        actor=actor,
        notes=notes,
        now=timestamp,
    )
    return updated_assignment_ledger, updated_group_ledger


def daily_assignment_summary(
    ledger: FacebookAssignmentLedger,
    assignment_date: date,
) -> DailyAssignmentSummary:
    assignments = assignments_for_date(ledger, assignment_date)
    counts = {status: 0 for status in AssignmentStatus}
    for assignment in assignments:
        counts[assignment.status] += 1
    total = len(assignments)
    remaining = (
        counts[AssignmentStatus.QUEUED]
        + counts[AssignmentStatus.IN_PROGRESS]
        + counts[AssignmentStatus.NEEDS_REVIEW]
    )
    eligible_total = max(total - counts[AssignmentStatus.SKIPPED], 0)
    completion_percent = (
        round((counts[AssignmentStatus.POSTED] / eligible_total) * 100)
        if eligible_total
        else 0
    )
    return DailyAssignmentSummary(
        total=total,
        queued=counts[AssignmentStatus.QUEUED],
        in_progress=counts[AssignmentStatus.IN_PROGRESS],
        posted=counts[AssignmentStatus.POSTED],
        skipped=counts[AssignmentStatus.SKIPPED],
        needs_review=counts[AssignmentStatus.NEEDS_REVIEW],
        remaining=remaining,
        completion_percent=completion_percent,
    )


def assignment_rows(
    ledger: FacebookAssignmentLedger,
    assignment_date: date,
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for assignment in assignments_for_date(ledger, assignment_date):
        rows.append(
            {
                "Priority": assignment.priority,
                "Team Member": assignment.assigned_to_name,
                "Status": assignment.status.value,
                "Property": assignment.property_address,
                "Facebook Group": assignment.group_name,
                "Variation": assignment.variation_label,
                "Completed By": assignment.completed_by or "—",
                "Notes": assignment.notes or "—",
            }
        )
    return rows


class FacebookAssignmentStore:
    """Private Supabase-backed assignment ledger."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise FacebookAssignmentError(
                "Supabase is not configured for the Facebook assignment dashboard."
            )
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise FacebookAssignmentError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(ASSIGNMENT_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    ASSIGNMENT_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": ASSIGNMENT_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise FacebookAssignmentError(
                    "Could not create the private Facebook assignment bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> FacebookAssignmentLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(ASSIGNMENT_BUCKET).download(
                ASSIGNMENT_LEDGER_PATH
            )
        except Exception:
            return FacebookAssignmentLedger()
        try:
            payload = json.loads(
                raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            )
            return FacebookAssignmentLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FacebookAssignmentError(
                "The saved Facebook assignment dashboard could not be read."
            ) from exc

    def save(self, ledger: FacebookAssignmentLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > ASSIGNMENT_MAX_BYTES:
            raise FacebookAssignmentError(
                "The Facebook assignment ledger is too large to save."
            )
        try:
            self._client.storage.from_(ASSIGNMENT_BUCKET).upload(
                path=ASSIGNMENT_LEDGER_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise FacebookAssignmentError(
                "Could not save the Facebook assignment dashboard."
            ) from exc
