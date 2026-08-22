from __future__ import annotations

from dataclasses import dataclass

from .channels import ALL_MARKETING_CHANNELS


@dataclass(frozen=True, slots=True)
class ChannelCompletion:
    key: str
    name: str
    built: bool
    tracked: bool
    ready_to_use: bool
    next_requirement: str
    operating_mode: str


_REQUIREMENTS: dict[str, tuple[bool, str, str]] = {
    "property_page": (True, "Ready now", "Automatic / owned web"),
    "blog": (True, "Approve content and connect final publishing workflow", "Approval required"),
    "market_seo": (True, "Connect final publishing workflow for live SEO pages", "Automatic / owned web"),
    "email": (True, "Connect approved email sender before live sending", "Approval required"),
    "sms": (True, "Connect approved SMS sender and enforce saved consent", "Approval required"),
    "reactivation": (True, "Connect approved outreach sender and enforce saved consent", "Approval required"),
    "marketplace": (True, "Manual final post in Facebook Marketplace", "Assisted manual post"),
    "facebook_groups": (True, "Manual final post in approved Facebook Groups", "Assisted manual post"),
    "meta_ads": (True, "Complete Meta account/campaign setup and approve spend", "Paid setup required"),
    "google_ads": (True, "Complete Google Ads account/campaign setup and approve spend", "Paid setup required"),
    "instagram": (True, "Upload/publish approved Reel or post", "Approval/manual publish"),
    "tiktok": (True, "Upload/publish approved TikTok", "Approval/manual publish"),
    "youtube": (True, "Upload/publish approved YouTube Short", "Approval/manual publish"),
    "classifieds": (True, "Manual final post to selected classified site", "Assisted manual post"),
    "nextdoor": (True, "Manual final post or paid-ad setup in Nextdoor", "Assisted / paid setup"),
    "chatgpt_ads": (
        True,
        "Set up an eligible OpenAI Ads Manager account, conversion measurement, and approved buyer-acquisition campaign before spending",
        "Paid setup required / API-ready",
    ),
}


def build_channel_completion() -> tuple[ChannelCompletion, ...]:
    """Return one honest completion row for every registered marketing channel."""
    rows: list[ChannelCompletion] = []
    for channel in ALL_MARKETING_CHANNELS:
        ready, requirement, operating_mode = _REQUIREMENTS.get(
            channel.key,
            (False, "Channel implementation still needs review", channel.mode.value),
        )
        rows.append(
            ChannelCompletion(
                key=channel.key,
                name=channel.name,
                built=channel.key in _REQUIREMENTS,
                tracked=True,
                ready_to_use=ready,
                next_requirement=requirement,
                operating_mode=operating_mode,
            )
        )
    return tuple(rows)


def completion_summary(rows: tuple[ChannelCompletion, ...]) -> dict[str, int]:
    return {
        "total": len(rows),
        "built": sum(row.built for row in rows),
        "tracked": sum(row.tracked for row in rows),
        "ready_to_use": sum(row.ready_to_use for row in rows),
        "needs_connection_or_manual_step": sum(
            row.next_requirement != "Ready now" for row in rows
        ),
    }
