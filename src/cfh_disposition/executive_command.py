from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .buyer_conversion import (
    BuyerConversionLedger,
    ConversionPriority,
    ConversionQueueItem,
    ConversionStage,
)
from .inventory_velocity import (
    EscalationLevel,
    EscalationTaskStatus,
    InventoryVelocityLedger,
    PropertyVelocityAssessment,
)
from .models import OwnerFinanceProperty, PropertyStatus
from .property_shutdown import (
    ControlTaskStatus,
    MarketingControlAction,
    PropertyControlLedger,
)
from .showing_conversion import (
    ShowingConversionLedger,
    ShowingPriority,
    ShowingQueueItem,
    ShowingStatus,
)
from .terms_testing import (
    RelaunchTaskStatus,
    TermsExperimentStatus,
    TermsRecommendation,
    TermsRecommendationResult,
    TermsTestingLedger,
)


class ExecutivePriority(StrEnum):
    BLOCKED = "Blocked"
    CRITICAL = "Critical"
    URGENT = "Urgent"
    HIGH = "High"
    NORMAL = "Normal"
    WATCH = "Watch"


class ExecutiveLane(StrEnum):
    COMPLIANCE = "Compliance Hold"
    MANAGEMENT = "Management Decision"
    TEAM = "Team Execution"
    SYSTEM = "System / Connection"


PRIORITY_SORT = {
    ExecutivePriority.BLOCKED: 0,
    ExecutivePriority.CRITICAL: 1,
    ExecutivePriority.URGENT: 2,
    ExecutivePriority.HIGH: 3,
    ExecutivePriority.NORMAL: 4,
    ExecutivePriority.WATCH: 5,
}

PAGE_PATHS = {
    "Vacant Home Disposition Escalation Center": "pages/20_Vacant_Home_Disposition_Escalation.py",
    "AI Buyer Conversion & Follow-Up Command Center": "pages/16_AI_Buyer_Conversion_Follow_Up.py",
    "Showing-to-Contract Conversion Center": "pages/22_Showing_to_Contract_Conversion.py",
    "Property Terms Test & Relaunch Center": "pages/21_Property_Terms_Test_Relaunch.py",
    "Property Shutdown & Buyer Reroute Center": "pages/18_Property_Shutdown_Buyer_Reroute.py",
    "Dwelyx Results Tracking & Attribution Center": "pages/19_Dwelyx_Results_Attribution.py",
}


@dataclass(frozen=True, slots=True)
class ExecutiveActionItem:
    action_id: str
    priority: ExecutivePriority
    lane: ExecutiveLane
    source: str
    title: str
    action: str
    reason: str
    owner: str = "Unassigned"
    due_at: datetime | None = None
    property_id: str = ""
    property_address: str = ""
    buyer_name: str = ""
    manager_only: bool = False
    page_name: str = ""
    entity_id: str = ""


