from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SUPPORTED_MARKETS = (
    "Virginia",
    "Illinois",
    "Indiana",
    "Alabama",
    "St. Louis Metro",
    "Michigan",
    "Ohio",
)

INTENT_OPTIONS = (
    "Alternative path to homeownership",
    "Owner-financed homes",
    "Lower down-payment options",
    "Browse available homes",
)


@dataclass(frozen=True, slots=True)
class ChatGPTAdsPlan:
    market: str
    intent: str
    campaign_name: str
    context_hints: tuple[str, ...]
    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    landing_url: str
    daily_budget: Decimal
    notes: tuple[str, ...]


def build_chatgpt_ads_landing_url(base_url: str, *, market: str, intent: str, campaign: str) -> str:
    parts = urlsplit(base_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("A valid CFH/Dwelyx buyer landing page URL is required.")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "source": "credit_friendly_homes",
            "medium": "chatgpt_ads",
            "campaign": campaign,
            "market": market,
            "intent": intent,
        }
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_chatgpt_ads_plan(
    *,
    market: str,
    intent: str,
    landing_base_url: str,
    daily_budget: Decimal,
) -> ChatGPTAdsPlan:
    if market not in SUPPORTED_MARKETS:
        raise ValueError("Unsupported ChatGPT Ads market.")
    if intent not in INTENT_OPTIONS:
        raise ValueError("Unsupported ChatGPT Ads intent.")
    if daily_budget <= 0:
        raise ValueError("Daily budget must be greater than zero.")

    slug_market = market.lower().replace(" ", "_").replace(".", "")
    slug_intent = intent.lower().replace(" ", "_").replace("-", "_")
    campaign = f"chatgpt_ads_{slug_market}_{slug_intent}"
    landing_url = build_chatgpt_ads_landing_url(
        landing_base_url,
        market=market,
        intent=intent,
        campaign=campaign,
    )

    if intent == "Owner-financed homes":
        hints = (
            "people exploring owner financing as a path to homeownership",
            f"people looking for owner-finance home options in {market}",
            "people comparing alternatives to traditional mortgage financing",
        )
        headlines = (
            "Explore Another Path to Homeownership",
            f"Owner-Finance Home Options in {market}",
            "Browse Homeownership Options That May Fit",
        )
    elif intent == "Lower down-payment options":
        hints = (
            "people exploring home buying with a smaller available down payment",
            f"people comparing homeownership paths in {market}",
            "people seeking information about flexible home-buying options",
        )
        headlines = (
            "Explore Home-Buying Options",
            f"Looking for a Home in {market}?",
            "See Available Paths to Homeownership",
        )
    else:
        hints = (
            f"people exploring homeownership options in {market}",
            "people comparing alternatives to a traditional home purchase",
            "people looking for available homes and next steps",
        )
        headlines = (
            "Looking for Another Path to Homeownership?",
            f"Explore Home Options in {market}",
            "Find Your Next Homeownership Option",
        )

    descriptions = (
        "Explore current homeownership options, choose your market, and review the next steps in one place.",
        "See available options and learn how the Credit Friendly Homes and Dwelyx buyer process works.",
        "Start with your location and home-buying goals, then browse options that may fit your situation.",
    )

    notes = (
        "Buyer acquisition only by default; do not advertise a specific property from this module.",
        "Do not promise approval, guaranteed financing, or guaranteed qualification.",
        "OpenAI Ads Manager Beta is a live advertiser product; confirm current account setup, country availability, and policy requirements before launch.",
        "Treat the budget in this plan as proposed only until an owner separately approves the exact spend and campaign.",
        "Preserve ChatGPT Ads attribution through the full CFH/Dwelyx funnel.",
        "Ads Manager supports campaign creation and measurement, but do not assume external campaign-management API access unless official API documentation/access is confirmed for this account.",
    )

    return ChatGPTAdsPlan(
        market=market,
        intent=intent,
        campaign_name=campaign,
        context_hints=hints,
        headlines=headlines,
        descriptions=descriptions,
        landing_url=landing_url,
        daily_budget=daily_budget,
        notes=notes,
    )
