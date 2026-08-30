from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntegrationDisposition(StrEnum):
    IMPROVE_AND_INTEGRATE = "improve_and_integrate"
    DEFERRED_REVIEW = "deferred_review"


@dataclass(frozen=True, slots=True)
class ExternalAppIntegration:
    repository: str
    source_app: str
    target_area: str
    target_workflow: str
    disposition: IntegrationDisposition
    consume_from_deal: tuple[str, ...]
    write_back_to_deal: tuple[str, ...]
    upgrade_requirements: tuple[str, ...]
    authority_boundary: str


EXTERNAL_APP_INTEGRATION: tuple[ExternalAppIntegration, ...] = (
    ExternalAppIntegration(
        repository="integrityhomes/agent-contact-finder",
        source_app="Agent Contact Finder",
        target_area="Leads & CRM",
        target_workflow="Deal contact research / listing-agent contact enrichment",
        disposition=IntegrationDisposition.IMPROVE_AND_INTEGRATE,
        consume_from_deal=(
            "property address",
            "city/state",
            "listing URL",
            "known agent name",
            "known brokerage",
        ),
        write_back_to_deal=(
            "agent phone/email",
            "brokerage phone",
            "agent website",
            "confidence/source links",
            "contact-research activity",
        ),
        upgrade_requirements=(
            "Remove duplicate manual Deal/property entry where CommandCore already knows the facts.",
            "Run lookup as a Deal capability instead of a separate daily app.",
            "Preserve source links and confidence so contact data is reviewable.",
            "Do not auto-contact an agent merely because research found contact information.",
        ),
        authority_boundary="Research/enrichment may run automatically; outbound contact remains governed by CommandCore communication/consent/routing rules.",
    ),
    ExternalAppIntegration(
        repository="integrityhomes/integrity-illinois-cfd-builder",
        source_app="Illinois CFD / Contract Builder",
        target_area="Deals",
        target_workflow="Unified Deal Record → Documents & Closing → Build Documents",
        disposition=IntegrationDisposition.IMPROVE_AND_INTEGRATE,
        consume_from_deal=(
            "seller/buyer/contact facts",
            "property facts",
            "purchase/finance terms",
            "legal/parcel information",
            "approved Deal terms",
        ),
        write_back_to_deal=(
            "generated document package",
            "document version/type",
            "generation timestamp",
            "document-prep activity",
            "review/approval status",
        ),
        upgrade_requirements=(
            "Preserve reviewed contract language and existing V14/Contract2 business logic during integration.",
            "Populate document inputs from Permanent Deal Facts instead of retyping them.",
            "Separate document preparation from signing/binding authority.",
            "Store generated documents and their provenance on the Deal.",
            "Expose only the contract/document packages appropriate to the selected Deal/state/workflow.",
        ),
        authority_boundary="CommandCore may prepare documents automatically from approved Deal facts; signing, binding agreements, legal-term changes, and final legal approval remain human-controlled.",
    ),
    ExternalAppIntegration(
        repository="integrityhomes/war-room-offer-engine",
        source_app="War Room Offer Engine",
        target_area="Deals",
        target_workflow="Unified Deal Record → Offers & Approval",
        disposition=IntegrationDisposition.IMPROVE_AND_INTEGRATE,
        consume_from_deal=(
            "property/listing facts",
            "asking/contract price",
            "rent/taxes/occupancy",
            "ARV/comps",
            "repair observations/media",
            "buyer-demand facts",
        ),
        write_back_to_deal=(
            "deal analysis",
            "ARV/comps evidence",
            "repair estimate/evidence",
            "recommended offer/exit strategy",
            "buyer-demand/dispo test findings",
            "offer-analysis activity",
        ),
        upgrade_requirements=(
            "Reuse the existing comps, repair, buyer-demand, deal-protection, and decision engines instead of recreating them.",
            "Auto-load facts already present in the Unified Deal Record.",
            "Move technical/source controls behind advanced details.",
            "Write analysis and evidence back to the same Deal rather than keeping a separate work file.",
            "Route any actual offer/send/binding action through Owner Approval where required.",
        ),
        authority_boundary="Analysis, research, repair math, comps, and offer drafting may run automatically; sending/binding offers or changing approved financial/legal terms requires the appropriate human approval.",
    ),
    ExternalAppIntegration(
        repository="integrityhomes/war-room-os",
        source_app="War Room OS",
        target_area="Deferred",
        target_workflow="Separate later audit",
        disposition=IntegrationDisposition.DEFERRED_REVIEW,
        consume_from_deal=(),
        write_back_to_deal=(),
        upgrade_requirements=(
            "Do not integrate during the current CommandCore launch-critical pass.",
            "Audit later, improve weak parts, identify duplicates, then decide what belongs in CommandCore.",
        ),
        authority_boundary="No current integration or production authority change.",
    ),
)


INTEGRATION_BY_REPOSITORY = {row.repository: row for row in EXTERNAL_APP_INTEGRATION}


def active_integrations() -> tuple[ExternalAppIntegration, ...]:
    return tuple(
        row
        for row in EXTERNAL_APP_INTEGRATION
        if row.disposition == IntegrationDisposition.IMPROVE_AND_INTEGRATE
    )


def deferred_integrations() -> tuple[ExternalAppIntegration, ...]:
    return tuple(
        row
        for row in EXTERNAL_APP_INTEGRATION
        if row.disposition == IntegrationDisposition.DEFERRED_REVIEW
    )
