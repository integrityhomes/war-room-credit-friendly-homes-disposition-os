from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PortStatus(StrEnum):
    NOT_PLANNED = "Not planned"
    INVENTORY_REVIEW = "Inventory review"
    READY_FOR_OWNER_REVIEW = "Ready for owner review"
    REQUESTED = "Requested"
    IN_PROGRESS = "In progress"
    COMPLETED = "Completed"
    BLOCKED = "Blocked"


class TestStatus(StrEnum):
    NOT_TESTED = "Not tested"
    PASSED = "Passed"
    FAILED = "Failed"
    NOT_APPLICABLE = "Not applicable"


class CancellationSafetyStatus(StrEnum):
    KEEP_ACTIVE = "Keep old provider active"
    READY_FOR_OWNER_REVIEW = "Ready for owner review"
    SAFE_TO_CANCEL = "Safe to cancel"
    CANCELLED = "Cancelled"


class PhoneNumberMigrationRecord(BaseModel):
    """Planning-only inventory record; it never authorizes or performs a port."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_number: str = Field(min_length=10, max_length=24)
    current_provider: str = Field(min_length=1, max_length=120)
    business_purpose: str = Field(min_length=1, max_length=240)
    assigned_team_or_person: str = Field(default="", max_length=120)
    market_or_campaign: str = Field(default="", max_length=160)
    port_status: PortStatus = PortStatus.NOT_PLANNED
    requested_date: date | None = None
    completed_date: date | None = None
    test_call_status: TestStatus = TestStatus.NOT_TESTED
    test_sms_status: TestStatus = TestStatus.NOT_TESTED
    old_provider_cancellation_safety_status: CancellationSafetyStatus = CancellationSafetyStatus.KEEP_ACTIVE

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) not in {10, 11}:
            raise ValueError("Enter a valid 10-digit US phone number")
        if len(digits) == 11 and not digits.startswith("1"):
            raise ValueError("Enter a valid US country code")
        return f"+{digits}" if len(digits) == 11 else f"+1{digits}"

    @model_validator(mode="after")
    def validate_migration_dates(self) -> PhoneNumberMigrationRecord:
        if self.completed_date and not self.requested_date:
            raise ValueError("A requested date is required before a completed date")
        if self.completed_date and self.requested_date and self.completed_date < self.requested_date:
            raise ValueError("The completed date cannot be before the requested date")
        if self.port_status == PortStatus.COMPLETED and not self.completed_date:
            raise ValueError("A completed port must include its completion date")
        return self


class PhoneNumberMigrationInventory(BaseModel):
    """Safe design model only; persistence and port execution are outside this build."""

    model_config = ConfigDict(extra="forbid")

    records: list[PhoneNumberMigrationRecord] = Field(default_factory=list)
    live_porting_authorized: bool = False
    external_action_started: bool = False

    @model_validator(mode="after")
    def enforce_planning_only(self) -> PhoneNumberMigrationInventory:
        if self.live_porting_authorized or self.external_action_started:
            raise ValueError("This inventory cannot authorize or start phone-number porting")
        return self
