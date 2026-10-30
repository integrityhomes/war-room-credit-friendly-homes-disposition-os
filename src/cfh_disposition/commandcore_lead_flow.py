"""Service-layer everyday path: Lead → Deal → Terms → Approval → Marketing.

Used by the end-to-end test and available for local demo walkthroughs.
Never invents property facts: callers must supply verified values, and
marketing publish is blocked until an owner-approved offer exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CrmCaller = Callable[[dict[str, Any]], dict[str, Any]]

PENDING_OFFER_STATUS = "draft_pending_owner_approval"
APPROVED_OFFER_STATUS = "owner_approved"
REJECTED_OFFER_STATUS = "owner_rejected"
MARKETING_STAGE = "Marketing / Dispo"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _saved(result: dict[str, Any]) -> dict[str, Any]:
    record = result.get("record")
    return record if isinstance(record, dict) else {}


@dataclass(frozen=True, slots=True)
class LeadCreateResult:
    ok: bool
    contact_id: str
    property_id: str
    deal_id: str
    message: str


@dataclass(frozen=True, slots=True)
class FlowStepResult:
    ok: bool
    record: dict[str, Any]
    message: str


@dataclass(frozen=True, slots=True)
class MarketingPublishResult:
    ok: bool
    published: bool
    blocked: bool
    message: str
    deal: dict[str, Any]
    offer: dict[str, Any] | None = None


def create_lead(
    call_crm: CrmCaller,
    *,
    seller: dict[str, Any],
    property_record: dict[str, Any],
    deal: dict[str, Any] | None = None,
) -> LeadCreateResult:
    """Create and link contact + property + deal (guided lead intake)."""
    contact_result = call_crm({"action": "upsert", "entity": "contacts", "record": seller})
    if not contact_result.get("ok"):
        return LeadCreateResult(False, "", "", "", _text(contact_result.get("error")) or "Seller could not be saved.")
    contact_id = _text(_saved(contact_result).get("id"))
    if not contact_id:
        return LeadCreateResult(False, "", "", "", "Seller saved without an id.")

    property_result = call_crm({"action": "upsert", "entity": "properties", "record": property_record})
    if not property_result.get("ok"):
        return LeadCreateResult(
            False,
            contact_id,
            "",
            "",
            _text(property_result.get("error")) or "Property could not be saved.",
        )
    property_id = _text(_saved(property_result).get("id"))
    if not property_id:
        return LeadCreateResult(False, contact_id, "", "", "Property saved without an id.")

    base = {k: v for k, v in (deal or {}).items() if k not in {"links", "id"}}
    deal_payload = {
        **base,
        "title": _text((deal or {}).get("title"))
        or _text(property_record.get("address"))
        or "New lead",
        "status": _text((deal or {}).get("status")) or "Active",
        "stage": _text((deal or {}).get("stage")) or "New Lead",
        "asking_price": _text((deal or {}).get("asking_price") or base.get("asking_price")),
        "notes": _text((deal or {}).get("notes") or base.get("notes")),
        "source": _text((deal or {}).get("source") or base.get("source")) or "commandcore",
        "demo": bool((deal or {}).get("demo") or seller.get("demo") or property_record.get("demo")),
        "links": {"contact_id": contact_id, "property_id": property_id},
    }
    deal_result = call_crm({"action": "upsert", "entity": "deals", "record": deal_payload})
    if not deal_result.get("ok"):
        return LeadCreateResult(
            False,
            contact_id,
            property_id,
            "",
            _text(deal_result.get("error")) or "Deal could not be created.",
        )
    deal_id = _text(_saved(deal_result).get("id"))
    if not deal_id:
        return LeadCreateResult(False, contact_id, property_id, "", "Deal saved without an id.")
    return LeadCreateResult(True, contact_id, property_id, deal_id, "Lead created and linked.")


def set_deal_terms(
    call_crm: CrmCaller,
    *,
    deal_id: str,
    terms: dict[str, Any],
) -> FlowStepResult:
    """Update verified deal terms on the Deal Record (no invented facts)."""
    existing = call_crm({"action": "get", "entity": "deals", "id": deal_id})
    if not existing.get("ok"):
        return FlowStepResult(False, {}, _text(existing.get("error")) or "Deal not found.")
    deal = dict(_saved(existing))
    allowed = (
        "asking_price",
        "offer_price",
        "arv",
        "estimated_repairs",
        "stage",
        "status",
        "assigned_to",
        "notes",
        "title",
    )
    for key in allowed:
        if key in terms:
            deal[key] = terms[key]
    if "stage" not in terms:
        deal["stage"] = _text(deal.get("stage")) or "Analyzing"
    result = call_crm({"action": "upsert", "entity": "deals", "record": deal})
    if not result.get("ok"):
        return FlowStepResult(False, {}, _text(result.get("error")) or "Deal terms could not be saved.")
    return FlowStepResult(True, _saved(result), "Deal terms saved.")


def request_approval(
    call_crm: CrmCaller,
    *,
    deal_id: str,
    offer: dict[str, Any] | None = None,
) -> FlowStepResult:
    """Create or update an offer waiting for owner approval."""
    existing = call_crm({"action": "get", "entity": "deals", "id": deal_id})
    if not existing.get("ok"):
        return FlowStepResult(False, {}, _text(existing.get("error")) or "Deal not found.")
    deal = _saved(existing)
    payload = {
        "source": "commandcore-lead-flow",
        "external_id": f"offer-approval-{deal_id}",
        "status": PENDING_OFFER_STATUS,
        "owner_approval_status": PENDING_OFFER_STATUS,
        "title": _text((offer or {}).get("title")) or f"Offer for {_text(deal.get('title')) or deal_id}",
        "summary": _text((offer or {}).get("summary"))
        or "Internal offer recommendation waiting for owner approval.",
        "terms": (offer or {}).get("terms") if isinstance((offer or {}).get("terms"), dict) else {},
        "links": {"deal_id": deal_id},
        "demo": bool(deal.get("demo") or (offer or {}).get("demo")),
        "external_action_started": False,
    }
    if offer:
        for key in ("id", "asking_price", "offer_price", "notes", "facts"):
            if key in offer:
                payload[key] = offer[key]
    result = call_crm({"action": "upsert", "entity": "offers", "record": payload})
    if not result.get("ok"):
        return FlowStepResult(False, {}, _text(result.get("error")) or "Approval request failed.")
    saved = _saved(result)
    call_crm(
        {
            "action": "upsert",
            "entity": "activities",
            "record": {
                "source": "commandcore-lead-flow",
                "external_id": f"approval-requested-{deal_id}-{_text(saved.get('id'))}",
                "activity_type": "owner_approval_requested",
                "title": "Owner approval requested",
                "summary": "Offer sent to the owner approval queue. Nothing was sent externally.",
                "occurred_at": _now(),
                "links": {"deal_id": deal_id, "offer_id": _text(saved.get("id"))},
                "external_action_started": False,
            },
        }
    )
    updated_deal = dict(deal)
    updated_deal["stage"] = "Offer Pending"
    call_crm({"action": "upsert", "entity": "deals", "record": updated_deal})
    return FlowStepResult(True, saved, "Offer sent to owner approval queue.")


def grant_approval(
    call_crm: CrmCaller,
    *,
    offer_id: str,
    owner_name: str = "Demo Owner",
    reason: str = "Approved for demo walkthrough",
) -> FlowStepResult:
    """Record an owner approval decision on an offer (no external send)."""
    existing = call_crm({"action": "get", "entity": "offers", "id": offer_id})
    if not existing.get("ok"):
        return FlowStepResult(False, {}, _text(existing.get("error")) or "Offer not found.")
    offer = dict(_saved(existing))
    status = _text(offer.get("status")).lower()
    if status != PENDING_OFFER_STATUS:
        return FlowStepResult(
            False,
            offer,
            f"Offer status is '{status or 'unknown'}'; expected '{PENDING_OFFER_STATUS}'.",
        )
    timestamp = _now()
    deal_id = _text((offer.get("links") or {}).get("deal_id") if isinstance(offer.get("links"), dict) else "")
    offer.update(
        {
            "status": APPROVED_OFFER_STATUS,
            "owner_approval_status": APPROVED_OFFER_STATUS,
            "owner_approval_decision": "approve",
            "owner_approved_by": owner_name,
            "owner_rejected_by": None,
            "owner_decided_at": timestamp,
            "owner_decision_reason": reason,
            "external_action_started": False,
        }
    )
    result = call_crm({"action": "upsert", "entity": "offers", "record": offer})
    if not result.get("ok"):
        return FlowStepResult(False, {}, _text(result.get("error")) or "Approval could not be saved.")
    saved = _saved(result)
    call_crm(
        {
            "action": "upsert",
            "entity": "activities",
            "record": {
                "source": "commandcore-lead-flow",
                "external_id": f"owner-decision-offers-{offer_id}",
                "activity_type": "owner_approval_decision",
                "title": "Owner approved offer",
                "summary": f"{owner_name} approved an owner-gated CommandCore item.",
                "occurred_at": timestamp,
                "details": {
                    "entity": "offers",
                    "record_id": offer_id,
                    "decision": "approve",
                    "owner_name": owner_name,
                    "reason": reason,
                    "external_action_started": False,
                },
                "links": {"deal_id": deal_id or None, "offer_id": offer_id},
            },
        }
    )
    if deal_id:
        deal_result = call_crm({"action": "get", "entity": "deals", "id": deal_id})
        if deal_result.get("ok"):
            deal = dict(_saved(deal_result))
            deal["stage"] = "Offer Made"
            call_crm({"action": "upsert", "entity": "deals", "record": deal})
    return FlowStepResult(True, saved, "Owner approval recorded.")


def _approved_offer_for_deal(call_crm: CrmCaller, deal_id: str) -> dict[str, Any] | None:
    listed = call_crm({"action": "list", "entity": "offers", "limit": 500})
    records = listed.get("records") if isinstance(listed.get("records"), list) else []
    for record in records:
        if not isinstance(record, dict):
            continue
        links = record.get("links") if isinstance(record.get("links"), dict) else {}
        if _text(links.get("deal_id")) != deal_id:
            continue
        if _text(record.get("status")).lower() == APPROVED_OFFER_STATUS:
            return record
    return None


def publish_marketing(
    call_crm: CrmCaller,
    *,
    deal_id: str,
) -> MarketingPublishResult:
    """Mark a deal ready for marketing only after owner approval.

    This records an internal marketing-ready state. It does not invent listing
    facts or launch external campaigns.
    """
    existing = call_crm({"action": "get", "entity": "deals", "id": deal_id})
    if not existing.get("ok"):
        return MarketingPublishResult(
            ok=False,
            published=False,
            blocked=True,
            message=_text(existing.get("error")) or "Deal not found.",
            deal={},
        )
    deal = dict(_saved(existing))
    approved = _approved_offer_for_deal(call_crm, deal_id)
    if approved is None:
        return MarketingPublishResult(
            ok=False,
            published=False,
            blocked=True,
            message="Marketing is blocked until an offer has owner approval.",
            deal=deal,
            offer=None,
        )

    deal["stage"] = MARKETING_STAGE
    deal["marketing_status"] = "ready_internal"
    deal["marketing_published_at"] = _now()
    deal["marketing_external_action_started"] = False
    result = call_crm({"action": "upsert", "entity": "deals", "record": deal})
    if not result.get("ok"):
        return MarketingPublishResult(
            ok=False,
            published=False,
            blocked=False,
            message=_text(result.get("error")) or "Marketing status could not be saved.",
            deal=deal,
            offer=approved,
        )
    saved = _saved(result)
    call_crm(
        {
            "action": "upsert",
            "entity": "activities",
            "record": {
                "source": "commandcore-lead-flow",
                "external_id": f"marketing-ready-{deal_id}",
                "activity_type": "marketing_ready",
                "title": "Marketing marked ready (internal)",
                "summary": (
                    "Deal marked ready for marketing after owner approval. "
                    "No external campaign was launched and no property facts were invented."
                ),
                "occurred_at": _now(),
                "links": {"deal_id": deal_id, "offer_id": _text(approved.get("id"))},
                "external_action_started": False,
            },
        }
    )
    return MarketingPublishResult(
        ok=True,
        published=True,
        blocked=False,
        message="Marketing marked ready after owner approval.",
        deal=saved,
        offer=approved,
    )
