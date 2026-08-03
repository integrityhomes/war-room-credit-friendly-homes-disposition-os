from decimal import Decimal

from cfh_disposition.ai_campaign import (
    CampaignFactorySettings,
    CampaignPackage,
    build_fallback_campaign,
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


def test_fact_packet_hides_street_address_and_contains_dwelyx():
    item = sample_property()
    packet = property_fact_packet(item, "https://www.dwelyx.com/?utm_source=test")
    assert packet["public_location"] == "Bristol, VA, 24201"
    assert item.address not in str(packet)
    assert "dwelyx.com" in packet["dwelyx_url"]


def test_fallback_campaign_routes_everything_to_dwelyx():
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    package = build_fallback_campaign(item, url)
    assert url in package.dwelyx_call_to_action
    assert url in package.marketplace_description
    assert url in package.sms_message
    assert validate_campaign_facts(package, item, url) == []


def test_fact_guard_blocks_unapproved_money_and_claims():
    item = sample_property()
    url = "https://www.dwelyx.com"
    unsafe = CampaignPackage(
        headline="Guaranteed Approval",
        short_description=f"Everyone approved with only $999 down. {url}",
        marketplace_description=f"No credit check. {url}",
        facebook_group_post=url,
        email_subject="Home",
        email_body=url,
        sms_message=url,
        classified_ad=url,
        social_caption=url,
        video_script=url,
        dwelyx_call_to_action=url,
    )
    errors = validate_campaign_facts(unsafe, item, url)
    assert any("Prohibited claim" in error for error in errors)
    assert any("$999" in error for error in errors)


def test_fact_guard_blocks_street_address_exposure():
    item = sample_property()
    url = "https://www.dwelyx.com"
    unsafe = CampaignPackage(
        headline="Home",
        short_description=f"See 101 Private Street. {url}",
        marketplace_description=url,
        facebook_group_post=url,
        email_subject="Home",
        email_body=url,
        sms_message=url,
        classified_ad=url,
        social_caption=url,
        video_script=url,
        dwelyx_call_to_action=url,
    )
    errors = validate_campaign_facts(unsafe, item, url)
    assert "Street address was exposed in public marketing copy." in errors
