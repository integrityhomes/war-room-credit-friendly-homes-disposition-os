"""Plain-language lead/deal status and one next action.

Derived from the Lead → Deal → Approval → Marketing flow in
``commandcore_lead_flow``. Pure functions only — no I/O, no Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cfh_disposition.commandcore_lead_flow import (
    APPROVED_OFFER_STATUS,
    MARKETING_STAGE,
    PENDING_OFFER_STATUS,
)

CRM_PAGE = "pages/44_CommandCore_CRM.py"
DEAL_PAGE = "pages/45_CommandCore_Deal_Record.py"
APPROVALS_PAGE = "pages/48_CommandCore_Owner_Approvals.py"
MARKETING_PAGE = "pages/90_CFH_Marketing_Dispo.py"

STATUS_NEEDS_TERMS = "Needs terms"
STATUS_NEEDS_APPROVAL = "Needs approval"
STATUS_READY_TO_MARKET = "Ready to market"
STATUS_MARKETING_LIVE = "Marketing live"
STATUS_CLOSED = "Closed"
STATUS_ON_HOLD = "On hold"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_terms(deal: dict[str, Any]) -> bool:
    """True when the deal has enough verified money fields to request approval."""
    asking = _text(deal.get("asking_price"))
    offer = _text(deal.get("offer_price"))
    return bool(asking and offer)


def _offers_for_deal(deal_id: str, offers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not deal_id or not offers:
        return []
    matched: list[dict[str, Any]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        links = offer.get("links") if isinstance(offer.get("links"), dict) else {}
        if _text(links.get("deal_id")) == deal_id or _text(offer.get("deal_id")) == deal_id:
            matched.append(offer)
    return matched


def _status_of(offer: dict[str, Any]) -> str:
    return _text(offer.get("status") or offer.get("owner_approval_status")).casefold()


@dataclass(frozen=True, slots=True)
class NextAction:
    """One plain status plus the single primary next step."""

    status: str
    action_label: str
    action_page: str
    reason: str
    key: str

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "action_label": self.action_label,
            "action_page": self.action_page,
            "reason": self.reason,
            "key": self.key,
        }


def next_action(
    record: dict[str, Any],
    *,
    offers: list[dict[str, Any]] | None = None,
) -> NextAction:
    """Return plain-words status and one primary next step for a lead/deal.

    ``record`` is a CRM deal (or lead represented as a deal). Optional ``offers``
    linked to the deal refine approval / marketing readiness. Never invents
    property facts — it only reads fields already on the record.
    """
    deal = record if isinstance(record, dict) else {}
    deal_id = _text(deal.get("id"))
    stage = _text(deal.get("stage"))
    status = _text(deal.get("status")).casefold()
    marketing_status = _text(deal.get("marketing_status")).casefold()
    linked_offers = _offers_for_deal(deal_id, offers)

    if status in {"closed", "dead", "sold", "lost", "cancelled", "canceled", "archived"}:
        return NextAction(
            status=STATUS_CLOSED,
            action_label="Open deal history",
            action_page=DEAL_PAGE,
            reason="This deal is closed or not moving forward.",
            key="closed",
        )
    if status in {"on hold", "on_hold", "paused"}:
        return NextAction(
            status=STATUS_ON_HOLD,
            action_label="Review deal",
            action_page=DEAL_PAGE,
            reason="This deal is on hold until someone resumes work.",
            key="on_hold",
        )

    if (
        stage == MARKETING_STAGE
        or marketing_status in {"ready_internal", "live", "published"}
        or _text(deal.get("marketing_published_at"))
    ):
        return NextAction(
            status=STATUS_MARKETING_LIVE,
            action_label="Open marketing",
            action_page=MARKETING_PAGE,
            reason="Marketing is marked ready. Continue from Marketing Home.",
            key="marketing_live",
        )

    pending = [offer for offer in linked_offers if _status_of(offer) == PENDING_OFFER_STATUS]
    approved = [offer for offer in linked_offers if _status_of(offer) == APPROVED_OFFER_STATUS]

    if approved and not pending:
        return NextAction(
            status=STATUS_READY_TO_MARKET,
            action_label="Prepare marketing",
            action_page=MARKETING_PAGE,
            reason="Owner approval is recorded. Marketing can be prepared from verified facts only.",
            key="ready_to_market",
        )

    if pending or stage.casefold() in {"offer pending"}:
        return NextAction(
            status=STATUS_NEEDS_APPROVAL,
            action_label="Review owner approvals",
            action_page=APPROVALS_PAGE,
            reason="An offer is waiting for Shawn or Sabrina to decide.",
            key="needs_approval",
        )

    if not _has_terms(deal) or stage.casefold() in {"new lead", "contacted", "follow-up", ""}:
        return NextAction(
            status=STATUS_NEEDS_TERMS,
            action_label="Open deal and set terms",
            action_page=DEAL_PAGE,
            reason="Add verified asking price and offer terms before requesting approval.",
            key="needs_terms",
        )

    # Terms exist but no approval request yet.
    return NextAction(
        status=STATUS_NEEDS_APPROVAL,
        action_label="Request owner approval",
        action_page=DEAL_PAGE,
        reason="Terms are recorded. Request owner approval from the Deal Workspace.",
        key="needs_approval_request",
    )


def render_next_action_card(st_module: Any, action: NextAction, *, key: str) -> None:
    """Render plain status and one primary page link button (Streamlit UI helper)."""
    with st_module.container(border=True):
        st_module.markdown(f"**Status:** {action.status}")
        st_module.caption(action.reason)
        # ``key`` keeps Streamlit widget identity stable when multiple cards render.
        st_module.page_link(
            action.action_page,
            label=action.action_label,
            use_container_width=True,
        )
        _ = key
