import json
from decimal import Decimal

import cfh_disposition.ai_campaign as ai_campaign
from cfh_disposition.ai_campaign import (
    CampaignFactorySettings,
    CampaignPackage,
    build_fallback_campaign,
    generate_ai_campaign,
    marketing_address,
    normalize_campaign_payload,
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


def test_campaign_package_accepts_detailed_short_description():
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    fallback = build_fallback_campaign(item, url)
    payload = fallback.model_dump()
    payload["short_description"] = f"{marketing_address(item)}. " + ("Detailed property information. " * 22) + url
    package = CampaignPackage.model_validate(payload)
    assert len(package.short_description) > 500
    assert len(package.short_description) <= 1000


def test_overlong_ai_fields_are_replaced_individually_with_safe_fallbacks():
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    fallback = build_fallback_campaign(item, url)
    payload = fallback.model_dump()
    payload["headline"] = f"AI headline — {marketing_address(item)}"
    payload["sms_message"] = "x" * 900
    payload["short_description"] = "y" * 1500

    normalized = normalize_campaign_payload(payload, fallback)
    package = CampaignPackage.model_validate(normalized)

    assert package.headline == payload["headline"]
    assert package.sms_message == fallback.sms_message
    assert package.short_description == fallback.short_description
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


def test_generate_ai_campaign_retries_one_timeout(monkeypatch):
    item = sample_property()
    url = "https://www.dwelyx.com/?utm_source=credit_friendly_homes"
    expected = build_fallback_campaign(item, url)
    calls: list[int] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps({"output_text": expected.model_dump_json()}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return FakeResponse()

    monkeypatch.setattr(ai_campaign, "urlopen", fake_urlopen)
    generated = generate_ai_campaign(
        item,
        url,
        CampaignFactorySettings(api_key="test-key"),
        timeout_seconds=1,
    )

    assert generated == expected
    assert calls == [1, 1]


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
