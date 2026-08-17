from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChannelMode(StrEnum):
    AUTOMATIC = "Automatic"
    APPROVAL_REQUIRED = "Approval Required"
    ASSISTED = "Assisted Posting"


@dataclass(frozen=True, slots=True)
class MarketingChannel:
    key: str
    name: str
    mode: ChannelMode
    purpose: str


CHANNELS: tuple[MarketingChannel, ...] = (
    MarketingChannel("property_page", "Property Landing Page", ChannelMode.AUTOMATIC, "Converts traffic into inquiries, callbacks, showings, and applications."),
    MarketingChannel("blog", "Owner-Finance Blog", ChannelMode.APPROVAL_REQUIRED, "Builds organic search traffic with useful owner-finance education."),
    MarketingChannel("market_seo", "City & Market SEO Pages", ChannelMode.AUTOMATIC, "Ranks permanent local pages and updates inventory automatically."),
    MarketingChannel("email", "Matched Buyer Email", ChannelMode.APPROVAL_REQUIRED, "Sends property campaigns to buyers whose profile matches."),
    MarketingChannel("sms", "Matched Buyer SMS", ChannelMode.APPROVAL_REQUIRED, "Sends concise alerts only to properly consented buyers."),
    MarketingChannel("reactivation", "Referral & Reactivation", ChannelMode.APPROVAL_REQUIRED, "Re-engages old leads and asks for qualified referrals."),
    MarketingChannel("marketplace", "Facebook Marketplace", ChannelMode.ASSISTED, "Creates a compliant package for manual publication."),
    MarketingChannel("facebook_groups", "Facebook Groups", ChannelMode.ASSISTED, "Creates group-specific posts and tracked links."),
    MarketingChannel("meta_ads", "Meta Housing Ads", ChannelMode.APPROVAL_REQUIRED, "Runs compliant paid housing campaigns with budget approval."),
    MarketingChannel("google_ads", "Google Search Ads", ChannelMode.APPROVAL_REQUIRED, "Captures buyers actively searching for owner-finance homes."),
    MarketingChannel("instagram", "Instagram Reels & Posts", ChannelMode.APPROVAL_REQUIRED, "Publishes property and education content."),
    MarketingChannel("tiktok", "TikTok", ChannelMode.APPROVAL_REQUIRED, "Publishes or creates ready-to-post short property videos."),
    MarketingChannel("youtube", "YouTube Shorts", ChannelMode.APPROVAL_REQUIRED, "Builds searchable short-form property video inventory."),
    MarketingChannel("classifieds", "Craigslist & Local Classifieds", ChannelMode.ASSISTED, "Creates compliant classified packages and refresh reminders."),
    MarketingChannel(
        "nextdoor",
        "Nextdoor Business Posts & Housing Ads",
        ChannelMode.ASSISTED,
        "Prepares verified Business Page posts and paid housing-ad packages with a tracked Dwelyx link; final publication and ad spending remain manual and approval-controlled.",
    ),
)

CHATGPT_ADS_CHANNEL = MarketingChannel(
    "chatgpt_ads",
    "ChatGPT Ads",
    ChannelMode.APPROVAL_REQUIRED,
    "Acquires buyers by market and intent, then routes tracked traffic into the CFH/Dwelyx buyer funnel rather than advertising an individual property.",
)

BUYER_ACQUISITION_CHANNELS: tuple[MarketingChannel, ...] = (CHATGPT_ADS_CHANNEL,)
ALL_MARKETING_CHANNELS: tuple[MarketingChannel, ...] = CHANNELS + BUYER_ACQUISITION_CHANNELS
CHANNELS_BY_KEY = {channel.key: channel for channel in ALL_MARKETING_CHANNELS}
