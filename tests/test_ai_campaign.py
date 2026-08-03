from decimal import Decimal

from cfh_disposition.ai_campaign import (
    CampaignFactorySettings,
    CampaignPackage,
    build_fallback_campaign,
    marketing_address,
    property_fact_packet,
    validate_campaign_facts,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="101 Private Street",
        city="Bristol",
        state="VA",
        zip_code="24201",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("100000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="Habitable property sold as-is.",
        repairs_needed="Kitchen updates are needed.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms and availability are subject to verification.",
    )


def test_settings_read_key_and_model():
    settings = CampaignFactorySettings.from_mapping(
        {"OPENAI_API_KEY": " secret ", "OPENAI_MODEL": "gpt-5-mini"}
    )
    assert settings.configured
    assert settings.api_key == "secret"
    assert settings.model == "gpt-5-mini"


def test_fact_packet_contains_full_marketing_address_and_dwelyx():
    item = sample_property()
    packet = property_fact_packet(item, "https://www.dwelyx.com/?utm_source=test")
    assert packet["marketing_address"] == "101 Private Street, Bristol, VA 24201"
    assert item.address in str(packet)
    assert "dwelyx.com" in packet["dwelyx_url"]


def test_fallback_campaign_routes_everything_to_dwelyx_and_includes_address():
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    package = build_fallback_campaign(item, url)
    address = marketing_address(item)
    assert url in package.dwelyx_call_to_action
    assert url in package.marketplace_description
    assert url in package.sms_message
    for _, text in package.channel_rows():
        assert address in text
    assert validate_campaign_facts(package, item, url) == []


def test_fact_guard_accepts_approved_money_followed_by_punctuation():
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    package = build_fallback_campaign(item, url)
    package = package.model_copy(
        update={
            "short_description": (
                f"{package.short_description} Purchase price $100,000, down payment $5,000, "
                "and monthly payment $1,200."
            )
        }
    )
    assert validate_campaign_facts(package, item, url) == []


def test_fact_guard_blocks_unapproved_money_and_claims():
    item = sample_property()
    url = "https://www.dwelyx.com"
    address = marketing_address(item)
    unsafe = CampaignPackage(
        headline=f"Guaranteed Approval — {address}",
        short_description=f"{address}. Everyone approved with only $999 down. {url}",
        marketplace_description=f"{address}. No credit check. {url}",
        facebook_group_post=f"{address}. {url}",
        email_subject=f"Home — {address}",
        email_body=f"{address}. {url}",
        sms_message=f"{address}. {url}",
        classified_ad=f"{address}. {url}",
        social_caption=f"{address}. {url}",
        video_script=f"{address}. {url}",
        dwelyx_call_to_action=f"Browse {address}: {url}",
    )
    errors = validate_campaign_facts(unsafe, item, url)
    assert any("Prohibited claim" in error for error in errors)
    assert any("$999" in error for error in errors)


def test_fact_guard_blocks_missing_address_from_any_channel():
    item = sample_property()
    url = "https://www.dwelyx.com"
    address = marketing_address(item)
    incomplete = CampaignPackage(
        headline=f"Home — {address}",
        short_description=f"{address}. {url}",
        marketplace_description=f"{address}. {url}",
        facebook_group_post=f"{address}. {url}",
        email_subject=f"Home — {address}",
        email_body=f"{address}. {url}",
        sms_message=f"{address}. {url}",
        classified_ad=f"{address}. {url}",
        social_caption=f"{address}. {url}",
        video_script=f"{address}. {url}",
        dwelyx_call_to_action=url,
    )
    errors = validate_campaign_facts(incomplete, item, url)
    assert "Property address is missing from Dwelyx Call to Action." in errors
