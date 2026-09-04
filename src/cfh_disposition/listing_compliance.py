from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .marketing_claims import risky_condition_claim_errors
from .models import OwnerFinanceProperty

SHARED_COMPLIANCE_POLICY_VERSION = "2026-09-04.1"


class ComplianceResultState(StrEnum):
    PASSED = "Passed"
    PASSED_WITH_WARNINGS = "Passed with warnings"
    BLOCKED = "Blocked"
    APPROVAL_REQUIRED = "Approval required"


class ComplianceResult(BaseModel):
    """Immutable, secret-free result that can be embedded in existing audit records."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    channel: str
    policy_version: str = SHARED_COMPLIANCE_POLICY_VERSION
    policy_checked_at: datetime
    content_hash: str
    result: ComplianceResultState
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_disclosures: tuple[str, ...] = ()
    approval_required: bool
    publication_mode: str
    rule_identifiers: tuple[str, ...] = ()
    external_action_started: bool = False


class BaselineRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier: str
    pattern: str
    message: str


BASELINE_BLOCKING_RULES: tuple[BaselineRule, ...] = (
    BaselineRule(
        identifier="fair_housing.protected_class_preference",
        pattern=r"\b(?:no|only|preferred?|preference\s+for|target)\s+(?:children|kids|families|men|women|males|females|singles|couples|christians|muslims|white|black|hispanic|immigrants|disabled|section\s*8)\b",
        message="Remove protected-class or discriminatory housing preferences.",
    ),
    BaselineRule(
        identifier="fair_housing.protected_class_targeting",
        pattern=r"\b(?:christian|muslim|white|black|hispanic|disabled|male|female|young|senior)\s+(?:buyers?|families|people|professionals?|residents?)\b",
        message="Remove targeting based on protected or sensitive personal characteristics.",
    ),
    BaselineRule(
        identifier="fair_housing.familial_status",
        pattern=r"\badults?\s+only\b|\bno\s+(?:children|kids)\b|\b(?:families|seniors)\s+only\b|\bperfect\s+for\s+(?:families|a\s+family|young\s+couples?)\b",
        message="Describe the property, not a preferred household or family type.",
    ),
    BaselineRule(
        identifier="fair_housing.neighborhood_claim",
        pattern=r"\b(?:safe|crime[-\s]?free|low[-\s]?crime|family[-\s]?friendly)\s+(?:area|neighbou?rhood|community)\b|\b(?:best|good|top[-\s]?rated)\s+schools?\b",
        message="Remove subjective safety, crime, family-status, or school-quality claims.",
    ),
    BaselineRule(
        identifier="financing.guaranteed_approval",
        pattern=r"\bguaranteed\s+(?:approval|financing|loan)\b|\b(?:everyone|anyone)\s+(?:is\s+)?approved\b|\b(?:instant|automatic|immediate)\s+approval\b|\bno\s+denials?\b",
        message="Remove guaranteed, automatic, or universal approval claims.",
    ),
    BaselineRule(
        identifier="financing.no_credit_check",
        pattern=r"\bno\s+credit\s+check\b|\bcredit\s+(?:doesn['’]?t|does\s+not)\s+matter\b|\bregardless\s+of\s+credit\b|\bbad\s+credit\s+guaranteed\b",
        message="Remove absolute credit claims and explain that approval and terms require review.",
    ),
    BaselineRule(
        identifier="privacy.sensitive_data_request",
        pattern=r"\b(?:send|share|provide|message|dm|text)\b.{0,80}\b(?:social\s+security|ssn|bank\s+account|routing\s+number|credit\s+card|debit\s+card|password|login\s+credentials?)\b",
        message="Do not request sensitive identity, financial, password, or account information in marketing copy.",
    ),
    BaselineRule(
        identifier="claims.misleading_assistance",
        pattern=r"\b(?:free\s+)?government\s+(?:grant|money|funding)\b|\bfree\s+house\b",
        message="Remove unsupported government-assistance or free-property claims.",
    ),
)


def compliance_content_hash(channel: str, content: str) -> str:
    normalized = "\n".join(line.rstrip() for line in str(content or "").strip().splitlines())
    return hashlib.sha256(f"{channel.strip().lower()}\n{normalized}".encode()).hexdigest()


def _money(value: Any) -> str:
    return "" if value is None else f"${value:,.0f}"


def _money_value(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def review_shared_compliance(
    *,
    channel: str,
    content: str,
    property_record: OwnerFinanceProperty | None = None,
    required_disclosures: tuple[str, ...] = (),
    approval_required: bool,
    publication_mode: str,
    checked_at: datetime | None = None,
) -> ComplianceResult:
    blockers: list[str] = []
    warnings: list[str] = []
    identifiers: list[str] = []
    value = str(content or "")
    lowered = value.casefold()

    for rule in BASELINE_BLOCKING_RULES:
        identifiers.append(rule.identifier)
        if re.search(rule.pattern, value, flags=re.IGNORECASE | re.DOTALL):
            blockers.append(rule.message)

    identifiers.append("claims.unsupported_condition")
    blockers.extend(risky_condition_claim_errors(value))

    for disclosure in required_disclosures:
        identifier = "disclosure." + re.sub(r"[^a-z0-9]+", "_", disclosure.casefold()).strip("_")[:60]
        identifiers.append(identifier)
        if disclosure.casefold() not in lowered:
            blockers.append(f'Required disclosure is missing: "{disclosure}"')

    if property_record is not None:
        identifiers.extend(("facts.property_address", "facts.displayed_financing_terms"))
        address = property_record.display_address
        if address and address.casefold() not in lowered:
            blockers.append("The exact property address is missing.")
        for label, amount in (
            ("down payment", property_record.down_payment),
            ("monthly payment", property_record.monthly_payment),
        ):
            if amount is None:
                blockers.append(f"The property record is missing {label}.")
            elif _money(amount) not in value:
                blockers.append(f"The exact {label} is missing.")
        identifiers.append("facts.no_invented_money")
        allowed_money = {
            Decimal(str(amount))
            for amount in (
                property_record.total_price,
                property_record.down_payment,
                property_record.monthly_payment,
            )
            if amount is not None
        }
        for token in re.findall(r"\$((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)", value):
            parsed = _money_value(token)
            if parsed is None or parsed not in allowed_money:
                blockers.append(f"An unverified dollar amount was found: ${token}.")

    identifiers.extend(("approval.channel_specific", "execution.no_automatic_action"))
    if approval_required:
        warnings.append("Human approval is required for this channel before any publication step.")
    if blockers:
        state = ComplianceResultState.BLOCKED
    elif approval_required:
        state = ComplianceResultState.APPROVAL_REQUIRED
    elif warnings:
        state = ComplianceResultState.PASSED_WITH_WARNINGS
    else:
        state = ComplianceResultState.PASSED

    return ComplianceResult(
        channel=channel,
        policy_checked_at=checked_at or datetime.now(UTC),
        content_hash=compliance_content_hash(channel, value),
        result=state,
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(set(warnings))),
        required_disclosures=required_disclosures,
        approval_required=approval_required,
        publication_mode=publication_mode,
        rule_identifiers=tuple(sorted(set(identifiers))),
        external_action_started=False,
    )
