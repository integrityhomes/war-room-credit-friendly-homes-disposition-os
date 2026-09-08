"""Provider-neutral, planning-only models for the CommandCore phone system."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROFIT_DIAL_CANCELLATION_WARNING = (
    "DO NOT CANCEL PROFIT DIAL OR REI BLACKBOOK UNTIL EVERY NUMBER IS VERIFIED "
    "WORKING ON THE NEW PROVIDER."
)


class PhoneProvider(StrEnum):
    QUO_OPENPHONE = "Quo/OpenPhone"
    PROFIT_DIAL = "Profit Dial"
    FUTURE = "Future provider"


class PhonePurpose(StrEnum):
    SELLER = "Seller"
    BUYER = "Buyer"
    DISPOSITIONS = "Dispositions"
    ACQUISITIONS = "Acquisitions"
    MAIN_LINE = "Main line"
    OTHER = "Other"


class PortingStatus(StrEnum):
    INVENTORY_ONLY = "inventory only"
    PORTABILITY_NOT_CHECKED = "portability not checked"
    PORTABILITY_CONFIRMED = "portability confirmed"
    DOCUMENTS_NEEDED = "documents needed"
    READY_TO_PORT = "ready to port"
    PORT_REQUESTED = "port requested"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    KEEP_ON_PROFIT_DIAL = "keep on Profit Dial"


class RoutingCategory(StrEnum):
    SELLER_LEADS = "Seller leads"
    BUYER_LEADS = "Buyer leads"
    ACQUISITIONS = "Acquisitions"
    DISPOSITIONS = "Dispositions"
    GENERAL = "General / main company line"
    AFTER_HOURS = "After-hours calls"
    MISSED_CALLS = "Missed calls"
    VOICEMAIL = "Voicemail"
    STOP_CONSENT = "STOP / consent messages"
    MONEY_LEGAL_HIGH_RISK = "Money / legal / high-risk messages"


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProviderConfiguration(PlanningModel):
    """Describes an adapter binding; it cannot execute provider operations."""

    provider: PhoneProvider
    adapter_name: str = Field(min_length=1, max_length=160)
    configured: bool = False
    inbound_live: bool = False
    outbound_live: bool = False
    webhook_active: bool = False
    account_created_by_commandcore: bool = False
    paid_action_started: bool = False

    @model_validator(mode="after")
    def enforce_offline_foundation(self) -> ProviderConfiguration:
        if any(
            (
                self.inbound_live,
                self.outbound_live,
                self.webhook_active,
                self.account_created_by_commandcore,
                self.paid_action_started,
            )
        ):
            raise ValueError("Phone providers must remain offline in planning mode")
        return self


class PhoneNumberRecord(PlanningModel):
    phone_number: str = Field(min_length=10, max_length=24)
    current_provider: str = Field(min_length=1, max_length=120)
    current_label: str = Field(min_length=1, max_length=120)
    department_purpose: str = Field(min_length=1, max_length=160)
    purpose: PhonePurpose
    assigned_staff_or_team: str = Field(default="", max_length=160)
    inbound_enabled_planned: bool = False
    outbound_enabled_planned: bool = False
    texting_planned: bool = False
    call_recording_planned: bool = False
    voicemail_planned: bool = False
    porting_status: PortingStatus = PortingStatus.INVENTORY_ONLY
    notes: str = Field(default="", max_length=2000)

    @field_validator("phone_number")
    @classmethod
    def normalize_us_phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) == 10:
            digits = f"1{digits}"
        if len(digits) != 11 or not digits.startswith("1"):
            raise ValueError("Enter a valid US phone number")
        return f"+{digits}"


class StaffPhoneAssignment(PlanningModel):
    staff_member: str = Field(min_length=1, max_length=120)
    user_reference: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    assigned_shared_phone_numbers: tuple[str, ...] = ()
    primary_number: str = ""
    backup_number: str = ""
    ring_priority: int = Field(default=1, ge=1, le=100)
    business_hours_availability: str = Field(default="", max_length=500)
    after_hours_routing: str = Field(default="", max_length=500)
    manager_escalation: str = Field(default="", max_length=160)
    active: bool = True

    @model_validator(mode="after")
    def validate_number_assignments(self) -> StaffPhoneAssignment:
        assigned = set(self.assigned_shared_phone_numbers)
        if self.primary_number and self.primary_number not in assigned:
            raise ValueError("Primary number must be one of the assigned shared numbers")
        if self.backup_number and self.backup_number not in assigned:
            raise ValueError("Backup number must be one of the assigned shared numbers")
        return self


class RoutingPlan(PlanningModel):
    category: RoutingCategory
    primary_staff_or_team: str = Field(min_length=1, max_length=160)
    backup_staff_or_team: str = Field(default="", max_length=160)
    instructions: str = Field(default="", max_length=2000)
    manager_approval_required: bool = False
    nevaeh_may_recommend_only: bool = True

    @model_validator(mode="after")
    def preserve_nevaeh_boundary(self) -> RoutingPlan:
        if not self.nevaeh_may_recommend_only:
            raise ValueError("Nevaeh may only recommend routing in planning mode")
        if self.category in {RoutingCategory.STOP_CONSENT, RoutingCategory.MONEY_LEGAL_HIGH_RISK}:
            self.manager_approval_required = True
        return self


class PhoneSystemPlan(PlanningModel):
    numbers: tuple[PhoneNumberRecord, ...] = ()
    assignments: tuple[StaffPhoneAssignment, ...] = ()
    routes: tuple[RoutingPlan, ...] = ()
    providers: tuple[ProviderConfiguration, ...] = ()
    planning_mode: bool = True
    external_actions_allowed: bool = False
    runtime_flag_enabled: bool = False
    port_requests_started: int = 0
    outbound_sms_sent: int = 0
    outbound_calls_made: int = 0
    external_spend_usd: int = 0

    @model_validator(mode="after")
    def enforce_planning_mode(self) -> PhoneSystemPlan:
        if not self.planning_mode or self.external_actions_allowed or self.runtime_flag_enabled:
            raise ValueError("Phone system setup must remain in planning mode")
        if any((self.port_requests_started, self.outbound_sms_sent, self.outbound_calls_made, self.external_spend_usd)):
            raise ValueError("Planning mode cannot perform live, paid, or porting actions")
        return self


class PhoneDashboardSummary(PlanningModel):
    total_phone_numbers: int
    assigned_numbers: int
    unassigned_numbers: int
    numbers_planned_for_port: int
    numbers_ready_for_port: int
    provider_status: str = "Planning only — no provider connected"
    live_inbound_status: str = "OFF"
    live_outbound_status: str = "OFF"
    nevaeh_phone_connection_status: str = "NOT CONNECTED — recommendations only"


def summarize_phone_plan(numbers: Sequence[PhoneNumberRecord]) -> PhoneDashboardSummary:
    assigned = sum(bool(item.assigned_staff_or_team) for item in numbers)
    planned = sum(
        item.porting_status
        not in {PortingStatus.INVENTORY_ONLY, PortingStatus.PORTABILITY_NOT_CHECKED, PortingStatus.KEEP_ON_PROFIT_DIAL}
        for item in numbers
    )
    ready = sum(item.porting_status is PortingStatus.READY_TO_PORT for item in numbers)
    return PhoneDashboardSummary(
        total_phone_numbers=len(numbers),
        assigned_numbers=assigned,
        unassigned_numbers=len(numbers) - assigned,
        numbers_planned_for_port=planned,
        numbers_ready_for_port=ready,
    )


def offline_provider_catalog() -> tuple[ProviderConfiguration, ...]:
    return (
        ProviderConfiguration(
            provider=PhoneProvider.QUO_OPENPHONE,
            adapter_name="commandcore-quo-openphone-adapter",
        ),
        ProviderConfiguration(provider=PhoneProvider.PROFIT_DIAL, adapter_name="not connected — inventory reference only"),
        ProviderConfiguration(provider=PhoneProvider.FUTURE, adapter_name="provider adapter to be selected"),
    )
