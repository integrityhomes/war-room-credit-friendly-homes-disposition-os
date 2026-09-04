from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_DOWN
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analytics import ClickEvent
from .dwelyx import build_dwelyx_url
from .listing_compliance import ComplianceResultState, review_shared_compliance
from .models import OwnerFinanceProperty
from .storage import SupabaseSettings

BUYER_ACQUISITION_BUCKET = "cfh-buyer-acquisition"
BUYER_ACQUISITION_PATH = "buyer-acquisition/ledger.json"
BUYER_ACQUISITION_MAX_BYTES = 3 * 1024 * 1024

SUPPORTED_ACQUISITION_SOURCES: dict[str, str] = {
    "meta_ads": "Meta Housing Ads",
    "google_ads": "Google Search Ads",
    "facebook_groups": "Facebook Groups",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube Shorts",
    "market_seo": "City & Market SEO",
    "referrals": "Buyer Referral Campaign",
    "classifieds": "Craigslist & Local Classifieds",
}

MANUAL_PUBLICATION_SOURCES = {"facebook_groups", "classifieds"}
PAID_SOURCES = {"meta_ads", "google_ads"}

class BuyerAcquisitionError(RuntimeError):
    """Raised when a buyer-acquisition campaign cannot be created or updated."""


class AcquisitionCampaignStatus(StrEnum):
    DRAFT = "Draft"
    APPROVED = "Approved"
    LIVE = "Live"
    PAUSED = "Paused"
    COMPLETED = "Completed"


class AcquisitionRecommendation(StrEnum):
    SCALE = "Scale"
    KEEP = "Keep Running"
    REPAIR = "Repair Funnel"
    PAUSE = "Pause Spend"
    TEST = "Launch Test"
    COLLECT = "Collect More Data"


class AcquisitionCampaign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    campaign_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=3, max_length=180)
    source_key: str
    source_name: str
    market_city: str = Field(min_length=1, max_length=100)
    market_state: str = Field(min_length=2, max_length=2)
    property_id: str = ""
    property_address: str = ""
    weekly_budget: Decimal = Field(default=Decimal("0"), ge=0)
    target_cost_per_registration: Decimal = Field(default=Decimal("20"), gt=0)
    weekly_registration_goal: int = Field(default=10, ge=1, le=100000)
    audience_notes: str = Field(default="Adults seeking owner-finance home information in the selected market.", max_length=1000)
    campaign_code: str = Field(min_length=3, max_length=180)
    tracked_link: str
    headline: str = Field(min_length=3, max_length=180)
    primary_copy: str = Field(min_length=20, max_length=4000)
    short_video_hook: str = Field(min_length=10, max_length=500)
    call_to_action: str = Field(min_length=10, max_length=700)
    publication_instructions: str = Field(min_length=10, max_length=1200)
    status: AcquisitionCampaignStatus = AcquisitionCampaignStatus.DRAFT
    approved_by: str = ""
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_campaign(self) -> AcquisitionCampaign:
        if self.source_key not in SUPPORTED_ACQUISITION_SOURCES:
            raise ValueError("Unsupported buyer-acquisition source")
        if self.source_name != SUPPORTED_ACQUISITION_SOURCES[self.source_key]:
            raise ValueError("Acquisition source name does not match source key")
        if self.market_state != self.market_state.upper():
            raise ValueError("Market state must be uppercase")
        validate_audience_notes(self.audience_notes)
        return self


