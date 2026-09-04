"""Read-only Nevaeh inbox projection over canonical CommandCore Communications."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .commandcore_secretary_context import evaluate_commandcore_communication
from .commandcore_secretary_orchestrator import (
    SecretaryConfidence,
    SecretaryIntent,
    SecretaryUrgency,
)


class NevaehInboxCategory(StrEnum):
    NEW = "New communications"
    NEEDS_REVIEW = "Needs review"
    MATCHED_TO_DEAL = "Matched to deal"
    HIGH_PRIORITY = "High priority"
    STOP_CONSENT = "STOP / Consent"
    MONEY_LEGAL = "Money / Legal"
    UNASSIGNED = "Unassigned"


class NevaehInboxItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    communication_id: str
    person: str
    channel: str
    received_at: str
    related_property: str
    related_deal: str
    assigned_worker: str
    classification: str
    confidence: str
    approval_required: bool
    recommended_next_step: str
    categories: tuple[NevaehInboxCategory, ...]
    records_written: int = 0
    tasks_created: int = 0
    external_actions_started: int = 0


def _text(value: object) -> str:
    return str(value or "").strip()


def _message(record: Mapping[str, Any]) -> str:
    return next(
        (
            _text(record.get(field))
            for field in ("message_text", "body", "message", "content", "summary")
            if _text(record.get(field))
        ),
        "",
    )


def build_nevaeh_inbox(
    communications: Sequence[Mapping[str, Any]],
    *,
    contacts: Sequence[Mapping[str, Any]],
    properties: Sequence[Mapping[str, Any]],
    deals: Sequence[Mapping[str, Any]],
) -> tuple[NevaehInboxItem, ...]:
    """Classify existing inbound records without writing, sending, or changing consent."""
    items: list[NevaehInboxItem] = []
    for communication in communications:
        if _text(communication.get("direction")).casefold() == "outbound":
            continue
        try:
            context = evaluate_commandcore_communication(
                communication,
                contacts=contacts,
                properties=properties,
                deals=deals,
            )
        except (TypeError, ValueError):
            continue
        decision = context.decision
        categories: list[NevaehInboxCategory] = []
        if not communication.get("reviewed_at") and communication.get("reviewed") is not True:
            categories.append(NevaehInboxCategory.NEW)
        if decision.confidence is SecretaryConfidence.INSUFFICIENT or decision.escalation_required:
            categories.append(NevaehInboxCategory.NEEDS_REVIEW)
        if decision.matched_deal_id:
            categories.append(NevaehInboxCategory.MATCHED_TO_DEAL)
        if decision.urgency in {SecretaryUrgency.HIGH, SecretaryUrgency.IMMEDIATE}:
            categories.append(NevaehInboxCategory.HIGH_PRIORITY)
        explicit_stop = communication.get("consent_stop_indicated") is True or bool(
            re.search(
                r"\b(stop|unsubscribe|opt[ -]?out|do not (?:text|call|contact|message))\b",
                _message(communication),
                flags=re.IGNORECASE,
            )
        )
        if decision.intent is SecretaryIntent.CONSENT_STOP or explicit_stop:
            categories.append(NevaehInboxCategory.STOP_CONSENT)
        if decision.intent in {SecretaryIntent.PAYMENT_MONEY, SecretaryIntent.LEGAL_COMPLIANCE}:
            categories.append(NevaehInboxCategory.MONEY_LEGAL)
        if decision.suggested_owner.startswith("Unassigned"):
            categories.append(NevaehInboxCategory.UNASSIGNED)
        items.append(
            NevaehInboxItem(
                communication_id=decision.communication_event_id,
                person=context.person_label,
                channel=decision.channel.value,
                received_at=_text(
                    communication.get("received_at")
                    or communication.get("occurred_at")
                    or communication.get("created_at")
                )
                or "Time unavailable",
                related_property=context.property_label,
                related_deal=context.deal_label,
                assigned_worker=decision.suggested_owner,
                classification=decision.intent.value,
                confidence=decision.confidence.value,
                approval_required=decision.approval_required,
                recommended_next_step=decision.suggested_action,
                categories=tuple(dict.fromkeys(categories)),
            )
        )
    return tuple(sorted(items, key=lambda item: item.received_at, reverse=True))


def inbox_category_counts(items: Sequence[NevaehInboxItem]) -> dict[str, int]:
    return {
        category.value: sum(category in item.categories for item in items)
        for category in NevaehInboxCategory
    }
