from datetime import UTC, datetime
from decimal import Decimal

from cfh_disposition.campaign_launch import (
    LaunchStatus,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.channels import CHANNELS
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.simple_flow import (
    MORE_TOOL_OPTIONS,
    PRIMARY_NAVIGATION,
    SimpleFlowStatus,
    build_simple_marketing_flow,
    launched_channel_count,
)

NOW = datetime(2026, 8, 5, 22, 0, tzinfo=UTC)


def ready_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        status=PropertyStatus.READY,
        address="101 Test Street",
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
        public_disclosures="Terms, condition, and availability are subject to verification.",
        photo_urls=["https://example.com/property.jpg"],
    )


def test_primary_navigation_keeps_normal_work_simple() -> None:
    assert PRIMARY_NAVIGATION == (
        "Simple Marketing Flow",
        "Property Intake",
        "Campaign Readiness",
        "Campaign Launch Center",
        "More Tools",
        "System Setup",
    )
    assert MORE_TOOL_OPTIONS == (
        "Record Manager",
        "Dwelyx Traffic Hub",
        "Marketplace Guard",
    )


def test_no_property_points_to_property_intake() -> None:
    flow = build_simple_marketing_flow([])

    assert flow.next_step.destination == "Property Intake"
    assert flow.next_step.button_label == "Add Property"
    assert flow.steps[0].status == SimpleFlowStatus.ACTION_REQUIRED
    assert flow.steps[1].status == SimpleFlowStatus.BLOCKED
    assert flow.steps[2].status == SimpleFlowStatus.BLOCKED


def test_missing_property_information_points_to_record_manager() -> None:
    property_record = ready_property().model_copy(
        update={"condition_summary": "", "status": PropertyStatus.NEEDS_INFORMATION}
    )

    flow = build_simple_marketing_flow([property_record])

    assert flow.steps[0].status == SimpleFlowStatus.COMPLETE
    assert flow.steps[1].status == SimpleFlowStatus.ACTION_REQUIRED
    assert flow.steps[2].status == SimpleFlowStatus.BLOCKED
    assert flow.next_step.destination == "More Tools"
    assert flow.next_step.button_label == "Fix Property Information"


def test_ready_property_without_launch_points_to_launch_center() -> None:
    property_record = ready_property()

    flow = build_simple_marketing_flow([property_record])

    assert flow.steps[1].status == SimpleFlowStatus.COMPLETE
    assert flow.steps[2].status == SimpleFlowStatus.ACTION_REQUIRED
    assert flow.next_step.destination == "Campaign Launch Center"
    assert flow.launched_channels == 0
    assert flow.total_channels == 15


def test_partial_launch_reports_channel_progress() -> None:
    property_record = ready_property()
    state = new_launch_state(property_record.property_id, "owner_finance_homes", now=NOW)
    for channel in CHANNELS[:4]:
        state = set_channel_status(
            state,
            channel.key,
            LaunchStatus.POSTED,
            updated_by="Sabrina",
            now=NOW,
        )

    flow = build_simple_marketing_flow(
        [property_record],
        selected_property_id=str(property_record.property_id),
        launch_state=state,
    )

    assert launched_channel_count(state) == 4
    assert flow.launched_channels == 4
    assert flow.steps[2].status == SimpleFlowStatus.ACTION_REQUIRED
    assert "4 of 15" in flow.steps[2].detail
    assert flow.next_step.button_label == "Finish Channel Launch"


def test_all_15_channels_complete_the_simple_flow() -> None:
    property_record = ready_property()
    state = new_launch_state(property_record.property_id, "owner_finance_homes", now=NOW)
    for index, channel in enumerate(CHANNELS):
        status = LaunchStatus.POSTED if index % 2 == 0 else LaunchStatus.SCHEDULED
        state = set_channel_status(
            state,
            channel.key,
            status,
            updated_by="Sabrina",
            now=NOW,
        )

    flow = build_simple_marketing_flow(
        [property_record],
        launch_state=state,
    )

    assert flow.launched_channels == len(CHANNELS) == 15
    assert flow.steps[2].status == SimpleFlowStatus.COMPLETE
    assert flow.complete is True
    assert flow.next_step.button_label == "Review Marketing"
