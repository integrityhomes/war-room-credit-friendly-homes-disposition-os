"""Provider-neutral, planning-only models for the CommandCore phone system."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

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
    MARKETING_DIALER_POOL = "Marketing / dialer pool"
    STAFF_LINE = "STAFF LINE"
    OTHER = "Other"


class OperationalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE_RESERVED = "INACTIVE / RESERVED"
    UNKNOWN_NEEDS_REVIEW = "UNKNOWN / NEEDS REVIEW"


class PortingStatus(StrEnum):
    KEEP_PROTECTED_MIGRATION_UNDECIDED = "KEEP / PROTECTED — MIGRATION UNDECIDED"
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
    record_id: str = Field(default_factory=lambda: str(uuid4()))
    phone_number: str = Field(min_length=10, max_length=24)
    current_provider: str = Field(min_length=1, max_length=120)
    current_label: str = Field(min_length=1, max_length=120)
    department_purpose: str = Field(default="", max_length=160)
    purpose: PhonePurpose
    provider_pool_id: str = Field(default="", max_length=160)
    assigned_staff_or_team: str = Field(default="", max_length=160)
    inbound_enabled_planned: bool = False
    outbound_enabled_planned: bool = False
    texting_planned: bool = False
    call_recording_planned: bool = False
    voicemail_planned: bool = False
    porting_status: PortingStatus = PortingStatus.KEEP_PROTECTED_MIGRATION_UNDECIDED
    notes: str = Field(default="", max_length=2000)
    operational_status: OperationalStatus = OperationalStatus.UNKNOWN_NEEDS_REVIEW
    active: bool = True
    actor_reference: str = Field(default="authenticated-commandcore-user", min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def read_legacy_active_status(cls, value: Any) -> Any:
        if isinstance(value, dict) and "operational_status" not in value and "active" in value:
            value = dict(value)
            value["operational_status"] = (
                OperationalStatus.ACTIVE if value["active"] else OperationalStatus.INACTIVE_RESERVED
            )
        return value

    @model_validator(mode="after")
    def keep_legacy_active_compatible(self) -> PhoneNumberRecord:
        self.active = self.operational_status is not OperationalStatus.INACTIVE_RESERVED
        return self

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
    assignment_id: str = Field(default_factory=lambda: str(uuid4()))
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
    actor_reference: str = Field(default="authenticated-commandcore-user", min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_number_assignments(self) -> StaffPhoneAssignment:
        assigned = set(self.assigned_shared_phone_numbers)
        if self.primary_number and self.primary_number not in assigned:
            raise ValueError("Primary number must be one of the assigned shared numbers")
        if self.backup_number and self.backup_number not in assigned:
            raise ValueError("Backup number must be one of the assigned shared numbers")
        return self


class RoutingPlan(PlanningModel):
    route_id: str = Field(default_factory=lambda: str(uuid4()))
    category: RoutingCategory
    primary_staff_or_team: str = Field(min_length=1, max_length=160)
    backup_staff_or_team: str = Field(default="", max_length=160)
    instructions: str = Field(default="", max_length=2000)
    manager_approval_required: bool = False
    nevaeh_may_recommend_only: bool = True
    active: bool = True
    actor_reference: str = Field(default="authenticated-commandcore-user", min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def preserve_nevaeh_boundary(self) -> RoutingPlan:
        if not self.nevaeh_may_recommend_only:
            raise ValueError("Nevaeh may only recommend routing in planning mode")
        if self.category in {RoutingCategory.STOP_CONSENT, RoutingCategory.MONEY_LEGAL_HIGH_RISK}:
            self.manager_approval_required = True
        return self


class PhoneProviderPool(PlanningModel):
    """Provider/category planning container that does not require a phone number."""

    pool_id: str = Field(default_factory=lambda: str(uuid4()))
    provider_name: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    category: PhonePurpose = PhonePurpose.MARKETING_DIALER_POOL
    operational_status: OperationalStatus = OperationalStatus.UNKNOWN_NEEDS_REVIEW
    notes: str = Field(default="", max_length=2000)
    active: bool = True
    actor_reference: str = Field(default="authenticated-commandcore-user", min_length=1, max_length=160)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def require_marketing_dialer_pool_category(self) -> PhoneProviderPool:
        if self.category is not PhonePurpose.MARKETING_DIALER_POOL:
            raise ValueError("Provider pools must use the marketing / dialer pool category")
        self.active = self.operational_status is not OperationalStatus.INACTIVE_RESERVED
        return self


class PhoneSystemPlan(PlanningModel):
    numbers: tuple[PhoneNumberRecord, ...] = ()
    provider_pools: tuple[PhoneProviderPool, ...] = ()
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
        not in {
            PortingStatus.KEEP_PROTECTED_MIGRATION_UNDECIDED,
            PortingStatus.INVENTORY_ONLY,
            PortingStatus.PORTABILITY_NOT_CHECKED,
            PortingStatus.KEEP_ON_PROFIT_DIAL,
        }
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


PHONE_INVENTORY_DOCUMENT = "phone_system_inventory"
PHONE_ASSIGNMENT_DOCUMENT = "phone_system_staff_assignment"
PHONE_ROUTE_DOCUMENT = "phone_system_routing_plan"
PHONE_PROVIDER_POOL_DOCUMENT = "phone_system_provider_pool"
PHONE_AUDIT_DOCUMENT = "phone_system_audit_event"
PHONE_DOCUMENT_TYPES = {
    PHONE_INVENTORY_DOCUMENT,
    PHONE_ASSIGNMENT_DOCUMENT,
    PHONE_ROUTE_DOCUMENT,
    PHONE_PROVIDER_POOL_DOCUMENT,
    PHONE_AUDIT_DOCUMENT,
}
_PROHIBITED_CREDENTIAL_KEYS = re.compile(
    r"(?:password|passcode|pin|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"oauth|secret|private[_ -]?key|carrier[_ -]?account)",
    re.IGNORECASE,
)
_PROHIBITED_CREDENTIAL_VALUES = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{8,}|"
    r"\b(?:password|passcode|pin|api[_ -]?key|token|secret)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)


class PhonePlanningStorageError(RuntimeError):
    """Raised when private planning persistence fails safely."""


def normalize_phone_planning_crm_response(response: Any) -> dict[str, Any]:
    """Normalize supported CRM client responses without exposing record contents."""
    if isinstance(response, dict):
        return response

    if not isinstance(response, (bytes, bytearray)):
        try:
            response = response.data
        except Exception:
            raise PhonePlanningStorageError(
                "Private phone planning storage returned an unsupported response"
            ) from None

    if isinstance(response, (bytes, bytearray)):
        try:
            response = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PhonePlanningStorageError(
                "Private phone planning storage returned an invalid response"
            ) from None

    if not isinstance(response, dict):
        raise PhonePlanningStorageError(
            "Private phone planning storage returned an unsupported response"
        )
    return response


class CrmCall(Protocol):
    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def reject_credentials(value: Any, path: str = "record") -> None:
    """Reject credential-shaped keys or values before private persistence."""
    if isinstance(value, dict):
        for key, item in value.items():
            if _PROHIBITED_CREDENTIAL_KEYS.search(str(key)):
                raise ValueError(f"Credentials are prohibited in phone planning records ({path}.{key})")
            reject_credentials(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_credentials(item, f"{path}[{index}]")
    elif isinstance(value, str) and _PROHIBITED_CREDENTIAL_VALUES.search(value):
        raise ValueError(f"Credentials are prohibited in phone planning records ({path})")


class PhonePlanningDocumentStore:
    """Phone planning records stored in existing private CRM documents."""

    def __init__(self, crm_call: CrmCall) -> None:
        self._crm_call = crm_call

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._crm_call(payload)
        if result.get("ok") is not True:
            raise PhonePlanningStorageError("Private phone planning storage is unavailable")
        return result

    def _documents(self) -> list[dict[str, Any]]:
        result = self._call(
            {"action": "list", "entity": "documents", "limit": 500, "include_archived": True}
        )
        records = result.get("records", [])
        return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []

    def _typed_payloads(self, document_type: str) -> list[dict[str, Any]]:
        return [
            payload
            for item in self._documents()
            if item.get("document_type") == document_type
            and isinstance((payload := item.get("payload")), dict)
        ]

    def list_numbers(self, *, include_inactive: bool = False) -> tuple[PhoneNumberRecord, ...]:
        records = tuple(PhoneNumberRecord.model_validate(item) for item in self._typed_payloads(PHONE_INVENTORY_DOCUMENT))
        return records if include_inactive else tuple(item for item in records if item.active)

    def list_assignments(self, *, include_inactive: bool = False) -> tuple[StaffPhoneAssignment, ...]:
        records = tuple(StaffPhoneAssignment.model_validate(item) for item in self._typed_payloads(PHONE_ASSIGNMENT_DOCUMENT))
        return records if include_inactive else tuple(item for item in records if item.active)

    def list_routes(self, *, include_inactive: bool = False) -> tuple[RoutingPlan, ...]:
        records = tuple(RoutingPlan.model_validate(item) for item in self._typed_payloads(PHONE_ROUTE_DOCUMENT))
        return records if include_inactive else tuple(item for item in records if item.active)

    def list_provider_pools(self, *, include_inactive: bool = False) -> tuple[PhoneProviderPool, ...]:
        records = tuple(
            PhoneProviderPool.model_validate(item)
            for item in self._typed_payloads(PHONE_PROVIDER_POOL_DOCUMENT)
        )
        return records if include_inactive else tuple(item for item in records if item.active)

    def _save(self, *, document_type: str, record_id: str, payload: dict[str, Any], actor_reference: str, action: str) -> None:
        reject_credentials(payload)
        now = datetime.now(UTC).isoformat()
        self._call(
            {
                "action": "upsert",
                "entity": "documents",
                "record": {
                    "id": record_id,
                    "document_type": document_type,
                    "title": document_type.replace("_", " ").title(),
                    "source": "commandcore-phone-system-planning",
                    "actor_reference": actor_reference,
                    "payload": payload,
                    "external_action_started": False,
                },
            }
        )
        audit_id = str(uuid4())
        self._call(
            {
                "action": "upsert",
                "entity": "documents",
                "record": {
                    "id": audit_id,
                    "document_type": PHONE_AUDIT_DOCUMENT,
                    "title": "Phone System Planning Audit Event",
                    "source": "commandcore-phone-system-planning",
                    "actor_reference": actor_reference,
                    "record_id": record_id,
                    "record_type": document_type,
                    "event_action": action,
                    "event_at": now,
                    "external_action_started": False,
                },
            }
        )

    def save_number(self, record: PhoneNumberRecord, *, action: str = "upsert") -> PhoneNumberRecord:
        saved = PhoneNumberRecord.model_validate(
            {**record.model_dump(), "updated_at": datetime.now(UTC)}
        )
        self._save(
            document_type=PHONE_INVENTORY_DOCUMENT,
            record_id=saved.record_id,
            payload=saved.model_dump(mode="json"),
            actor_reference=saved.actor_reference,
            action=action,
        )
        return saved

    def save_assignment(self, record: StaffPhoneAssignment, *, action: str = "upsert") -> StaffPhoneAssignment:
        saved = StaffPhoneAssignment.model_validate(
            {**record.model_dump(), "updated_at": datetime.now(UTC)}
        )
        self._save(
            document_type=PHONE_ASSIGNMENT_DOCUMENT,
            record_id=saved.assignment_id,
            payload=saved.model_dump(mode="json"),
            actor_reference=saved.actor_reference,
            action=action,
        )
        return saved

    def save_route(self, record: RoutingPlan, *, action: str = "upsert") -> RoutingPlan:
        saved = RoutingPlan.model_validate({**record.model_dump(), "updated_at": datetime.now(UTC)})
        self._save(
            document_type=PHONE_ROUTE_DOCUMENT,
            record_id=saved.route_id,
            payload=saved.model_dump(mode="json"),
            actor_reference=saved.actor_reference,
            action=action,
        )
        return saved

    def save_provider_pool(
        self, record: PhoneProviderPool, *, action: str = "upsert"
    ) -> PhoneProviderPool:
        saved = PhoneProviderPool.model_validate(
            {**record.model_dump(), "updated_at": datetime.now(UTC)}
        )
        self._save(
            document_type=PHONE_PROVIDER_POOL_DOCUMENT,
            record_id=saved.pool_id,
            payload=saved.model_dump(mode="json"),
            actor_reference=saved.actor_reference,
            action=action,
        )
        return saved

    def deactivate_number(self, record: PhoneNumberRecord, actor_reference: str) -> PhoneNumberRecord:
        updated = PhoneNumberRecord.model_validate(
            {
                **record.model_dump(),
                "operational_status": OperationalStatus.INACTIVE_RESERVED,
                "actor_reference": actor_reference,
            }
        )
        return self.save_number(updated, action="deactivate")

    def deactivate_provider_pool(
        self, record: PhoneProviderPool, actor_reference: str
    ) -> PhoneProviderPool:
        updated = PhoneProviderPool.model_validate(
            {
                **record.model_dump(),
                "operational_status": OperationalStatus.INACTIVE_RESERVED,
                "actor_reference": actor_reference,
            }
        )
        return self.save_provider_pool(updated, action="deactivate")

    def deactivate_assignment(self, record: StaffPhoneAssignment, actor_reference: str) -> StaffPhoneAssignment:
        updated = StaffPhoneAssignment.model_validate(
            {**record.model_dump(), "active": False, "actor_reference": actor_reference}
        )
        return self.save_assignment(updated, action="deactivate")

    def deactivate_route(self, record: RoutingPlan, actor_reference: str) -> RoutingPlan:
        updated = RoutingPlan.model_validate(
            {**record.model_dump(), "active": False, "actor_reference": actor_reference}
        )
        return self.save_route(updated, action="deactivate")
