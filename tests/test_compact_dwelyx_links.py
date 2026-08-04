from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from cfh_disposition.ai_campaign import CAMPAIGN_FIELD_LIMITS, build_fallback_campaign
from cfh_disposition.dwelyx import DEFAULT_DWELYX_URL, build_dwelyx_url
from cfh_disposition.models import OwnerFinanceProperty


def test_default_buyer_destination_uses_compact_tracking_link() -> None:
    property_id = uuid4()
    url = build_dwelyx_url(
        DEFAULT_DWELYX_URL,
        source="credit_friendly_homes",
        medium="property_campaign",
        campaign="owner_finance_home",
        property_id=property_id,
    )

    query = parse_qs(urlsplit(url).query)
    assert query["go"] == ["dwelyx"]
    assert query["medium"] == ["property_campaign"]
    assert query["campaign"] == ["owner_finance_home"]
    assert query["property_id"] == [str(property_id)]
    assert "target" not in query
    assert "source" not in query


def test_compact_tracking_link_keeps_fallback_sms_within_limit() -> None:
    item = OwnerFinanceProperty(
        address="945 West Packard Street",
        city="Decatur",
        state="IL",
        zip_code="62521",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("90000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="Property condition details are available for buyer review.",
        repairs_needed="Buyer should independently verify all property condition details.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms, condition, and availability are subject to verification.",
    )
    link = build_dwelyx_url(
        DEFAULT_DWELYX_URL,
        source="credit_friendly_homes",
        medium="property_campaign",
        campaign="owner_finance_home",
        property_id=item.property_id,
    )

    package = build_fallback_campaign(item, link)

    assert len(package.sms_message) <= CAMPAIGN_FIELD_LIMITS["sms_message"]
