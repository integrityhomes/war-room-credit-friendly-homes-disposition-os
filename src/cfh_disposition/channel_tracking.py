from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .analytics import ClickEvent
from .channels import CHANNELS, CHANNELS_BY_KEY, MarketingChannel
from .dwelyx import DEFAULT_TRACKING_APP_URL, build_dwelyx_url

# Earlier builds and manually created links used a few human-readable or generic
# medium values. Keep those clicks inside the correct 14-channel scorecard.
CHANNEL_ALIASES: dict[str, str] = {
    "available_homes_portal": "property_page",
    "featured_home_card": "property_page",
    "property_landing_page": "property_page",
    "unavailable_property_page": "property_page",
    "website": "property_page",
    "property_campaign": "property_page",
    "owner_finance_blog": "blog",
    "city_market_seo_pages": "market_seo",
    "facebook_marketplace": "marketplace",
    "facebook_group": "facebook_groups",
    "meta_housing_ads": "meta_ads",
    "google": "google_ads",
    "google_search_ads": "google_ads",
    "instagram_reels_posts": "instagram",
    "youtube_shorts": "youtube",
    "craigslist_local_classifieds": "classifieds",
    "referral_reactivation": "reactivation",
}


def normalize_channel_key(value: str) -> str:
    return value.strip().lower().replace("&", "and").replace("/", "_").replace(" ", "_")


def canonical_channel_key(value: str) -> str | None:
    normalized = normalize_channel_key(value)
    if normalized in CHANNELS_BY_KEY:
        return normalized
    return CHANNEL_ALIASES.get(normalized)


def channel_name(value: str) -> str:
    key = canonical_channel_key(value)
    if key and key in CHANNELS_BY_KEY:
        return CHANNELS_BY_KEY[key].name
    return value.replace("_", " ").title() or "Unknown"


@dataclass(frozen=True, slots=True)
class ChannelScore:
    channel: MarketingChannel
    clicks: int
    traffic_share: float
    campaigns: int
    properties: int
    last_click: datetime | None

    def as_row(self) -> dict[str, Any]:
        return {
            "Channel": self.channel.name,
            "Mode": self.channel.mode.value,
            "Clicks": self.clicks,
            "Traffic share": f"{self.traffic_share:.1f}%",
            "Campaigns": self.campaigns,
            "Properties": self.properties,
            "Last click (UTC)": self.last_click.strftime("%Y-%m-%d %H:%M") if self.last_click else "—",
            "Status": "Active" if self.clicks else "No traffic yet",
        }


def channel_scorecard(events: list[ClickEvent]) -> list[ChannelScore]:
    click_counts: Counter[str] = Counter()
    campaign_sets: dict[str, set[str]] = defaultdict(set)
    property_sets: dict[str, set[str]] = defaultdict(set)
    last_clicks: dict[str, datetime] = {}

    for event in events:
        key = canonical_channel_key(event.medium)
        if not key:
            continue
        click_counts[key] += 1
        campaign_sets[key].add(event.campaign)
        if event.property_id:
            property_sets[key].add(event.property_id)
        previous = last_clicks.get(key)
        if previous is None or event.occurred_at > previous:
            last_clicks[key] = event.occurred_at

    mapped_total = sum(click_counts.values())
    return [
        ChannelScore(
            channel=channel,
            clicks=click_counts[channel.key],
            traffic_share=(click_counts[channel.key] / mapped_total * 100) if mapped_total else 0.0,
            campaigns=len(campaign_sets[channel.key]),
            properties=len(property_sets[channel.key]),
            last_click=last_clicks.get(channel.key),
        )
        for channel in CHANNELS
    ]


def unmapped_clicks(events: list[ClickEvent]) -> list[ClickEvent]:
    return [event for event in events if canonical_channel_key(event.medium) is None]


def build_channel_links(
    dwelyx_url: str,
    *,
    campaign: str,
    property_id: UUID | str | None = None,
    tracking_base_url: str = DEFAULT_TRACKING_APP_URL,
) -> list[dict[str, str]]:
    """Create one uniquely attributed Dwelyx link for every registered channel."""
    return [
        {
            "Channel key": channel.key,
            "Channel": channel.name,
            "Mode": channel.mode.value,
            "Purpose": channel.purpose,
            "Tracked Dwelyx link": build_dwelyx_url(
                dwelyx_url,
                source="credit_friendly_homes",
                medium=channel.key,
                campaign=campaign,
                property_id=property_id,
                tracking_base_url=tracking_base_url,
            ),
        }
        for channel in CHANNELS
    ]
