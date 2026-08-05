from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .campaign_launch import (
    CampaignLaunchState,
    LaunchStatus,
    ensure_all_channels,
)
from .channels import CHANNELS
from .launch_plan import build_launch_plan
from .models import OwnerFinanceProperty


class SimpleFlowStatus(StrEnum):
    COMPLETE = "Complete"
    ACTION_REQUIRED = "Action Required"
    BLOCKED = "Blocked"


PRIMARY_NAVIGATION: tuple[str, ...] = (
    "Simple Marketing Flow",
    "Property Intake",
    "Campaign Readiness",
    "Campaign Launch Center",
    "More Tools",
    "System Setup",
)

MORE_TOOL_OPTIONS: tuple[str, ...] = (
    "Record Manager",
    "Dwelyx Traffic Hub",
    "Marketplace Guard",
)


@dataclass(frozen=True, slots=True)
class SimpleFlowStep:
    number: int
    title: str
    status: SimpleFlowStatus
    detail: str
    destination: str
    button_label: str


@dataclass(frozen=True, slots=True)
class SimpleMarketingFlow:
    property_id: str
    property_address: str
    steps: tuple[SimpleFlowStep, SimpleFlowStep, SimpleFlowStep]
    next_step: SimpleFlowStep
    launched_channels: int
    total_channels: int

    @property
    def complete(self) -> bool:
        return all(step.status == SimpleFlowStatus.COMPLETE for step in self.steps)


def launched_channel_count(state: CampaignLaunchState | None) -> int:
    if state is None:
        return 0
    normalized = ensure_all_channels(state)
    active_statuses = {LaunchStatus.POSTED, LaunchStatus.SCHEDULED}
    return sum(
        record.status in active_statuses
        for record in normalized.channels.values()
    )


def _empty_flow() -> SimpleMarketingFlow:
    step_one = SimpleFlowStep(
        number=1,
        title="Add a property",
        status=SimpleFlowStatus.ACTION_REQUIRED,
        detail="No property is saved yet.",
        destination="Property Intake",
        button_label="Add Property",
    )
    step_two = SimpleFlowStep(
        number=2,
        title="Prepare campaign",
        status=SimpleFlowStatus.BLOCKED,
        detail="Add a property before preparing marketing.",
        destination="Property Intake",
        button_label="Add Property First",
    )
    step_three = SimpleFlowStep(
        number=3,
        title=f"Launch all {len(CHANNELS)} channels",
        status=SimpleFlowStatus.BLOCKED,
        detail="The campaign cannot launch until a property is ready.",
        destination="Property Intake",
        button_label="Add Property First",
    )
    return SimpleMarketingFlow(
        property_id="",
        property_address="",
        steps=(step_one, step_two, step_three),
        next_step=step_one,
        launched_channels=0,
        total_channels=len(CHANNELS),
    )


def build_simple_marketing_flow(
    properties: Sequence[OwnerFinanceProperty],
    *,
    selected_property_id: str = "",
    launch_state: CampaignLaunchState | None = None,
) -> SimpleMarketingFlow:
    if not properties:
        return _empty_flow()

    selected = next(
        (
            item
            for item in properties
            if str(item.property_id) == selected_property_id
        ),
        properties[0],
    )
    plan = build_launch_plan(selected)
    launched = launched_channel_count(launch_state)
    total = len(CHANNELS)

    step_one = SimpleFlowStep(
        number=1,
        title="Property",
        status=SimpleFlowStatus.COMPLETE,
        detail=f"{selected.display_address} is saved.",
        destination="More Tools",
        button_label="Edit Property",
    )

    if plan.can_launch:
        step_two = SimpleFlowStep(
            number=2,
            title="Campaign",
            status=SimpleFlowStatus.COMPLETE,
            detail="Property facts passed the marketing readiness check.",
            destination="Campaign Readiness",
            button_label="Review Campaign",
        )
    else:
        issue_count = len(plan.validation.errors)
        step_two = SimpleFlowStep(
            number=2,
            title="Campaign",
            status=SimpleFlowStatus.ACTION_REQUIRED,
            detail=f"Fix {issue_count} blocking item(s) before marketing.",
            destination="More Tools",
            button_label="Fix Property Information",
        )

    if not plan.can_launch:
        step_three = SimpleFlowStep(
            number=3,
            title=f"{total}-Channel Launch",
            status=SimpleFlowStatus.BLOCKED,
            detail="Launch is blocked until the property passes readiness.",
            destination="More Tools",
            button_label="Fix Property First",
        )
    elif launched == total:
        step_three = SimpleFlowStep(
            number=3,
            title=f"{total}-Channel Launch",
            status=SimpleFlowStatus.COMPLETE,
            detail=f"All {total} channels are recorded Posted or Scheduled.",
            destination="Campaign Launch Center",
            button_label="Review Marketing",
        )
    elif launched == 0:
        step_three = SimpleFlowStep(
            number=3,
            title=f"{total}-Channel Launch",
            status=SimpleFlowStatus.ACTION_REQUIRED,
            detail="No channels are recorded Posted or Scheduled yet.",
            destination="Campaign Launch Center",
            button_label=f"Launch All {total} Channels",
        )
    else:
        step_three = SimpleFlowStep(
            number=3,
            title=f"{total}-Channel Launch",
            status=SimpleFlowStatus.ACTION_REQUIRED,
            detail=f"{launched} of {total} channels are Posted or Scheduled.",
            destination="Campaign Launch Center",
            button_label="Finish Channel Launch",
        )

    steps = (step_one, step_two, step_three)
    next_step = next(
        (
            step
            for step in steps
            if step.status != SimpleFlowStatus.COMPLETE
        ),
        step_three,
    )
    return SimpleMarketingFlow(
        property_id=str(selected.property_id),
        property_address=selected.display_address,
        steps=steps,
        next_step=next_step,
        launched_channels=launched,
        total_channels=total,
    )
