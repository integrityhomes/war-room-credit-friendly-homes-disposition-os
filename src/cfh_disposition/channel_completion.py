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
    completion_state: str
    next_requirement: str
    operating_mode: str
    connection_required: bool
    manual_final_step_required: bool


# This registry describes the current operating truth, not merely whether code exists.
# A channel is only `ready_to_use` when CommandCore/CFH can operate it now in its
# intended mode without pretending an unconnected external adapter is live.
_REQUIREMENTS: dict[str, tuple[bool, str, str, str, bool, bool]] = {
    "property_page": (
        True,
        "Ready now",
        "Ready now",
        "Automatic / owned web",
        False,
        False,
    ),
    "blog": (
        True,
        "Approval-gated owned-web workflow complete",
        "Approve the saved campaign before the public article becomes available",
        "Approval required / owned web",
        False,
        False,
    ),
    "market_seo": (
        True,
        "Owned-web market pages complete",
        "Ready now from public CFH inventory",
        "Automatic / owned web",
        False,
        False,
    ),
    "email": (
        False,
        "Software complete — sender connection required",
        "Connect approved email sender before live sending",
        "Approval required",
        True,
        False,
    ),
    "sms": (
        False,
        "Software complete — sender connection required",
        "Verify the approved SMS / Profit Dial sender connection before live sending",
        "Approval required",
        True,
        False,
    ),
    "reactivation": (
        False,
        "Software complete — outreach connection required",
        "Connect approved outreach sender and enforce saved consent",
        "Approval required",
        True,
        False,
    ),
    "marketplace": (
        True,
        "Assisted workflow complete",
        "Manual final post in Facebook Marketplace",
        "Assisted manual post",
        False,
        True,
    ),
    "facebook_groups": (
        True,
        "Assisted workflow complete",
        "Manual final post in approved Facebook Groups",
        "Assisted manual post",
        False,
        True,
    ),
    "meta_ads": (
        False,
        "Software complete — paid platform connection required",
        "Complete Meta account/campaign setup and approve spend",
        "Paid setup required",
        True,
        False,
    ),
    "google_ads": (
        False,
        "Software complete — paid platform connection required",
        "Complete Google Ads account/campaign setup and approve spend",
        "Paid setup required",
        True,
        False,
    ),
    "instagram": (
        False,
        "Software complete — publication step not connected",
        "Connect an approved publication path or complete the final upload manually",
        "Approval/manual publish",
        True,
        True,
    ),
    "tiktok": (
        False,
        "Software complete — publication step not connected",
        "Connect an approved publication path or complete the final TikTok upload manually",
        "Approval/manual publish",
        True,
        True,
    ),
    "youtube": (
        False,
        "Software complete — publication step not connected",
        "Connect an approved publication path or complete the final YouTube upload manually",
        "Approval/manual publish",
        True,
        True,
    ),
    "classifieds": (
        True,
        "Assisted workflow complete",
        "Manual final post to selected classified site",
        "Assisted manual post",
        False,
        True,
    ),
    "nextdoor": (
        True,
        "Assisted workflow complete",
        "Manual final post or separately approved paid-ad setup in Nextdoor",
        "Assisted / paid setup",
        False,
        True,
    ),
    "chatgpt_ads": (
        False,
        "Planning package complete — advertiser connection required",
        "Set up an eligible OpenAI Ads Manager account, conversion measurement, and approved buyer-acquisition campaign before spending",
        "Paid setup required / planning package",
        True,
        False,
    ),
}


def build_channel_completion() -> tuple[ChannelCompletion, ...]:
    """Return one honest completion row for every registered marketing channel."""
    rows: list[ChannelCompletion] = []
    for channel in ALL_MARKETING_CHANNELS:
        (
            ready,
            completion_state,
            requirement,
            operating_mode,
            connection_required,
            manual_final_step_required,
        ) = _REQUIREMENTS.get(
            channel.key,
            (
                False,
                "Implementation review required",
                "Channel implementation still needs review",
                channel.mode.value,
                True,
                False,
            ),
        )
        rows.append(
            ChannelCompletion(
                key=channel.key,
                name=channel.name,
                built=channel.key in _REQUIREMENTS,
                tracked=True,
                ready_to_use=ready,
                completion_state=completion_state,
                next_requirement=requirement,
                operating_mode=operating_mode,
                connection_required=connection_required,
                manual_final_step_required=manual_final_step_required,
            )
        )
    return tuple(rows)


def completion_summary(rows: tuple[ChannelCompletion, ...]) -> dict[str, int]:
    return {
        "total": len(rows),
        "built": sum(row.built for row in rows),
        "tracked": sum(row.tracked for row in rows),
        "ready_to_use": sum(row.ready_to_use for row in rows),
        "connection_required": sum(row.connection_required for row in rows),
        "manual_final_step_required": sum(row.manual_final_step_required for row in rows),
        "not_ready_now": sum(not row.ready_to_use for row in rows),
    }
