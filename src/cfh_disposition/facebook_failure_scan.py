from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .facebook_assignments import (
    AssignmentStatus,
    FacebookAssignmentError,
    FacebookAssignmentStore,
)
from .facebook_groups import FacebookGroupError, FacebookGroupStore, active_groups
from .models import OwnerFinanceProperty
from .operational_failures import CriticalFailureType, record_operational_failure


def scan_facebook_operational_failures(
    values: Mapping[str, Any],
    properties: Sequence[OwnerFinanceProperty],
) -> int:
    """Promote actionable Facebook work failures into the critical failure ledger.

    This is intentionally best-effort: a broken failure scanner must never make the VA board
    unusable. The main critical banner will display whatever this scanner successfully records.
    """
    recorded = 0
    properties_by_id = {str(item.property_id): item for item in properties}

    try:
        assignment_ledger = FacebookAssignmentStore(values).load()
    except FacebookAssignmentError as exc:
        if record_operational_failure(
            values,
            CriticalFailureType.FACEBOOK_TASK,
            summary="Facebook assignment ledger could not be loaded.",
            technical_detail=str(exc),
            channel="facebook_groups",
            source="facebook_assignment_dashboard",
        ):
            recorded += 1
        assignment_ledger = None

    try:
        group_ledger = FacebookGroupStore(values).load()
    except FacebookGroupError as exc:
        if record_operational_failure(
            values,
            CriticalFailureType.FACEBOOK_TASK,
            summary="Facebook Group directory/posting ledger could not be loaded.",
            technical_detail=str(exc),
            channel="facebook_groups",
            source="facebook_group_posting_center",
        ):
            recorded += 1
        group_ledger = None

    if group_ledger is not None:
        for group in active_groups(group_ledger):
            if group.group_url:
                continue
            if record_operational_failure(
                values,
                CriticalFailureType.FACEBOOK_TASK,
                summary=f"Active Facebook Group is missing its saved URL: {group.name}.",
                technical_detail=(
                    "The VA cannot open the exact destination from the Daily Board until the "
                    "group URL is added in the Facebook Group Directory."
                ),
                channel="facebook_groups",
                source=f"group:{group.group_id}",
            ):
                recorded += 1

    if assignment_ledger is not None:
        for assignment in assignment_ledger.assignments:
            if assignment.status in {AssignmentStatus.POSTED, AssignmentStatus.SKIPPED}:
                continue
            property_record = properties_by_id.get(assignment.property_id)
            if assignment.status == AssignmentStatus.NEEDS_REVIEW:
                if record_operational_failure(
                    values,
                    CriticalFailureType.FACEBOOK_TASK,
                    summary=(
                        f"Facebook assignment needs manager review: {assignment.property_address} "
                        f"→ {assignment.group_name}."
                    ),
                    technical_detail=assignment.notes or "Assignment was moved to Needs Review.",
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    channel="facebook_groups",
                    campaign=assignment.campaign,
                    source=f"assignment:{assignment.assignment_id}",
                ):
                    recorded += 1
            if not assignment.group_url:
                if record_operational_failure(
                    values,
                    CriticalFailureType.FACEBOOK_TASK,
                    summary=(
                        f"Facebook assignment has no group URL: {assignment.property_address} "
                        f"→ {assignment.group_name}."
                    ),
                    technical_detail="The assignment cannot be completed from the VA board until the group URL is saved.",
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    channel="facebook_groups",
                    campaign=assignment.campaign,
                    source=f"assignment:{assignment.assignment_id}",
                ):
                    recorded += 1
            if property_record is not None and property_record.updated_at > assignment.created_at:
                if record_operational_failure(
                    values,
                    CriticalFailureType.FACEBOOK_TASK,
                    summary=(
                        f"Facebook assignment is stale after a property fact change: "
                        f"{assignment.property_address} → {assignment.group_name}."
                    ),
                    technical_detail=(
                        "The central property record changed after this assignment was generated. "
                        "Regenerate the assignment before posting."
                    ),
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    channel="facebook_groups",
                    campaign=assignment.campaign,
                    source=f"assignment:{assignment.assignment_id}",
                ):
                    recorded += 1

    return recorded
