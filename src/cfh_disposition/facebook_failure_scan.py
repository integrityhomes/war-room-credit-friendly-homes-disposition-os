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
from .operational_failures import (
    CriticalFailureType,
    OperationalFailureError,
    OperationalFailureStore,
    open_failures,
    record_operational_failure,
)


def _key(
    *,
    property_id: str = "",
    channel: str = "facebook_groups",
    campaign: str = "owner_finance_homes",
    source: str = "",
) -> str:
    return "|".join(
        [CriticalFailureType.FACEBOOK_TASK.value, property_id, channel, campaign, source]
    ).casefold()


def scan_facebook_operational_failures(
    values: Mapping[str, Any],
    properties: Sequence[OwnerFinanceProperty],
) -> int:
    """Promote actionable Facebook work failures into the critical failure ledger.

    Existing open failures are not re-recorded on every Streamlit rerun; repeat counts should
    represent real repeated incidents rather than page refreshes.
    """
    recorded = 0
    properties_by_id = {str(item.property_id): item for item in properties}
    try:
        open_keys = {
            item.occurrence_key
            for item in open_failures(OperationalFailureStore(values).load())
            if item.occurrence_key
        }
    except OperationalFailureError:
        open_keys = set()

    def record_once(
        *,
        summary: str,
        technical_detail: str,
        property_id: str = "",
        property_address: str = "",
        campaign: str = "owner_finance_homes",
        source: str = "",
    ) -> None:
        nonlocal recorded
        occurrence_key = _key(
            property_id=property_id,
            campaign=campaign,
            source=source,
        )
        if occurrence_key in open_keys:
            return
        if record_operational_failure(
            values,
            CriticalFailureType.FACEBOOK_TASK,
            summary=summary,
            technical_detail=technical_detail,
            property_id=property_id,
            property_address=property_address,
            channel="facebook_groups",
            campaign=campaign,
            source=source,
        ):
            recorded += 1
            open_keys.add(occurrence_key)

    try:
        assignment_ledger = FacebookAssignmentStore(values).load()
    except FacebookAssignmentError as exc:
        record_once(
            summary="Facebook assignment ledger could not be loaded.",
            technical_detail=str(exc),
            source="facebook_assignment_dashboard",
        )
        assignment_ledger = None

    try:
        group_ledger = FacebookGroupStore(values).load()
    except FacebookGroupError as exc:
        record_once(
            summary="Facebook Group directory/posting ledger could not be loaded.",
            technical_detail=str(exc),
            source="facebook_group_posting_center",
        )
        group_ledger = None

    if group_ledger is not None:
        for group in active_groups(group_ledger):
            if group.group_url:
                continue
            record_once(
                summary=f"Active Facebook Group is missing its saved URL: {group.name}.",
                technical_detail=(
                    "The VA cannot open the exact destination from the Daily Board until the "
                    "group URL is added in the Facebook Group Directory."
                ),
                source=f"group:{group.group_id}",
            )

    if assignment_ledger is not None:
        for assignment in assignment_ledger.assignments:
            if assignment.status in {AssignmentStatus.POSTED, AssignmentStatus.SKIPPED}:
                continue
            property_record = properties_by_id.get(assignment.property_id)
            source = f"assignment:{assignment.assignment_id}"
            if assignment.status == AssignmentStatus.NEEDS_REVIEW:
                record_once(
                    summary=(
                        f"Facebook assignment needs manager review: {assignment.property_address} "
                        f"→ {assignment.group_name}."
                    ),
                    technical_detail=assignment.notes or "Assignment was moved to Needs Review.",
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    campaign=assignment.campaign,
                    source=source,
                )
            if not assignment.group_url:
                record_once(
                    summary=(
                        f"Facebook assignment has no group URL: {assignment.property_address} "
                        f"→ {assignment.group_name}."
                    ),
                    technical_detail=(
                        "The assignment cannot be completed from the VA board until the group URL is saved."
                    ),
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    campaign=assignment.campaign,
                    source=source,
                )
            if property_record is not None and property_record.updated_at > assignment.created_at:
                record_once(
                    summary=(
                        "Facebook assignment is stale after a property fact change: "
                        f"{assignment.property_address} → {assignment.group_name}."
                    ),
                    technical_detail=(
                        "The central property record changed after this assignment was generated. "
                        "Regenerate the assignment before posting."
                    ),
                    property_id=assignment.property_id,
                    property_address=assignment.property_address,
                    campaign=assignment.campaign,
                    source=source,
                )

    return recorded