class AcquisitionOutcome(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    campaign_id: str
    period_start: date
    period_end: date
    impressions: int = Field(default=0, ge=0)
    reported_clicks: int = Field(default=0, ge=0)
    registrations: int = Field(default=0, ge=0)
    qualified_buyers: int = Field(default=0, ge=0)
    applications: int = Field(default=0, ge=0)
    contracts: int = Field(default=0, ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str = Field(default="", max_length=1500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_period(self) -> AcquisitionOutcome:
        if self.period_end < self.period_start:
            raise ValueError("Period end must be on or after period start")
        if self.qualified_buyers > self.registrations:
            raise ValueError("Qualified buyers cannot exceed registrations")
        if self.applications > self.registrations:
            raise ValueError("Applications cannot exceed registrations")
        if self.contracts > self.applications:
            raise ValueError("Contracts cannot exceed applications")
        return self


class BuyerAcquisitionLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    campaigns: list[AcquisitionCampaign] = Field(default_factory=list)
    outcomes: list[AcquisitionOutcome] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AcquisitionPerformance:
    campaign_id: str
    campaign_name: str
    source_key: str
    source_name: str
    market: str
    property_address: str
    impressions: int
    reported_clicks: int
    tracked_clicks: int
    usable_clicks: int
    registrations: int
    qualified_buyers: int
    applications: int
    contracts: int
    spend: Decimal
    click_through_rate: float | None
    click_to_registration_rate: float | None
    qualified_registration_rate: float | None
    registration_to_application_rate: float | None
    cost_per_registration: Decimal | None
    cost_per_qualified_buyer: Decimal | None
    recommendation: AcquisitionRecommendation
    reason: str
    confidence: str
    projected_weekly_registrations: int


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    campaign_id: str
    campaign_name: str
    recommendation: AcquisitionRecommendation
    current_weekly_budget: Decimal
    recommended_weekly_budget: Decimal
    projected_registrations: int


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def _slug(value: str) -> str:
    return "_".join(part for part in "".join(character.lower() if character.isalnum() else " " for character in value).split() if part)


def validate_audience_notes(notes: str) -> None:
    result = review_shared_compliance(
        channel="housing_audience",
        content=notes,
        approval_required=False,
        publication_mode="Internal Review",
    )
    if result.result == ComplianceResultState.BLOCKED:
        raise BuyerAcquisitionError(
            "Prohibited housing audience language detected: " + "; ".join(result.blockers)
        )


def validate_campaign_copy(campaign: AcquisitionCampaign, property_record: OwnerFinanceProperty | None = None) -> list[str]:
    errors: list[str] = []
    combined = "\n".join(
        [
            campaign.headline,
            campaign.primary_copy,
            campaign.short_video_hook,
            campaign.call_to_action,
            campaign.publication_instructions,
        ]
    )
    lowered = combined.casefold()
    baseline = review_shared_compliance(
        channel=campaign.source_key,
        content=combined,
        approval_required=campaign.source_key in PAID_SOURCES,
        publication_mode=(
            "Assisted Posting" if campaign.source_key in MANUAL_PUBLICATION_SOURCES else "Approval Required"
        ),
    )
    errors.extend(baseline.blockers)
    if combined.count(campaign.tracked_link) != 3:
        errors.append("The tracked Dwelyx link must appear once in the main copy, video hook, and call to action.")
    if "equal housing opportunity" not in lowered:
        errors.append("Equal Housing Opportunity language is missing.")
    if "subject to review and verification" not in lowered:
        errors.append("Approval and availability review language is missing.")
    if property_record is not None:
        if property_record.display_address.casefold() not in lowered:
            errors.append("The exact property address is missing.")
        for label, value in (
            ("down payment", property_record.down_payment),
            ("monthly payment", property_record.monthly_payment),
        ):
            if value is None:
                errors.append(f"The property record is missing {label}.")
            elif _money(value) not in combined:
                errors.append(f"The exact {label} is missing.")
        if property_record.total_price is not None and _money(property_record.total_price) in combined:
            errors.append("The total purchase price must not appear in acquisition campaign copy.")
    return sorted(set(errors))


def build_acquisition_campaign(
    *,
    source_key: str,
    market_city: str,
    market_state: str,
    dwelyx_url: str,
    weekly_budget: Decimal | str | int = Decimal("0"),
    target_cost_per_registration: Decimal | str | int = Decimal("20"),
    weekly_registration_goal: int = 10,
    audience_notes: str = "Adults seeking owner-finance home information in the selected market.",
    property_record: OwnerFinanceProperty | None = None,
    name: str = "",
    now: datetime | None = None,
) -> AcquisitionCampaign:
    if source_key not in SUPPORTED_ACQUISITION_SOURCES:
        raise BuyerAcquisitionError("Choose a supported buyer-acquisition source.")
    city = market_city.strip()
    state = market_state.strip().upper()
    if not city or len(state) != 2:
        raise BuyerAcquisitionError("A market city and two-letter state are required.")
    validate_audience_notes(audience_notes)
    source_name = SUPPORTED_ACQUISITION_SOURCES[source_key]
    scope = property_record.display_address if property_record else f"{city}, {state}"
    campaign_code = f"buyer_growth_{_slug(city)}_{state.lower()}_{source_key}"
    if property_record:
        campaign_code += f"_{str(property_record.property_id)[:8]}"
    tracked_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium=source_key,
        campaign=campaign_code,
        property_id=property_record.property_id if property_record else None,
    )
    approval = "Approval, terms, property condition, and availability are subject to review and verification."
    housing = "Equal Housing Opportunity."
    if property_record:
        address = property_record.display_address
        down = _money(property_record.down_payment)
        monthly = _money(property_record.monthly_payment)
        condition = property_record.condition_summary or "Property condition information is available for buyer review."
        repairs = property_record.repairs_needed or "Buyers should independently inspect and verify any work needed."
        headline = f"Owner-finance home information: {address}"
        primary_copy = (
            f"Review an owner-finance home at {address}. Current terms shown are {down} down and "
            f"{monthly} per month. The monthly payment is not rent. Condition: {condition} "
            f"Known work or repairs: {repairs} {approval} {housing}\n\n"
            f"Create or log in to a Dwelyx buyer account to review current details and availability: {tracked_link}"
        )
        short_video_hook = (
            f"Looking for owner-finance options near {city}, {state}? Review {address}, currently shown at "
            f"{down} down and {monthly} per month. Details and availability: {tracked_link}"
        )
    else:
        headline = f"Owner-finance home alerts for {city}, {state}"
        primary_copy = (
            f"Create a Dwelyx buyer account to review owner-finance homes as they become available in and around "
            f"{city}, {state}. Inventory and terms change, and no approval is promised. {approval} {housing}\n\n"
            f"Join the buyer list and keep your preferences current: {tracked_link}"
        )
        short_video_hook = (
            f"Searching for owner-finance homes around {city}, {state}? Create a Dwelyx buyer account to review "
            f"available options and update your buying preferences: {tracked_link}"
        )
    call_to_action = (
        f"Create or log in to your Dwelyx buyer account to review current owner-finance availability: {tracked_link}"
    )
    if source_key == "facebook_groups":
        instructions = (
            "Manual publication only. Review the selected Facebook Group rules before posting. Do not use browser bots, "
            "automated member-group posting, or misleading engagement tactics."
        )
    elif source_key == "classifieds":
        instructions = (
            "Manual or platform-approved publication only. Follow each classified site's housing rules, duplicate limits, "
            "and refresh schedule."
        )
    elif source_key == "meta_ads":
        instructions = (
            "Manager approval required. Build this as a housing ad using Meta's applicable housing-ad settings. Do not target "
            "protected classes or use inferred sensitive traits."
        )
    elif source_key == "google_ads":
        instructions = (
            "Manager approval required. Use factual housing-search keywords and negative keywords. Send traffic only to the "
            "tracked Dwelyx buyer-registration destination."
        )
    else:
        instructions = (
            "Manager approval required before publication. Use only the prepared factual package and the tracked Dwelyx link."
        )
    current = now or datetime.now(UTC)
    campaign = AcquisitionCampaign(
        name=name.strip() or f"{source_name} — {scope}",
        source_key=source_key,
        source_name=source_name,
        market_city=city,
        market_state=state,
        property_id=str(property_record.property_id) if property_record else "",
        property_address=property_record.display_address if property_record else "",
        weekly_budget=Decimal(str(weekly_budget)),
        target_cost_per_registration=Decimal(str(target_cost_per_registration)),
        weekly_registration_goal=weekly_registration_goal,
        audience_notes=audience_notes,
        campaign_code=campaign_code,
        tracked_link=tracked_link,
        headline=headline,
        primary_copy=primary_copy,
        short_video_hook=short_video_hook,
        call_to_action=call_to_action,
        publication_instructions=instructions,
        created_at=current,
        updated_at=current,
    )
    errors = validate_campaign_copy(campaign, property_record)
    if errors:
        raise BuyerAcquisitionError("Campaign fact guard blocked the package: " + "; ".join(errors))
    return campaign


def create_campaign(ledger: BuyerAcquisitionLedger, campaign: AcquisitionCampaign) -> BuyerAcquisitionLedger:
    duplicate = next(
        (
            row
            for row in ledger.campaigns
            if row.source_key == campaign.source_key
            and row.market_city.casefold() == campaign.market_city.casefold()
            and row.market_state == campaign.market_state
            and row.property_id == campaign.property_id
            and row.status
            in {
                AcquisitionCampaignStatus.DRAFT,
                AcquisitionCampaignStatus.APPROVED,
                AcquisitionCampaignStatus.LIVE,
                AcquisitionCampaignStatus.PAUSED,
            }
        ),
        None,
    )
    if duplicate:
        raise BuyerAcquisitionError("An active buyer-acquisition campaign already exists for this source and scope.")
    return ledger.model_copy(
        update={
            "campaigns": [*ledger.campaigns, campaign],
            "updated_at": datetime.now(UTC),
        }
    )


def find_campaign(ledger: BuyerAcquisitionLedger, campaign_id: str) -> AcquisitionCampaign:
    campaign = next((row for row in ledger.campaigns if row.campaign_id == campaign_id), None)
    if campaign is None:
        raise BuyerAcquisitionError("Buyer-acquisition campaign could not be found.")
    return campaign


def update_campaign_status(
    ledger: BuyerAcquisitionLedger,
    *,
    campaign_id: str,
    status: AcquisitionCampaignStatus,
    actor: str = "",
    now: datetime | None = None,
) -> BuyerAcquisitionLedger:
    current = now or datetime.now(UTC)
    campaign = find_campaign(ledger, campaign_id)
    if status in {AcquisitionCampaignStatus.APPROVED, AcquisitionCampaignStatus.LIVE} and not actor.strip():
        raise BuyerAcquisitionError("Manager name is required before approving or launching a campaign.")
    if status == AcquisitionCampaignStatus.LIVE and campaign.status not in {
        AcquisitionCampaignStatus.APPROVED,
        AcquisitionCampaignStatus.PAUSED,
        AcquisitionCampaignStatus.LIVE,
    }:
        raise BuyerAcquisitionError("Approve the campaign before marking it Live.")
    updated_campaigns: list[AcquisitionCampaign] = []
    for row in ledger.campaigns:
        if row.campaign_id != campaign_id:
            updated_campaigns.append(row)
            continue
        changes: dict[str, Any] = {"status": status, "updated_at": current}
        if status == AcquisitionCampaignStatus.APPROVED:
            changes.update({"approved_by": actor.strip(), "approved_at": current})
        updated_campaigns.append(row.model_copy(update=changes))
    return ledger.model_copy(update={"campaigns": updated_campaigns, "updated_at": current})


def upsert_outcome(
    ledger: BuyerAcquisitionLedger,
    *,
    campaign_id: str,
    period_start: date,
    period_end: date,
    impressions: int = 0,
    reported_clicks: int = 0,
    registrations: int = 0,
    qualified_buyers: int = 0,
    applications: int = 0,
    contracts: int = 0,
    spend: Decimal | str | int = Decimal("0"),
    notes: str = "",
    now: datetime | None = None,
) -> BuyerAcquisitionLedger:
    find_campaign(ledger, campaign_id)
    current = now or datetime.now(UTC)
    existing = next(
        (
            row
            for row in ledger.outcomes
            if row.campaign_id == campaign_id
            and row.period_start == period_start
            and row.period_end == period_end
        ),
        None,
    )
    outcome = AcquisitionOutcome(
        outcome_id=existing.outcome_id if existing else str(uuid4()),
        campaign_id=campaign_id,
        period_start=period_start,
        period_end=period_end,
        impressions=impressions,
        reported_clicks=reported_clicks,
        registrations=registrations,
        qualified_buyers=qualified_buyers,
        applications=applications,
        contracts=contracts,
        spend=Decimal(str(spend)),
        notes=notes,
        created_at=existing.created_at if existing else current,
        updated_at=current,
    )
    outcomes = [
        row
        for row in ledger.outcomes
        if not (
            row.campaign_id == campaign_id
            and row.period_start == period_start
            and row.period_end == period_end
        )
    ]
    outcomes.append(outcome)
    return ledger.model_copy(update={"outcomes": outcomes, "updated_at": current})


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _cost(spend: Decimal, count: int) -> Decimal | None:
    return (spend / Decimal(count)).quantize(Decimal("0.01")) if count else None


def _campaign_clicks(campaign: AcquisitionCampaign, click_events: Sequence[ClickEvent]) -> int:
    return sum(
        1
        for event in click_events
        if event.campaign == campaign.campaign_code
        and (not campaign.property_id or event.property_id == campaign.property_id)
    )


def recommendation_for_acquisition(
    *,
    usable_clicks: int,
    registrations: int,
    qualified_buyers: int,
    applications: int,
    contracts: int,
    spend: Decimal,
    target_cost_per_registration: Decimal,
) -> tuple[AcquisitionRecommendation, str, str]:
    if contracts > 0:
        return AcquisitionRecommendation.SCALE, "The campaign produced a filled home or contract.", "High"
    cost_per_registration = _cost(spend, registrations)
    if registrations >= 5 and qualified_buyers >= 3 and cost_per_registration is not None:
        if cost_per_registration <= target_cost_per_registration:
            return AcquisitionRecommendation.SCALE, "Registration cost is on target and the campaign is producing qualified buyers.", "High"
        if cost_per_registration <= target_cost_per_registration * Decimal("1.35"):
            return AcquisitionRecommendation.KEEP, "The campaign is producing qualified buyers near the target acquisition cost.", "Medium"
    if usable_clicks >= 20 and registrations == 0:
        if spend >= target_cost_per_registration * Decimal("2"):
            return AcquisitionRecommendation.PAUSE, "Spend and clicks are accumulating without new Dwelyx registrations.", "High"
        return AcquisitionRecommendation.REPAIR, "Traffic is reaching the funnel but is not becoming Dwelyx registrations.", "Medium"
    if registrations >= 3 and qualified_buyers == 0:
        return AcquisitionRecommendation.REPAIR, "Registrations are coming in, but buyer quality or onboarding needs repair.", "Medium"
    if applications > 0 or qualified_buyers > 0:
        return AcquisitionRecommendation.KEEP, "The campaign has produced meaningful buyer progress but needs more volume.", "Medium"
    if usable_clicks < 10 and spend <= target_cost_per_registration:
        return AcquisitionRecommendation.COLLECT, "The campaign does not yet have enough traffic for a reliable decision.", "Low"
    if spend == 0 and usable_clicks == 0:
        return AcquisitionRecommendation.TEST, "Launch a measured test and collect the first buyer-acquisition data.", "Low"
    return AcquisitionRecommendation.COLLECT, "Continue collecting registrations and qualified-buyer outcomes before changing the campaign.", "Low"


def projected_registrations(weekly_budget: Decimal, target_cost_per_registration: Decimal) -> int:
    if weekly_budget <= 0 or target_cost_per_registration <= 0:
        return 0
    return int((weekly_budget / target_cost_per_registration).to_integral_value(rounding=ROUND_DOWN))


def build_acquisition_performance(
    ledger: BuyerAcquisitionLedger,
    click_events: Sequence[ClickEvent] = (),
) -> list[AcquisitionPerformance]:
    outcomes_by_campaign: dict[str, list[AcquisitionOutcome]] = defaultdict(list)
    for outcome in ledger.outcomes:
        outcomes_by_campaign[outcome.campaign_id].append(outcome)
    rows: list[AcquisitionPerformance] = []
    for campaign in ledger.campaigns:
        outcomes = outcomes_by_campaign[campaign.campaign_id]
        impressions = sum(row.impressions for row in outcomes)
        reported_clicks = sum(row.reported_clicks for row in outcomes)
        tracked_clicks = _campaign_clicks(campaign, click_events)
        usable_clicks = max(reported_clicks, tracked_clicks)
        registrations = sum(row.registrations for row in outcomes)
        qualified_buyers = sum(row.qualified_buyers for row in outcomes)
        applications = sum(row.applications for row in outcomes)
        contracts = sum(row.contracts for row in outcomes)
        spend = sum((row.spend for row in outcomes), Decimal("0"))
        recommendation, reason, confidence = recommendation_for_acquisition(
            usable_clicks=usable_clicks,
            registrations=registrations,
            qualified_buyers=qualified_buyers,
            applications=applications,
            contracts=contracts,
            spend=spend,
            target_cost_per_registration=campaign.target_cost_per_registration,
        )
        rows.append(
            AcquisitionPerformance(
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.name,
                source_key=campaign.source_key,
                source_name=campaign.source_name,
                market=f"{campaign.market_city}, {campaign.market_state}",
                property_address=campaign.property_address,
                impressions=impressions,
                reported_clicks=reported_clicks,
                tracked_clicks=tracked_clicks,
                usable_clicks=usable_clicks,
                registrations=registrations,
                qualified_buyers=qualified_buyers,
                applications=applications,
                contracts=contracts,
                spend=spend,
                click_through_rate=_rate(usable_clicks, impressions),
                click_to_registration_rate=_rate(registrations, usable_clicks),
                qualified_registration_rate=_rate(qualified_buyers, registrations),
                registration_to_application_rate=_rate(applications, registrations),
                cost_per_registration=_cost(spend, registrations),
                cost_per_qualified_buyer=_cost(spend, qualified_buyers),
                recommendation=recommendation,
                reason=reason,
                confidence=confidence,
                projected_weekly_registrations=projected_registrations(
                    campaign.weekly_budget,
                    campaign.target_cost_per_registration,
                ),
            )
        )
    priority = {
        AcquisitionRecommendation.SCALE: 0,
        AcquisitionRecommendation.KEEP: 1,
        AcquisitionRecommendation.REPAIR: 2,
        AcquisitionRecommendation.TEST: 3,
        AcquisitionRecommendation.COLLECT: 4,
        AcquisitionRecommendation.PAUSE: 5,
    }
    return sorted(rows, key=lambda row: (priority[row.recommendation], -row.registrations, row.campaign_name.casefold()))


def recommend_budget_allocation(
    campaigns: Sequence[AcquisitionCampaign],
    performance: Sequence[AcquisitionPerformance],
    total_weekly_budget: Decimal | str | int,
) -> list[BudgetAllocation]:
    total = Decimal(str(total_weekly_budget))
    if total < 0:
        raise BuyerAcquisitionError("Total weekly budget cannot be negative.")
    performance_by_id = {row.campaign_id: row for row in performance}
    weights = {
        AcquisitionRecommendation.SCALE: Decimal("5"),
        AcquisitionRecommendation.KEEP: Decimal("3"),
        AcquisitionRecommendation.REPAIR: Decimal("1"),
        AcquisitionRecommendation.TEST: Decimal("2"),
        AcquisitionRecommendation.COLLECT: Decimal("1"),
        AcquisitionRecommendation.PAUSE: Decimal("0"),
    }
    eligible = [
        campaign
        for campaign in campaigns
        if campaign.status in {
            AcquisitionCampaignStatus.APPROVED,
            AcquisitionCampaignStatus.LIVE,
            AcquisitionCampaignStatus.PAUSED,
        }
        and campaign.campaign_id in performance_by_id
    ]
    weight_total = sum((weights[performance_by_id[row.campaign_id].recommendation] for row in eligible), Decimal("0"))
    allocations: list[BudgetAllocation] = []
    allocated = Decimal("0")
    for index, campaign in enumerate(eligible):
        performance_row = performance_by_id[campaign.campaign_id]
        weight = weights[performance_row.recommendation]
        if total == 0 or weight_total == 0 or weight == 0:
            recommended = Decimal("0")
        elif index == len(eligible) - 1:
            recommended = (total - allocated).quantize(Decimal("0.01"))
        else:
            recommended = (total * weight / weight_total).quantize(Decimal("0.01"))
            allocated += recommended
        allocations.append(
            BudgetAllocation(
                campaign_id=campaign.campaign_id,
                campaign_name=campaign.name,
                recommendation=performance_row.recommendation,
                current_weekly_budget=campaign.weekly_budget,
                recommended_weekly_budget=recommended,
                projected_registrations=projected_registrations(
                    recommended,
                    campaign.target_cost_per_registration,
                ),
            )
        )
    return allocations


def performance_rows(performance: Sequence[AcquisitionPerformance]) -> list[dict[str, str | int | float]]:
    def percent(value: float | None) -> str:
        return "—" if value is None else f"{value * 100:.1f}%"

    def money(value: Decimal | None) -> str:
        return "—" if value is None else f"${value:,.2f}"

    return [
        {
            "Recommendation": row.recommendation.value,
            "Campaign": row.campaign_name,
            "Source": row.source_name,
            "Market": row.market,
            "Clicks": row.usable_clicks,
            "Registrations": row.registrations,
            "Qualified Buyers": row.qualified_buyers,
            "Applications": row.applications,
            "Filled / Contracts": row.contracts,
            "Spend": money(row.spend),
            "Cost / Registration": money(row.cost_per_registration),
            "Click → Registration": percent(row.click_to_registration_rate),
            "Qualified Rate": percent(row.qualified_registration_rate),
            "Projected Weekly Registrations": row.projected_weekly_registrations,
            "Why": row.reason,
        }
        for row in performance
    ]


def allocation_rows(allocations: Sequence[BudgetAllocation]) -> list[dict[str, str | int]]:
    return [
        {
            "Campaign": row.campaign_name,
            "Recommendation": row.recommendation.value,
            "Current Weekly Budget": f"${row.current_weekly_budget:,.2f}",
            "Recommended Weekly Budget": f"${row.recommended_weekly_budget:,.2f}",
            "Projected Registrations": row.projected_registrations,
        }
        for row in allocations
    ]


class BuyerAcquisitionStore:
    """Private Supabase Storage ledger for acquisition campaigns and outcomes."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise BuyerAcquisitionError("Supabase is not configured for buyer-acquisition records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise BuyerAcquisitionError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(BUYER_ACQUISITION_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    BUYER_ACQUISITION_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": BUYER_ACQUISITION_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise BuyerAcquisitionError("Could not create the private buyer-acquisition bucket.") from exc
        self._bucket_ready = True

    def load(self) -> BuyerAcquisitionLedger:
        self._ensure_bucket()
        bucket = self._client.storage.from_(BUYER_ACQUISITION_BUCKET)
        try:
            payload = bucket.download(BUYER_ACQUISITION_PATH)
        except Exception:
            return BuyerAcquisitionLedger()
        try:
            return BuyerAcquisitionLedger.model_validate_json(payload.decode("utf-8"))
        except Exception as exc:
            raise BuyerAcquisitionError("Saved buyer-acquisition records are unreadable.") from exc

    def save(self, ledger: BuyerAcquisitionLedger) -> None:
        self._ensure_bucket()
        data = ledger.model_dump_json().encode("utf-8")
        if len(data) > BUYER_ACQUISITION_MAX_BYTES:
            raise BuyerAcquisitionError("Buyer-acquisition records exceed the private storage limit.")
        bucket = self._client.storage.from_(BUYER_ACQUISITION_BUCKET)
        options = {"content-type": "application/json", "cache-control": "0", "upsert": "true"}
        try:
            bucket.upload(BUYER_ACQUISITION_PATH, data, options)
        except Exception:
            try:
                bucket.update(BUYER_ACQUISITION_PATH, data, options)
            except Exception as exc:
                raise BuyerAcquisitionError("Could not save buyer-acquisition records.") from exc