@dataclass(frozen=True, slots=True)
class ExecutiveSnapshot:
    total_actions: int
    urgent_or_blocked_actions: int
    management_decisions: int
    team_actions: int
    compliance_holds: int
    active_vacant_properties: int
    critical_properties: int
    estimated_holding_exposure: Decimal
    contract_pending_records: int
    showing_contract_handoffs: int


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def _vacant(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(word in normalized for word in ("vacant", "empty", "unoccupied"))


def _priority_for_escalation(level: EscalationLevel, manager_required: bool) -> ExecutivePriority:
    if level == EscalationLevel.CRITICAL:
        return ExecutivePriority.CRITICAL
    if level == EscalationLevel.HIGH or manager_required:
        return ExecutivePriority.HIGH
    if level == EscalationLevel.WATCH:
        return ExecutivePriority.WATCH
    return ExecutivePriority.NORMAL


def _priority_for_conversion(priority: ConversionPriority) -> ExecutivePriority:
    mapping = {
        ConversionPriority.COMPLIANCE_HOLD: ExecutivePriority.BLOCKED,
        ConversionPriority.URGENT: ExecutivePriority.URGENT,
        ConversionPriority.HIGH: ExecutivePriority.HIGH,
        ConversionPriority.NORMAL: ExecutivePriority.NORMAL,
        ConversionPriority.NURTURE: ExecutivePriority.WATCH,
        ConversionPriority.CLOSED: ExecutivePriority.WATCH,
    }
    return mapping[priority]


def _priority_for_showing(priority: ShowingPriority) -> ExecutivePriority:
    mapping = {
        ShowingPriority.COMPLIANCE_HOLD: ExecutivePriority.BLOCKED,
        ShowingPriority.URGENT: ExecutivePriority.URGENT,
        ShowingPriority.HIGH: ExecutivePriority.HIGH,
        ShowingPriority.NORMAL: ExecutivePriority.NORMAL,
        ShowingPriority.NURTURE: ExecutivePriority.WATCH,
        ShowingPriority.CLOSED: ExecutivePriority.WATCH,
    }
    return mapping[priority]


def _lane_for_contact_hold(blocked: bool) -> ExecutiveLane:
    return ExecutiveLane.COMPLIANCE if blocked else ExecutiveLane.TEAM


def inventory_action_items(
    assessments: Sequence[PropertyVelocityAssessment],
    ledger: InventoryVelocityLedger,
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    open_statuses = {EscalationTaskStatus.OPEN, EscalationTaskStatus.IN_PROGRESS}
    open_tasks = {
        (task.property_id, task.intervention_type): task
        for task in ledger.tasks
        if task.status in open_statuses
    }
    represented: set[tuple[str, object]] = set()
    items: list[ExecutiveActionItem] = []

    for assessment in assessments:
        if assessment.level in {EscalationLevel.CLOSED, EscalationLevel.NORMAL} and not assessment.manager_approval_required:
            continue
        key = (assessment.signals.property_id, assessment.primary_intervention)
        task = open_tasks.get(key)
        represented.add(key)
        manager_only = assessment.manager_approval_required or bool(task and task.manager_approval_required)
        lane = ExecutiveLane.MANAGEMENT if manager_only else ExecutiveLane.TEAM
        priority = _priority_for_escalation(assessment.level, manager_only)
        items.append(
            ExecutiveActionItem(
                action_id=f"inventory:{assessment.signals.property_id}:{assessment.primary_intervention.value}",
                priority=priority,
                lane=lane,
                source="Vacant Home Escalation",
                title=(task.title if task else f"{assessment.bottleneck.value} — {assessment.signals.address}"),
                action=(task.reason if task else assessment.primary_action),
                reason=assessment.diagnosis,
                owner=(task.owner if task else "Sabrina"),
                due_at=(task.due_at if task else current + timedelta(hours=assessment.due_hours)),
                property_id=assessment.signals.property_id,
                property_address=assessment.signals.address,
                manager_only=manager_only,
                page_name="Vacant Home Disposition Escalation Center",
                entity_id=(task.task_id if task else assessment.signals.property_id),
            )
        )

    for key, task in open_tasks.items():
        if key in represented:
            continue
        manager_only = task.manager_approval_required
        items.append(
            ExecutiveActionItem(
                action_id=f"inventory-task:{task.task_id}",
                priority=(ExecutivePriority.CRITICAL if task.due_at < current else ExecutivePriority.HIGH),
                lane=(ExecutiveLane.MANAGEMENT if manager_only else ExecutiveLane.TEAM),
                source="Vacant Home Escalation",
                title=task.title,
                action=task.reason,
                reason=task.notes or "An assigned escalation task remains open.",
                owner=task.owner,
                due_at=task.due_at,
                property_id=task.property_id,
                manager_only=manager_only,
                page_name="Vacant Home Disposition Escalation Center",
                entity_id=task.task_id,
            )
        )
    return items


def conversion_action_items(
    queue: Sequence[ConversionQueueItem],
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    included = {
        ConversionPriority.COMPLIANCE_HOLD,
        ConversionPriority.URGENT,
        ConversionPriority.HIGH,
    }
    items: list[ExecutiveActionItem] = []
    for row in queue:
        contract_priority = row.stage == ConversionStage.CONTRACT_PENDING
        if row.priority not in included and not contract_priority:
            continue
        blocked = row.priority == ConversionPriority.COMPLIANCE_HOLD
        priority = ExecutivePriority.URGENT if contract_priority and not blocked else _priority_for_conversion(row.priority)
        items.append(
            ExecutiveActionItem(
                action_id=f"conversion:{row.record_id}",
                priority=priority,
                lane=_lane_for_contact_hold(blocked),
                source="Buyer Follow-Up",
                title=f"{row.stage.value} — {row.buyer_name}",
                action=row.recommended_action or row.next_action,
                reason=row.reason,
                owner=row.owner,
                due_at=row.next_action_at or current,
                property_address=row.property_address,
                buyer_name=row.buyer_name,
                page_name="AI Buyer Conversion & Follow-Up Command Center",
                entity_id=row.record_id,
            )
        )
    return items


def showing_action_items(
    queue: Sequence[ShowingQueueItem],
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    included = {
        ShowingPriority.COMPLIANCE_HOLD,
        ShowingPriority.URGENT,
        ShowingPriority.HIGH,
    }
    items: list[ExecutiveActionItem] = []
    for row in queue:
        contract_handoff = row.status == ShowingStatus.CONTRACT_HANDOFF
        if row.priority not in included and not contract_handoff:
            continue
        blocked = row.priority == ShowingPriority.COMPLIANCE_HOLD
        priority = ExecutivePriority.URGENT if contract_handoff and not blocked else _priority_for_showing(row.priority)
        items.append(
            ExecutiveActionItem(
                action_id=f"showing:{row.appointment_id}",
                priority=priority,
                lane=_lane_for_contact_hold(blocked),
                source="Showing Conversion",
                title=f"{row.status.value} — {row.buyer_name}",
                action=row.recommended_action or row.next_action,
                reason=row.reason,
                owner=row.owner,
                due_at=row.next_action_at or row.scheduled_at or current,
                property_address=row.property_address,
                buyer_name=row.buyer_name,
                page_name="Showing-to-Contract Conversion Center",
                entity_id=row.appointment_id,
            )
        )
    return items


def terms_action_items(
    ledger: TermsTestingLedger,
    recommendations: Mapping[str, TermsRecommendationResult] | None = None,
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    results = recommendations or {}
    items: list[ExecutiveActionItem] = []
    closed = {TermsExperimentStatus.COMPLETED, TermsExperimentStatus.CANCELLED}

    for experiment in ledger.experiments:
        if experiment.status in closed:
            continue
        priority = ExecutivePriority.WATCH
        manager_only = False
        lane = ExecutiveLane.TEAM
        action = "Review the active terms test."
        reason = experiment.objective
        due = experiment.updated_at + timedelta(days=1)

        if experiment.status == TermsExperimentStatus.DRAFT:
            priority = ExecutivePriority.HIGH
            manager_only = True
            lane = ExecutiveLane.MANAGEMENT
            action = "Approve or cancel the draft challenger."
            reason = "A proposed property-term change is waiting for a management decision."
            due = experiment.created_at + timedelta(days=1)
        elif experiment.status == TermsExperimentStatus.APPROVED:
            priority = ExecutivePriority.URGENT
            manager_only = True
            lane = ExecutiveLane.MANAGEMENT
            action = "Explicitly apply the approved challenger or cancel the test."
            reason = "Management approved the challenger, but the saved property terms have not been changed."
            due = (experiment.approved_at or experiment.updated_at) + timedelta(hours=4)
        elif experiment.status in {TermsExperimentStatus.ACTIVE, TermsExperimentStatus.REVIEW_READY}:
            result = results.get(experiment.experiment_id)
            if result and result.recommendation == TermsRecommendation.PROTECT_CONTRACT:
                priority = ExecutivePriority.CRITICAL
                action = "Stop further terms changes and protect the signed buyer contract."
                reason = result.reason
                due = current
            elif result and result.sample_ready and result.recommendation in {TermsRecommendation.KEEP, TermsRecommendation.REVERT}:
                priority = ExecutivePriority.HIGH
                manager_only = True
                lane = ExecutiveLane.MANAGEMENT
                action = "Approve the measured Keep or Revert decision."
                reason = result.reason
                due = current + timedelta(hours=12)
            elif experiment.status == TermsExperimentStatus.REVIEW_READY:
                priority = ExecutivePriority.HIGH
                manager_only = True
                lane = ExecutiveLane.MANAGEMENT
                action = "Review the experiment results and approve Keep, Revert, or Extend."
                reason = result.reason if result else "The test is marked ready for management review."
                due = current + timedelta(hours=12)
            elif result and result.recommendation == TermsRecommendation.EXTEND:
                priority = ExecutivePriority.WATCH
                action = "Continue the test until the minimum sample is reached."
                reason = result.reason
        elif experiment.status == TermsExperimentStatus.REVERT_APPROVED:
            priority = ExecutivePriority.URGENT
            action = "Restore the original saved property terms using the required confirmation."
            reason = experiment.decision_reason or "Management approved a rollback, but the original terms have not been restored."
            due = (experiment.decided_at or experiment.updated_at) + timedelta(hours=4)
        elif experiment.status == TermsExperimentStatus.KEEP_APPROVED:
            priority = ExecutivePriority.HIGH
            action = "Finish the 15-channel relaunch confirmations using the approved challenger."
            reason = experiment.decision_reason or "The challenger was approved to remain active."
            due = (experiment.decided_at or experiment.updated_at) + timedelta(days=1)

        items.append(
            ExecutiveActionItem(
                action_id=f"terms-decision:{experiment.experiment_id}",
                priority=priority,
                lane=lane,
                source="Property Terms Testing",
                title=f"{experiment.status.value} — {experiment.tested_field.value} — {experiment.property_address}",
                action=action,
                reason=reason,
                owner=(experiment.approved_by or experiment.applied_by or "Sabrina"),
                due_at=due,
                property_id=experiment.property_id,
                property_address=experiment.property_address,
                manager_only=manager_only,
                page_name="Property Terms Test & Relaunch Center",
                entity_id=experiment.experiment_id,
            )
        )

        open_relaunch = [
            task
            for task in experiment.relaunch_tasks
            if task.status in {RelaunchTaskStatus.READY, RelaunchTaskStatus.IN_PROGRESS, RelaunchTaskStatus.FAILED}
        ]
        if open_relaunch:
            failed = sum(task.status == RelaunchTaskStatus.FAILED for task in open_relaunch)
            items.append(
                ExecutiveActionItem(
                    action_id=f"terms-relaunch:{experiment.experiment_id}",
                    priority=(ExecutivePriority.URGENT if failed else ExecutivePriority.HIGH),
                    lane=ExecutiveLane.TEAM,
                    source="Terms Relaunch",
                    title=f"{len(open_relaunch)} open channel updates — {experiment.property_address}",
                    action="Update every remaining channel so buyers see the currently approved terms.",
                    reason=(f"{failed} relaunch tasks are marked Failed." if failed else "Old terms may still be visible on unfinished channels."),
                    owner=experiment.applied_by or "Sabrina",
                    due_at=(experiment.applied_at or experiment.updated_at) + timedelta(days=1),
                    property_id=experiment.property_id,
                    property_address=experiment.property_address,
                    page_name="Property Terms Test & Relaunch Center",
                    entity_id=experiment.experiment_id,
                )
            )
    return items


def property_control_action_items(
    ledger: PropertyControlLedger,
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    latest_by_property = {}
    for event in sorted(ledger.events, key=lambda item: item.requested_at):
        latest_by_property[event.property_id] = event

    items: list[ExecutiveActionItem] = []
    for event in latest_by_property.values():
        open_channel = [
            task
            for task in event.channel_tasks
            if task.status in {ControlTaskStatus.READY, ControlTaskStatus.FAILED}
        ]
        open_buyer = [
            task
            for task in event.buyer_tasks
            if task.status in {ControlTaskStatus.READY, ControlTaskStatus.FAILED}
        ]
        if not open_channel and not open_buyer:
            continue
        failed = sum(task.status == ControlTaskStatus.FAILED for task in [*open_channel, *open_buyer])
        unavailable = event.action in {
            MarketingControlAction.PENDING,
            MarketingControlAction.FILLED,
            MarketingControlAction.SOLD,
        }
        priority = ExecutivePriority.URGENT if failed or unavailable else ExecutivePriority.HIGH
        items.append(
            ExecutiveActionItem(
                action_id=f"property-control:{event.event_id}",
                priority=priority,
                lane=ExecutiveLane.TEAM,
                source="Property Shutdown",
                title=f"{event.action.value} cleanup — {event.property_address}",
                action=(
                    f"Complete {len(open_channel)} channel tasks and {len(open_buyer)} buyer reroute tasks."
                ),
                reason=(f"{failed} tasks are marked Failed." if failed else "The latest authorized property-control event still has unfinished work."),
                owner=event.requested_by,
                due_at=event.requested_at + timedelta(days=1),
                property_id=event.property_id,
                property_address=event.property_address,
                page_name="Property Shutdown & Buyer Reroute Center",
                entity_id=event.event_id,
            )
        )
    return items


def system_action_items(
    errors: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    return [
        ExecutiveActionItem(
            action_id=f"system:{source.casefold().replace(' ', '_')}",
            priority=ExecutivePriority.BLOCKED,
            lane=ExecutiveLane.SYSTEM,
            source=source,
            title=f"{source} is unavailable",
            action="Open the connected operating page or System Setup and repair the connection before relying on its metrics.",
            reason=detail,
            owner="Management",
            due_at=current,
            manager_only=True,
            page_name=("Dwelyx Results Tracking & Attribution Center" if "Dwelyx" in source else ""),
            entity_id=source,
        )
        for source, detail in sorted(errors.items())
        if detail.strip()
    ]


def deduplicate_and_sort(items: Sequence[ExecutiveActionItem]) -> list[ExecutiveActionItem]:
    unique: dict[str, ExecutiveActionItem] = {}
    for item in items:
        existing = unique.get(item.action_id)
        if existing is None or PRIORITY_SORT[item.priority] < PRIORITY_SORT[existing.priority]:
            unique[item.action_id] = item
    ceiling = datetime.max.replace(tzinfo=UTC)
    return sorted(
        unique.values(),
        key=lambda item: (
            PRIORITY_SORT[item.priority],
            0 if item.manager_only else 1,
            _current(item.due_at) if item.due_at else ceiling,
            item.title.casefold(),
        ),
    )


def build_executive_snapshot(
    items: Sequence[ExecutiveActionItem],
    properties: Sequence[OwnerFinanceProperty],
    assessments: Sequence[PropertyVelocityAssessment],
    conversion_ledger: BuyerConversionLedger,
    showing_ledger: ShowingConversionLedger,
) -> ExecutiveSnapshot:
    active_vacant = sum(
        item.status in {PropertyStatus.READY, PropertyStatus.LIVE} and _vacant(item.occupancy)
        for item in properties
    )
    urgent_priorities = {
        ExecutivePriority.BLOCKED,
        ExecutivePriority.CRITICAL,
        ExecutivePriority.URGENT,
    }
    holding = sum(
        (item.signals.estimated_holding_cost for item in assessments if item.level != EscalationLevel.CLOSED),
        Decimal("0"),
    )
    return ExecutiveSnapshot(
        total_actions=len(items),
        urgent_or_blocked_actions=sum(item.priority in urgent_priorities for item in items),
        management_decisions=sum(item.manager_only for item in items),
        team_actions=sum(item.lane == ExecutiveLane.TEAM for item in items),
        compliance_holds=sum(item.lane == ExecutiveLane.COMPLIANCE for item in items),
        active_vacant_properties=active_vacant,
        critical_properties=sum(item.level == EscalationLevel.CRITICAL for item in assessments),
        estimated_holding_exposure=holding,
        contract_pending_records=sum(record.stage == ConversionStage.CONTRACT_PENDING for record in conversion_ledger.records),
        showing_contract_handoffs=sum(item.status == ShowingStatus.CONTRACT_HANDOFF for item in showing_ledger.appointments),
    )


def action_rows(items: Sequence[ExecutiveActionItem]) -> list[dict[str, str]]:
    return [
        {
            "Priority": item.priority.value,
            "Lane": item.lane.value,
            "Source": item.source,
            "Property": item.property_address or "—",
            "Buyer": item.buyer_name or "—",
            "Owner": item.owner,
            "Due": item.due_at.astimezone().strftime("%Y-%m-%d %I:%M %p") if item.due_at else "—",
            "Action": item.action,
            "Why": item.reason,
            "Open In": item.page_name or "System Setup",
        }
        for item in items
    ]


def portfolio_rows(
    properties: Sequence[OwnerFinanceProperty],
    assessments: Sequence[PropertyVelocityAssessment],
    items: Sequence[ExecutiveActionItem],
) -> list[dict[str, str | int]]:
    assessments_by_id = {item.signals.property_id: item for item in assessments}
    actions_by_property: dict[str, list[ExecutiveActionItem]] = {}
    for item in items:
        if item.property_id:
            actions_by_property.setdefault(item.property_id, []).append(item)
    rows: list[dict[str, str | int]] = []
    for property_record in properties:
        property_id = str(property_record.property_id)
        assessment = assessments_by_id.get(property_id)
        property_actions = actions_by_property.get(property_id, [])
        rows.append(
            {
                "Property": property_record.display_address,
                "Status": property_record.status.value,
                "Risk": assessment.level.value if assessment else "Not scored",
                "Days Marketed": assessment.signals.days_marketed if assessment else 0,
                "Bottleneck": assessment.bottleneck.value if assessment else "—",
                "Open Actions": len(property_actions),
                "Management Decisions": sum(item.manager_only for item in property_actions),
                "Holding Exposure": (
                    f"${assessment.signals.estimated_holding_cost:,.0f}"
                    if assessment and assessment.signals.daily_holding_cost > 0
                    else "Not entered"
                ),
                "Next Action": property_actions[0].action if property_actions else "No urgent action",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["Risk"] not in {"Critical", "High"},
            -int(row["Open Actions"]),
            str(row["Property"]).casefold(),
        ),
    )


def daily_brief_text(
    snapshot: ExecutiveSnapshot,
    items: Sequence[ExecutiveActionItem],
    *,
    generated_at: datetime | None = None,
    maximum_items: int = 10,
) -> str:
    current = _current(generated_at)
    lines = [
        f"Daily Executive Disposition Brief — {current.astimezone().strftime('%Y-%m-%d %I:%M %p')}",
        "",
        f"Active vacant properties: {snapshot.active_vacant_properties}",
        f"Critical properties: {snapshot.critical_properties}",
        f"Urgent or blocked actions: {snapshot.urgent_or_blocked_actions}",
        f"Management decisions: {snapshot.management_decisions}",
        f"Team execution actions: {snapshot.team_actions}",
        f"Estimated holding exposure: ${snapshot.estimated_holding_exposure:,.0f}",
        "",
        "Top priorities:",
    ]
    for index, item in enumerate(items[: max(1, maximum_items)], start=1):
        context = " — ".join(value for value in (item.property_address, item.buyer_name) if value)
        lines.append(
            f"{index}. [{item.priority.value}] {item.title}"
            + (f" ({context})" if context else "")
            + f" — {item.action}"
        )
    if not items:
        lines.append("No urgent, high, blocked, or management actions are currently open.")
    return "\n".join(lines)
