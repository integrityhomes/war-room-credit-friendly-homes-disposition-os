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
    caption: str
    short_script: str
    shot_list: tuple[str, ...]
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


def build_social_video_package(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    channel_name: str,
    tracked_link: str,
) -> SocialVideoPackage:
    """Create a fact-only short-form social package for one property and channel."""
    _validate(property_, tracked_link)
    address = _property_label(property_)
    facts = _fact_lines(property_)
    fact_sentence = " • ".join(facts)

    hook = f"Looking for an owner-finance home in {property_.city or property_.state}?"
    caption_parts = [hook, address]
    if fact_sentence:
        caption_parts.append(fact_sentence)
    if property_.condition_summary:
        caption_parts.append(property_.condition_summary)
    caption_parts.append("See current details and continue in Dwelyx:")
    caption_parts.append(tracked_link)
    caption = "\n\n".join(caption_parts)

    script_lines = [
        hook,
        f"Take a quick look at {address}.",
    ]
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
        caption=caption,
        short_script=" ".join(script_lines),
        shot_list=shot_list,
        call_to_action="View current details in Dwelyx",
        tracked_link=tracked_link,
    )
