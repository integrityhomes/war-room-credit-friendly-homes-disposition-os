from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .mode import HarnessMode, parse_mode

Executor = Callable[[str, dict[str, Any]], Any]
REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "account_number",
    "routing_number",
    "card_number",
    "cvv",
    "pin",
)


class ActionType(StrEnum):
    EMAIL_SEND = "email.send"
    SMS_SEND = "sms.send"
    OFFER_SEND = "offer.send"
    CONTRACT_SEND = "contract.send"
    CONTRACT_SIGN = "contract.sign"
    ADS_SPEND = "ads.spend"
    ADS_AUTHORIZED_SCRAPE = "ads.authorized_scrape"
    CRM_COMMIT = "crm.commit"
    MONEY_MOVE = "money.move"


CONSEQUENTIAL_ACTIONS = {
    ActionType.EMAIL_SEND,
    ActionType.SMS_SEND,
    ActionType.OFFER_SEND,
    ActionType.CONTRACT_SEND,
    ActionType.CONTRACT_SIGN,
    ActionType.ADS_SPEND,
    ActionType.ADS_AUTHORIZED_SCRAPE,
    ActionType.MONEY_MOVE,
}


@dataclass(frozen=True, slots=True)
class SideEffectRecord:
    action_type: str
    mode: str
    deal_id: str
    internal_only: bool
    external_action_started: bool
    approval_required: bool
    approval_present: bool
    decision: str
    reason: str
    payload_summary: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_for_report(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else _redact_for_report(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_for_report(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_for_report(item) for item in value]
    return value


def _approval_deal_id(approval: dict[str, Any]) -> str:
    links = approval.get("links")
    link_deal_id = links.get("deal_id") if isinstance(links, dict) else None
    return _text(approval.get("deal_id") or link_deal_id)


def _owner_approval_present(approval: dict[str, Any] | None, *, deal_id: str) -> bool:
    if not approval or not deal_id:
        return False
    status = _text(approval.get("status") or approval.get("approval_status")).casefold()
    approved = approval.get("approved") is True or status in {
        "approved",
        "owner_approved",
        "released",
        "approved_for_release",
    }
    return approved and _approval_deal_id(approval) == deal_id


class SideEffectBus:
    """Single fail-closed door for harness-connected consequential actions."""

    def __init__(
        self,
        mode: str | HarnessMode | None = None,
        *,
        production_executor: Executor | None = None,
        staging_executor: Executor | None = None,
    ) -> None:
        self.mode = parse_mode(mode)
        self.production_executor = production_executor
        self.staging_executor = staging_executor
        self.records: list[SideEffectRecord] = []
        self.provider_calls = 0

    def request(
        self,
        action_type: ActionType | str,
        payload: dict[str, Any],
        *,
        deal: dict[str, Any],
        owner_approval: dict[str, Any] | None = None,
    ) -> SideEffectRecord:
        action = ActionType(action_type)
        deal_id = _text(deal.get("id"))
        internal_only = deal.get("internal_only") is True
        external_started = deal.get("external_action_started") is True
        approval_required = action in CONSEQUENTIAL_ACTIONS
        approval_present = _owner_approval_present(owner_approval, deal_id=deal_id)

        decision = "blocked"
        reason = "Default deny."
        executor: Executor | None = None

        if self.mode is HarnessMode.SIMULATION:
            reason = "Simulation mode records intent only; provider calls and production CRM writes are disabled."
        elif self.mode is HarnessMode.STAGING:
            if action is ActionType.CRM_COMMIT:
                decision = "staging_only"
                reason = "Staging mode permits CRM writes only through the staging executor."
                executor = self.staging_executor
            else:
                reason = "Staging mode blocks send, sign, spend, scrape-auth, money movement, and production CRM writes."
        elif internal_only:
            reason = "The record is internal_only and cannot perform a production side effect."
        elif not external_started:
            reason = "external_action_started is not explicitly true."
        elif approval_required and not approval_present:
            reason = "A matching approved Owner Approval for this Deal is required."
        else:
            decision = "allowed"
            reason = "Explicit production safety gates passed."
            executor = self.production_executor

        record = SideEffectRecord(
            action_type=action.value,
            mode=self.mode.value,
            deal_id=deal_id,
            internal_only=internal_only,
            external_action_started=external_started,
            approval_required=approval_required,
            approval_present=approval_present,
            decision=decision,
            reason=reason,
            payload_summary=_redact_for_report(payload),
            timestamp=datetime.now(UTC).isoformat(),
        )
        self.records.append(record)

        if executor is not None and decision in {"allowed", "staging_only"}:
            executor(action.value, dict(payload))
            self.provider_calls += 1

        return record
