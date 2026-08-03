from __future__ import annotations

from decimal import Decimal

from .models import (
    BuyerProfile,
    CommunicationPreference,
    OwnerFinanceProperty,
    PropertyStatus,
)

SAMPLE_PROPERTIES = [
    OwnerFinanceProperty(
        status=PropertyStatus.READY,
        address="101 Sample Ridge Road",
        city="Saltville",
        state="VA",
        zip_code="24370",
        county="Smyth",
        bedrooms=2,
        bathrooms=Decimal("1"),
        square_feet=980,
        acreage=Decimal("1.0"),
        total_price=Decimal("119900"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="Partially remodeled home with a completed exterior and unfinished kitchen.",
        repairs_needed="Kitchen drywall, cabinets, countertops, and final finish work.",
        photo_urls=[f"https://example.com/sample-home-{index}.jpg" for index in range(1, 11)],
        video_url="https://example.com/sample-video",
        application_url="https://example.com/apply",
        showing_instructions="Showing by confirmed appointment only.",
        public_disclosures="Owner-financing terms and buyer eligibility are subject to review. Property sold as-is.",
    ),
    OwnerFinanceProperty(
        status=PropertyStatus.NEEDS_INFORMATION,
        address="202 Demo Avenue",
        city="Bristol",
        state="VA",
        zip_code="24201",
        bedrooms=3,
        bathrooms=Decimal("1.5"),
        total_price=Decimal("149900"),
        down_payment=Decimal("7500"),
        monthly_payment=Decimal("1395"),
        condition_summary="Vacant home needing cosmetic updates.",
        repairs_needed="Paint, flooring, and minor exterior repairs.",
        photo_urls=["https://example.com/demo-1.jpg"],
    ),
]

SAMPLE_BUYERS = [
    BuyerProfile(
        first_name="Jordan",
        last_name="Sample",
        email="jordan@example.com",
        phone="555-0101",
        preferred_cities=["Saltville", "Bristol"],
        preferred_states=["VA"],
        minimum_bedrooms=2,
        maximum_monthly_payment=Decimal("1300"),
        available_down_payment=Decimal("6000"),
        move_timeframe_days=45,
        communication_preference=CommunicationPreference.PHONE,
        email_consent=True,
        sms_consent=True,
        call_consent=True,
        source="Website",
    ),
    BuyerProfile(
        first_name="Morgan",
        last_name="Demo",
        email="morgan@example.com",
        preferred_cities=["Bristol"],
        preferred_states=["VA"],
        minimum_bedrooms=3,
        maximum_monthly_payment=Decimal("1100"),
        available_down_payment=Decimal("2500"),
        email_consent=True,
        source="Facebook Group",
    ),
]
