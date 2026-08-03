from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .channels import CHANNELS, ChannelMode, MarketingChannel
from .models import OwnerFinanceProperty
from .validation import ValidationResult, validate_property_for_launch


class LaunchState(StrEnum):
    BLOCKED = "Blocked"
    READY = "Ready"
    NEEDS_APPROVAL = "Needs Approval"
    ASSISTED_TASK = "Assisted Task"


@dataclass(frozen=True, slots=True)
class ChannelLaunchItem:
    channel: MarketingChannel
    state: LaunchState
    reason: str


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    validation: ValidationResult
    items: tuple[ChannelLaunchItem, ...]

    @property
    def can_launch(self) -> bool:
        return self.validation.can_launch


def build_launch_plan(property_record: OwnerFinanceProperty) -> LaunchPlan:
    validation = validate_property_for_launch(property_record)
    items: list[ChannelLaunchItem] = []

    for channel in CHANNELS:
        if not validation.can_launch:
            items.append(ChannelLaunchItem(channel, LaunchState.BLOCKED, "Fix property validation errors first."))
        elif channel.mode == ChannelMode.AUTOMATIC:
            items.append(ChannelLaunchItem(channel, LaunchState.READY, "Publishes automatically after launch approval."))
        elif channel.mode == ChannelMode.APPROVAL_REQUIRED:
            items.append(ChannelLaunchItem(channel, LaunchState.NEEDS_APPROVAL, "Content or spending requires approval."))
        else:
            items.append(ChannelLaunchItem(channel, LaunchState.ASSISTED_TASK, "Package is prepared; final platform post remains manual."))

    return LaunchPlan(validation=validation, items=tuple(items))
