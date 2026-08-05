from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .automatic_launch import (
    AutomationDispatchReceipt,
    AutomationDispatchSettings,
    LaunchAction,
    launch_action_for_channel,
    serialize_launch_payload,
    sign_launch_payload,
)
from .buyer_conversion import BuyerConversionLedger, ConversionStage, TERMINAL_STAGES
from .campaign_launch import (
    CampaignLaunchState,
    LaunchStatus,
    ensure_all_channels,
    set_channel_status,
)
from .channels import CHANNELS, CHANNELS_BY_KEY
from .launch_plan import build_launch_plan
from .models import BuyerProfile, OwnerFinanceProperty, PropertyStatus
from .storage import SupabaseSettings

PROPERTY_CONTROL_BUCKET = "cfh-property-marketing-control"
PROPERTY_CONTROL_PATH = "property-marketing-control/ledger.json"
PROPERTY_CONTROL_MAX_BYTES = 4 * 1024 * 1024
PROPERTY_CONTROL_EVENT = "credit_friendly_homes.property.marketing_control"
PROPERTY_CONTROL_SCHEMA_VERSION = "1.0"
PROPERTY_CONTROL_RESPONSE_LIMIT = 500


class PropertyControlError(RuntimeError):
    """Raised when a property shutdown or resume operation cannot be completed."""


class MarketingControlAction(StrEnum):
    PENDING = "Pending / Under Contract"
    FILLED = "Filled"
    SOLD = "Sold"
    PAUSE = "Temporarily Paused"
    RESUME = "Resume Marketing"


class ControlOperation(StrEnum):
    SHUTDOWN = "Shutdown"
    RESUME = "Resume"


class ControlTaskStatus(StrEnum):
    READY = "Ready"
    DISPATCHED = "Dispatched"
    CONFIRMED = "Confirmed"
    FAILED = "Failed"
    NOT_APPLICABLE = "Not Applicable"


class ControlDispatchStatus(StrEnum):
    NOT_ATTEMPTED = "Not Attempted"
    NOT_CONFIGURED = "Not Configured"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"


class ChannelControlTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel_key: str
    channel_name: str
    operation: ControlOperation
    launch_action: str
    requires_manual_confirmation: bool
    instruction: str = Field(min_length=5, max_length=1200)
    status: ControlTaskStatus = ControlTaskStatus.READY
    updated_at: datetime | None = None
    updated_by: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1200)


class BuyerRerouteTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    conversion_record_id: str
    buyer_id: str
    buyer_name: str = Field(default="Unknown buyer", max_length=240)
    current_stage: str
    owner: str = Field(default="Unassigned", max_length=120)
    action: str = Field(min_length=5, max_length=1000)
    status: ControlTaskStatus = ControlTaskStatus.READY
    updated_at: datetime | None = None
    updated_by: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1200)


class PropertyControlEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    property_id: str
    property_address: str = Field(min_length=2, max_length=320)
    campaign: str = Field(default="owner_finance_homes", max_length=160)
    action: MarketingControlAction
    operation: ControlOperation
    previous_status: str
    new_status: str
    reason: str = Field(min_length=5, max_length=1500)
    notes: str = Field(default="", max_length=3000)
    requested_by: str = Field(min_length=2, max_length=120)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    winning_conversion_record_id: str = ""
    channel_tasks: list[ChannelControlTask] = Field(default_factory=list)
    buyer_tasks: list[BuyerRerouteTask] = Field(default_factory=list)
    dispatch_status: ControlDispatchStatus = ControlDispatchStatus.NOT_ATTEMPTED
    dispatch_detail: str = Field(default="", max_length=1500)
    dispatch_at: datetime | None = None

    @model_validator(mode="after")
    def validate_channel_coverage(self) -> PropertyControlEvent:
        keys = [task.channel_key for task in self.channel_tasks]
        if len(keys) != len(CHANNELS) or set(keys) != set(CHANNELS_BY_KEY):
            raise ValueError("A property control event must contain every current marketing channel")
        return self


class PropertyControlLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: list[PropertyControlEvent] = Field(default_factory=list)


def _current(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def operation_for_action(action: MarketingControlAction) -> ControlOperation:
    return ControlOperation.RESUME if action == MarketingControlAction.RESUME else ControlOperation.SHUTDOWN


def property_status_for_action(action: MarketingControlAction) -> PropertyStatus:
    mapping = {
        MarketingControlAction.PENDING: PropertyStatus.PENDING,
        MarketingControlAction.FILLED: PropertyStatus.FILLED,
        MarketingControlAction.SOLD: PropertyStatus.SOLD,
        MarketingControlAction.PAUSE: PropertyStatus.PAUSED,
        MarketingControlAction.RESUME: PropertyStatus.LIVE,
    }
    return mapping[action]


def updated_property_for_action(
    property_record: OwnerFinanceProperty,
    action: MarketingControlAction,
    *,
    now: datetime | None = None,
) -> OwnerFinanceProperty:
    new_status = property_status_for_action(action)
    if property_record.status == new_status:
        raise PropertyControlError(f"This property is already marked {new_status.value}.")
    updated = property_record.model_copy(
        update={
            "status": new_status,
            "updated_at": _current(now),
        }
    )
    if action == MarketingControlAction.RESUME:
        plan = build_launch_plan(updated)
        if not plan.can_launch:
            raise PropertyControlError(
                "Marketing cannot resume until the property passes the launch gate: "
                + "; ".join(plan.validation.errors)
            )
    return updated


def _shutdown_instruction(channel_key: str, channel_name: str, action: LaunchAction) -> str:
    if channel_key == "property_page":
        return "The property is hidden from the Credit Friendly Homes public portal immediately after its status is saved."
    if channel_key == "marketplace":
        return "Open the active Facebook Marketplace listing, mark it pending or sold when accurate, and remove any call for new buyer inquiries."
    if channel_key == "facebook_groups":
        return "Review every group where this property was posted and comment, edit, or remove the post so buyers know it is unavailable."
    if channel_key == "classifieds":
        return "Remove or pause every active classified listing and record the listing location or confirmation in this task."
    if channel_key == "nextdoor":
        return "Remove or update the Nextdoor Business Post and pause the paid housing ad. Confirm both organic and paid placements separately in the notes."
    if action == LaunchAction.AUTO_PUBLISH:
        return f"Send a property-wide pause or removal instruction for {channel_name} through the connected publishing workflow."
    return f"Review {channel_name} and stop any active property promotion."


def _resume_instruction(channel_key: str, channel_name: str, action: LaunchAction) -> str:
    if channel_key == "property_page":
        return "The property returns to the Credit Friendly Homes public portal immediately after the Live status passes the launch gate."
    if channel_key == "marketplace":
        return "Review the monthly Marketplace safety counter, then manually create or reactivate one accurate For Sale listing if permitted."
    if channel_key == "facebook_groups":
        return "Use the approved Facebook Group posting workflow and current cooldown rules before reposting the property."
    if channel_key == "classifieds":
        return "Review each classified platform and manually create or reactivate the current property listing."
    if channel_key == "nextdoor":
        return "Review the current Nextdoor package, then manually republish the Business Post or restart the paid housing ad after manager approval."
    if action == LaunchAction.AUTO_PUBLISH:
        return f"Send a resume or republish instruction for {channel_name} through the connected publishing workflow."
    return f"Review {channel_name} and restore the current approved property campaign."


def build_channel_control_tasks(
    action: MarketingControlAction,
    *,
    now: datetime | None = None,
) -> list[ChannelControlTask]:
    timestamp = _current(now)
    operation = operation_for_action(action)
    tasks: list[ChannelControlTask] = []
    for channel in CHANNELS:
        launch_action = launch_action_for_channel(channel)
        instruction = (
            _resume_instruction(channel.key, channel.name, launch_action)
            if operation == ControlOperation.RESUME
            else _shutdown_instruction(channel.key, channel.name, launch_action)
        )
        internal = channel.key == "property_page"
        tasks.append(
            ChannelControlTask(
                channel_key=channel.key,
                channel_name=channel.name,
                operation=operation,
                launch_action=launch_action.value,
                requires_manual_confirmation=(
                    launch_action == LaunchAction.MANUAL_FINAL_POST and not internal
                ),
                instruction=instruction,
                status=(ControlTaskStatus.CONFIRMED if internal else ControlTaskStatus.READY),
                updated_at=(timestamp if internal else None),
                updated_by=("System" if internal else ""),
                notes=("Property status controls public visibility." if internal else ""),
            )
        )
    return tasks


def _buyer_name(buyer: BuyerProfile | None, buyer_id: str) -> str:
    if buyer is None:
        return f"Buyer {buyer_id[:8]}"
    name = " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()
    return name or f"Buyer {buyer_id[:8]}"


def build_buyer_reroute_tasks(
    conversion_ledger: BuyerConversionLedger,
    buyers: Sequence[BuyerProfile],
    *,
    property_id: str,
    action: MarketingControlAction,
    winning_conversion_record_id: str = "",
) -> list[BuyerRerouteTask]:
    buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
    tasks: list[BuyerRerouteTask] = []
    for record in conversion_ledger.records:
        if record.property_id != str(property_id) or record.stage in TERMINAL_STAGES:
            continue
        winner = bool(winning_conversion_record_id and record.record_id == winning_conversion_record_id)
        if winner and action in {
            MarketingControlAction.PENDING,
            MarketingControlAction.FILLED,
            MarketingControlAction.SOLD,
        }:
            instruction = "Keep this buyer attached to the selected property and complete the pending contract or move-in workflow."
            status = ControlTaskStatus.NOT_APPLICABLE
        elif action == MarketingControlAction.PAUSE:
            instruction = "Pause property-specific follow-up and decide whether this buyer should wait or be offered another available Dwelyx home."
            status = ControlTaskStatus.READY
        elif action == MarketingControlAction.RESUME:
            instruction = "Review the buyer's current interest and restore property-specific follow-up only when consent and availability are confirmed."
            status = ControlTaskStatus.READY
        else:
            instruction = "Stop promoting this unavailable property to the buyer and reassign the buyer to another available Dwelyx home."
            status = ControlTaskStatus.READY
        tasks.append(
            BuyerRerouteTask(
                conversion_record_id=record.record_id,
                buyer_id=record.buyer_id,
                buyer_name=_buyer_name(buyers_by_id.get(record.buyer_id), record.buyer_id),
                current_stage=record.stage.value,
                owner=record.owner or "Unassigned",
                action=instruction,
                status=status,
            )
        )
    return tasks


def build_property_control_event(
    property_record: OwnerFinanceProperty,
    action: MarketingControlAction,
    *,
    reason: str,
    requested_by: str,
    campaign: str = "owner_finance_homes",
    notes: str = "",
    conversion_ledger: BuyerConversionLedger | None = None,
    buyers: Sequence[BuyerProfile] = (),
    winning_conversion_record_id: str = "",
    now: datetime | None = None,
) -> tuple[OwnerFinanceProperty, PropertyControlEvent]:
    if not reason.strip():
        raise PropertyControlError("Enter the reason for this property status change.")
    if not requested_by.strip():
        raise PropertyControlError("Enter the team member authorizing this action.")
    timestamp = _current(now)
    updated_property = updated_property_for_action(property_record, action, now=timestamp)
    buyer_tasks = build_buyer_reroute_tasks(
        conversion_ledger or BuyerConversionLedger(),
        buyers,
        property_id=str(property_record.property_id),
        action=action,
        winning_conversion_record_id=winning_conversion_record_id,
    )
    event = PropertyControlEvent(
        property_id=str(property_record.property_id),
        property_address=property_record.display_address,
        campaign=campaign.strip() or "owner_finance_homes",
        action=action,
        operation=operation_for_action(action),
        previous_status=property_record.status.value,
        new_status=updated_property.status.value,
        reason=reason,
        notes=notes,
        requested_by=requested_by,
        requested_at=timestamp,
        winning_conversion_record_id=winning_conversion_record_id,
        channel_tasks=build_channel_control_tasks(action, now=timestamp),
        buyer_tasks=buyer_tasks,
    )
    return updated_property, event


def append_control_event(
    ledger: PropertyControlLedger,
    event: PropertyControlEvent,
) -> PropertyControlLedger:
    return ledger.model_copy(
        update={
            "events": [*ledger.events, event],
            "updated_at": event.requested_at,
        }
    )


def find_control_event(
    ledger: PropertyControlLedger,
    event_id: str,
) -> PropertyControlEvent | None:
    return next((event for event in ledger.events if event.event_id == event_id), None)


def _replace_event(
    ledger: PropertyControlLedger,
    updated_event: PropertyControlEvent,
    *,
    now: datetime | None = None,
) -> PropertyControlLedger:
    timestamp = _current(now)
    events = [
        updated_event if event.event_id == updated_event.event_id else event
        for event in ledger.events
    ]
    return ledger.model_copy(update={"events": events, "updated_at": timestamp})


def update_channel_task(
    ledger: PropertyControlLedger,
    *,
    event_id: str,
    channel_key: str,
    status: ControlTaskStatus,
    updated_by: str,
    notes: str = "",
    now: datetime | None = None,
) -> PropertyControlLedger:
    event = find_control_event(ledger, event_id)
    if event is None:
        raise PropertyControlError("The selected property control event could not be found.")
    if channel_key not in CHANNELS_BY_KEY:
        raise PropertyControlError("The selected marketing channel is not registered.")
    timestamp = _current(now)
    tasks = [
        task.model_copy(
            update={
                "status": status,
                "updated_at": timestamp,
                "updated_by": updated_by.strip(),
                "notes": notes.strip(),
            }
        )
        if task.channel_key == channel_key
        else task
        for task in event.channel_tasks
    ]
    return _replace_event(ledger, event.model_copy(update={"channel_tasks": tasks}), now=timestamp)


def update_buyer_task(
    ledger: PropertyControlLedger,
    *,
    event_id: str,
    conversion_record_id: str,
    status: ControlTaskStatus,
    updated_by: str,
    notes: str = "",
    now: datetime | None = None,
) -> PropertyControlLedger:
    event = find_control_event(ledger, event_id)
    if event is None:
        raise PropertyControlError("The selected property control event could not be found.")
    timestamp = _current(now)
    matched = False
    tasks: list[BuyerRerouteTask] = []
    for task in event.buyer_tasks:
        if task.conversion_record_id == conversion_record_id:
            matched = True
            tasks.append(
                task.model_copy(
                    update={
                        "status": status,
                        "updated_at": timestamp,
                        "updated_by": updated_by.strip(),
                        "notes": notes.strip(),
                    }
                )
            )
        else:
            tasks.append(task)
    if not matched:
        raise PropertyControlError("The selected buyer reroute task could not be found.")
    return _replace_event(ledger, event.model_copy(update={"buyer_tasks": tasks}), now=timestamp)


def mark_control_dispatch(
    ledger: PropertyControlLedger,
    *,
    event_id: str,
    status: ControlDispatchStatus,
    detail: str = "",
    now: datetime | None = None,
) -> PropertyControlLedger:
    event = find_control_event(ledger, event_id)
    if event is None:
        raise PropertyControlError("The selected property control event could not be found.")
    timestamp = _current(now)
    channel_tasks: list[ChannelControlTask] = []
    for task in event.channel_tasks:
        channel = CHANNELS_BY_KEY[task.channel_key]
        action = launch_action_for_channel(channel)
        if task.channel_key == "property_page" or action == LaunchAction.MANUAL_FINAL_POST:
            channel_tasks.append(task)
            continue
        if status == ControlDispatchStatus.SUCCEEDED:
            task_status = ControlTaskStatus.DISPATCHED
        elif status == ControlDispatchStatus.FAILED:
            task_status = ControlTaskStatus.FAILED
        else:
            task_status = ControlTaskStatus.READY
        channel_tasks.append(
            task.model_copy(
                update={
                    "status": task_status,
                    "updated_at": timestamp,
                    "updated_by": "Publishing workflow",
                    "notes": detail[:1200],
                }
            )
        )
    updated = event.model_copy(
        update={
            "channel_tasks": channel_tasks,
            "dispatch_status": status,
            "dispatch_detail": detail[:1500],
            "dispatch_at": timestamp,
        }
    )
    return _replace_event(ledger, updated, now=timestamp)


def build_property_control_payload(event: PropertyControlEvent) -> dict[str, Any]:
    return {
        "schema_version": PROPERTY_CONTROL_SCHEMA_VERSION,
        "event": PROPERTY_CONTROL_EVENT,
        "requested_at": event.requested_at.astimezone(UTC).isoformat(),
        "requested_by": event.requested_by,
        "campaign": event.campaign,
        "operation": event.operation.value.lower(),
        "action": event.action.value,
        "reason": event.reason,
        "property": {
            "property_id": event.property_id,
            "address": event.property_address,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
        },
        "buyer_reroute": {
            "affected_active_records": sum(
                task.status != ControlTaskStatus.NOT_APPLICABLE for task in event.buyer_tasks
            ),
            "winning_conversion_record_id": event.winning_conversion_record_id or None,
            "send_buyer_personal_data": False,
        },
        "buyer_destination": {
            "old_property_links_redirect_to_full_inventory": True,
            "publish_property_to_dwelyx": False,
            "property_sync_to_dwelyx": False,
        },
        "channels": [
            {
                "channel_key": task.channel_key,
                "channel_name": task.channel_name,
                "operation": task.operation.value.lower(),
                "launch_action": task.launch_action,
                "requires_manual_confirmation": task.requires_manual_confirmation,
                "instruction": task.instruction,
            }
            for task in event.channel_tasks
        ],
    }


def dispatch_property_control(
    event: PropertyControlEvent,
    settings: AutomationDispatchSettings,
) -> AutomationDispatchReceipt:
    if not settings.configured:
        raise PropertyControlError(
            "The publishing workflow is not connected. The property status was still saved locally, and the task board remains available."
        )
    body = serialize_launch_payload(build_property_control_payload(event))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Credit-Friendly-Homes-Disposition-OS/1.0",
        "X-CFH-Event": PROPERTY_CONTROL_EVENT,
    }
    signature = sign_launch_payload(body, settings.signing_secret)
    if signature:
        headers["X-CFH-Signature"] = signature
    request = Request(settings.webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")[:PROPERTY_CONTROL_RESPONSE_LIMIT]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:PROPERTY_CONTROL_RESPONSE_LIMIT]
        raise PropertyControlError(
            f"The publishing workflow rejected the property control request (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise PropertyControlError(
            "The publishing workflow could not be reached. Use the saved task board to stop or resume each channel manually."
        ) from exc
    if not 200 <= status_code < 300:
        raise PropertyControlError(
            f"The publishing workflow returned HTTP {status_code}. Use the saved task board to control each channel manually."
        )
    return AutomationDispatchReceipt(
        status_code=status_code,
        sent_at=datetime.now(UTC),
        response_text=response_text,
    )


def campaign_state_after_control(
    state: CampaignLaunchState,
    event: PropertyControlEvent,
    *,
    dispatch_status: ControlDispatchStatus,
    now: datetime | None = None,
) -> CampaignLaunchState:
    timestamp = _current(now)
    updated = ensure_all_channels(state)
    for channel in CHANNELS:
        launch_action = launch_action_for_channel(channel)
        if channel.key == "property_page":
            status = (
                LaunchStatus.POSTED
                if event.operation == ControlOperation.RESUME
                else LaunchStatus.PAUSED
            )
            note = "Public visibility updated by the saved property status."
        elif launch_action == LaunchAction.MANUAL_FINAL_POST:
            status = LaunchStatus.READY
            note = "Manual platform confirmation is still required."
        elif dispatch_status == ControlDispatchStatus.SUCCEEDED:
            status = (
                LaunchStatus.SCHEDULED
                if event.operation == ControlOperation.RESUME
                else LaunchStatus.PAUSED
            )
            note = "The connected publishing workflow accepted the property control request."
        elif dispatch_status == ControlDispatchStatus.FAILED:
            status = LaunchStatus.FAILED
            note = "The publishing workflow did not confirm this property control request."
        else:
            status = LaunchStatus.READY
            note = "The publishing workflow is not connected; complete this task manually."
        updated = set_channel_status(
            updated,
            channel.key,
            status,
            updated_by=event.requested_by,
            notes=note,
            now=timestamp,
        )
    return updated


def channel_task_rows(event: PropertyControlEvent) -> list[dict[str, str]]:
    return [
        {
            "Channel": task.channel_name,
            "Operation": task.operation.value,
            "Status": task.status.value,
            "Manual Confirmation": "Yes" if task.requires_manual_confirmation else "No",
            "Instruction": task.instruction,
            "Updated By": task.updated_by or "—",
            "Notes": task.notes or "—",
        }
        for task in event.channel_tasks
    ]


def buyer_task_rows(event: PropertyControlEvent) -> list[dict[str, str]]:
    return [
        {
            "Buyer": task.buyer_name,
            "Current Stage": task.current_stage,
            "Owner": task.owner,
            "Status": task.status.value,
            "Required Action": task.action,
            "Updated By": task.updated_by or "—",
            "Notes": task.notes or "—",
        }
        for task in event.buyer_tasks
    ]


def event_history_rows(ledger: PropertyControlLedger) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for event in sorted(ledger.events, key=lambda item: item.requested_at, reverse=True):
        rows.append(
            {
                "When": event.requested_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Property": event.property_address,
                "Action": event.action.value,
                "From": event.previous_status,
                "To": event.new_status,
                "Requested By": event.requested_by,
                "Dispatch": event.dispatch_status.value,
                "Open Channel Tasks": sum(
                    task.status in {ControlTaskStatus.READY, ControlTaskStatus.FAILED}
                    for task in event.channel_tasks
                ),
                "Open Buyer Tasks": sum(
                    task.status in {ControlTaskStatus.READY, ControlTaskStatus.FAILED}
                    for task in event.buyer_tasks
                ),
                "Reason": event.reason,
            }
        )
    return rows


class PropertyControlStore:
    """Private Supabase Storage ledger for shutdown, resume, and buyer-reroute work."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise PropertyControlError("Supabase is not configured for property control records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise PropertyControlError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(PROPERTY_CONTROL_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    PROPERTY_CONTROL_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": PROPERTY_CONTROL_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise PropertyControlError("Could not create the private property-control bucket.") from exc
        self._bucket_ready = True

    def load(self) -> PropertyControlLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(PROPERTY_CONTROL_BUCKET).download(PROPERTY_CONTROL_PATH)
        except Exception:
            return PropertyControlLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return PropertyControlLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PropertyControlError("The saved property-control ledger could not be read.") from exc

    def save(self, ledger: PropertyControlLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > PROPERTY_CONTROL_MAX_BYTES:
            raise PropertyControlError("The property-control ledger is too large to save.")
        try:
            self._client.storage.from_(PROPERTY_CONTROL_BUCKET).upload(
                path=PROPERTY_CONTROL_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise PropertyControlError("Could not save the property-control ledger.") from exc
