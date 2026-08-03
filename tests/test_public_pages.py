from decimal import Decimal

from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.public_pages import is_public_property, public_location, public_portal_path, public_property_path


def launch_ready_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        status=PropertyStatus.READY,
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
        showing_instructions="Appointment required.",
        public_disclosures="Owner financing terms are subject to verification.",
        photo_urls=["https://example.com/property.jpg"],
    )


def test_public_location_includes_complete_street_address():
    item = launch_ready_property()
    assert public_location(item) == "101 Private Street, Bristol, VA 24201"
    assert item.address in public_location(item)


def test_only_ready_or_live_launchable_properties_are_public():
    item = launch_ready_property()
    assert is_public_property(item)

    item.status = PropertyStatus.LIVE
    assert is_public_property(item)

    item.status = PropertyStatus.NEEDS_INFORMATION
    assert not is_public_property(item)

    item.status = PropertyStatus.READY
    item.photo_urls = []
    assert not is_public_property(item)


def test_public_paths_use_query_parameters():
    item = launch_ready_property()
    assert public_property_path(item.property_id) == f"?property={item.property_id}"
    assert public_portal_path() == "?homes=1"
