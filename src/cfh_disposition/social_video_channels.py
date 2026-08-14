from __future__ import annotations

from dataclasses import dataclass

from .models import OwnerFinanceProperty


class SocialVideoPackageError(ValueError):
    """Raised when a property is missing facts required for social promotion."""


@dataclass(frozen=True, slots=True)
class SocialVideoPackage:
    channel_key: str
    channel_name: str
    hook: str
    post_title: str
    caption: str
    caption_variants: tuple[str, ...]
    short_script: str
    on_screen_text: tuple[str, ...]
    shot_list: tuple[str, ...]
    hashtags: tuple[str, ...]
    posting_notes: tuple[str, ...]
    call_to_action: str
    tracked_link: str


def _money(value) -> str:
    return f"${value:,.0f}" if value is not None else ""


def _property_label(property_: OwnerFinanceProperty) -> str:
    return property_.display_address or "this available home"


def _fact_lines(property_: OwnerFinanceProperty) -> list[str]:
    facts: list[str] = []
    if property_.bedrooms is not None:
        facts.append(f"{property_.bedrooms} bedroom" + ("" if property_.bedrooms == 1 else "s"))
    if property_.bathrooms is not None:
        facts.append(f"{property_.bathrooms:g} bathroom" + ("" if property_.bathrooms == 1 else "s"))
    if property_.monthly_payment is not None:
        facts.append(f"monthly payment {_money(property_.monthly_payment)}")
    if property_.down_payment is not None:
        facts.append(f"down payment {_money(property_.down_payment)}")
    if property_.total_price is not None:
        facts.append(f"price {_money(property_.total_price)}")
    return facts


def _validate(property_: OwnerFinanceProperty, tracked_link: str) -> None:
    if not property_.display_address:
        raise SocialVideoPackageError("Property address is required before creating social content.")
    if not tracked_link.strip():
        raise SocialVideoPackageError("A tracked Dwelyx link is required.")
    if property_.monthly_payment is None and property_.total_price is None:
        raise SocialVideoPackageError(
            "Add at least a monthly payment or total price before creating social content."
        )


def _location(property_: OwnerFinanceProperty) -> str:
    if property_.city and property_.state:
        return f"{property_.city}, {property_.state}"
    return property_.city or property_.state or "your area"


def _platform_fields(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    tracked_link: str,
    hook: str,
    facts: list[str],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    location = _location(property_)
    address = _property_label(property_)
    price_fact = _money(property_.monthly_payment or property_.total_price)

    if channel_key == "instagram":
        title = f"Owner-finance home in {location}"
        hashtags = (
            "#OwnerFinancing",
            "#CreditFriendlyHomes",
            f"#{(property_.city or property_.state or 'Homes').replace(' ', '')}",
            "#HomeBuyer",
            "#HomesForSale",
        )
        on_screen = (
            hook,
            address,
            f"Current details from {price_fact}" if price_fact else "See current property details",
            "View current details in Dwelyx",
        )
        notes = (
            "Use for an Instagram Reel or feed post.",
            "Keep the tracked Dwelyx link attached to the post or profile-link workflow used for this campaign.",
            "Do not add financing promises or property claims that are not in the saved property record.",
        )
    elif channel_key == "tiktok":
        title = f"Take a look at this owner-finance home in {location}"
        hashtags = (
            "#OwnerFinance",
            "#HomeTour",
            "#CreditFriendlyHomes",
            f"#{(property_.city or property_.state or 'Homes').replace(' ', '')}",
            "#RealEstate",
        )
        on_screen = (
            "Owner-finance home available",
            address,
            ", ".join(facts[:2]) if facts else "Current details available",
            "Open the tracked Dwelyx link for current details",
        )
        notes = (
            "Lead with the strongest exterior or interior shot in the first 2 seconds.",
            "Use the exact tracked link for this TikTok campaign wherever the profile/post workflow permits it.",
            "Keep the property visually truthful to the uploaded photos or video.",
        )
    elif channel_key == "youtube":
        title = f"Owner Finance Home in {location} | Quick Tour"
        hashtags = (
            "#Shorts",
            "#OwnerFinancing",
            "#CreditFriendlyHomes",
            f"#{(property_.city or property_.state or 'Homes').replace(' ', '')}",
        )
        on_screen = (
            f"Owner Finance | {location}",
            address,
            ", ".join(facts[:2]) if facts else "Current property details",
            "Details + next step in Dwelyx",
        )
        notes = (
            "Publish as a vertical YouTube Short.",
            "Put the tracked Dwelyx link in the description and pinned comment when available.",
            "Long-form walkthrough rendering remains a separate later build.",
        )
    else:
        raise SocialVideoPackageError(f"Unsupported social channel: {channel_key}")

    return title, hashtags, on_screen, notes


def _caption_variants(
    *,
    hook: str,
    address: str,
    fact_sentence: str,
    condition_summary: str | None,
    tracked_link: str,
) -> tuple[str, ...]:
    details = fact_sentence or "Current property details available in Dwelyx"
    condition = f"\n{condition_summary}" if condition_summary else ""
    return (
        f"{hook}\n\n{address}\n\n{details}{condition}\n\nSee current details in Dwelyx:\n{tracked_link}",
        f"New property opportunity: {address}\n\n{details}{condition}\n\nView the current details here:\n{tracked_link}",
        f"Quick look at {address}.\n\n{details}{condition}\n\nUse this link for current property details and next steps:\n{tracked_link}",
    )


def build_social_video_package(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    channel_name: str,
    tracked_link: str,
) -> SocialVideoPackage:
    """Create a fact-only, ready-to-post short-form social package for one property and channel."""
    _validate(property_, tracked_link)
    address = _property_label(property_)
    facts = _fact_lines(property_)
    fact_sentence = " • ".join(facts)
    hook = f"Looking for an owner-finance home in {_location(property_)}?"

    variants = _caption_variants(
        hook=hook,
        address=address,
        fact_sentence=fact_sentence,
        condition_summary=property_.condition_summary,
        tracked_link=tracked_link,
    )
    post_title, hashtags, on_screen_text, posting_notes = _platform_fields(
        property_,
        channel_key=channel_key,
        tracked_link=tracked_link,
        hook=hook,
        facts=facts,
    )

    script_lines = [hook, f"Take a quick look at {address}."]
    if facts:
        script_lines.append("Here are the current terms: " + ", ".join(facts) + ".")
    if property_.condition_summary:
        script_lines.append(property_.condition_summary)
    script_lines.append("Use the link with this post to view the current details in Dwelyx.")

    shot_list = (
        "Front exterior / opening shot",
        "Best interior room",
        "Kitchen",
        "Bathroom",
        "Bedroom or flexible room",
        "Yard / exterior feature",
        "Final exterior shot with call to action",
    )

    return SocialVideoPackage(
        channel_key=channel_key,
        channel_name=channel_name,
        hook=hook,
        post_title=post_title,
        caption=variants[0],
        caption_variants=variants,
        short_script=" ".join(script_lines),
        on_screen_text=on_screen_text,
        shot_list=shot_list,
        hashtags=hashtags,
        posting_notes=posting_notes,
        call_to_action="View current details in Dwelyx",
        tracked_link=tracked_link,
    )
