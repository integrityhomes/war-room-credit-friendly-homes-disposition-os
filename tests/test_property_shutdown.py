from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import URLError

import pytest

from cfh_disposition.automatic_launch import AutomationDispatchSettings
from cfh_disposition.buyer_conversion import (
    BuyerConversionLedger,
    ConversionRecord,
    ConversionStage,
)
from cfh_disposition.campaign_launch import LaunchStatus, new_launch_state
from cfh_disposition.channels import CHANNELS
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty, PropertyStatus
from cfh_disposition.property_shutdown import (
    ControlDispatchStatus,
    ControlTaskStatus,
    MarketingControlAction,
    PropertyControlError,
    PropertyControlLedger,
    append_control_event,
    build_property_control_event,
    build_property_control_payload,
    campaign_state_after_control,
    dispatch_property_control,
    mark_control_dispatch,
    update_buyer_task,
    update_channel_task,
)
from cfh_disposition.public_pages import is_public_property
from cfh_disposition.validation import validate_property_for_launch

NOW = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)


def property_record(**overrides) -> OwnerFinanceProperty:
    values = {
        "status": PropertyStatus.LIVE,
        "address": "945 W Packard St",
        "city": "Decatur",
        "state": "IL",
        "zip_code": "62522",
        "bedrooms": 3,
        "bathrooms": Decimal("1"),
        "total_price": Decimal("94500"),
        "down_payment": Decimal("2000"),
        "monthly_payment": Decimal("950"),
        "condition_summary": "Livable property sold as-is.",
        "repairs_needed": "Small drywall repairs.",
        "showing_instructions": "Appointment required.",
        "public_disclosures": "Possible updating.",
        "photo_urls": ["https://example.com/property.jpg"],
    }
    values.update(overrides)
    return OwnerFinanceProperty(**values)


def buyers_and_ledger(item: OwnerFinanceProperty):
    first = BuyerProfile(first_name="Jordan", last_name="Lee")
    second = BuyerProfile(first_name="Morgan", last_name="Hill")
    first_record = ConversionRecord(
        buyer_id=str(first.buyer_id),
        property_id=str(item.property_id),
        stage=ConversionStage.CONTRACT_PENDING,
        owner="Sabrina",
    )
    second_record = ConversionRecord(
        buyer_id=str(second.buyer_id),
        property_id=str(item.property_id),
        stage=ConversionStage.QUALIFIED,
        owner="Carlos",
    )
    ledger = BuyerConversionLedger(records=[first_record, second_record])
    return [first, second], ledger, first_record, second_record


def test_pending_event_covers_all_channels_and_protects_winning_buyer() -> None:
    item = property_record()
    buyers, conversion_ledger, winner, other = buyers_and_ledger(item)

    updated, event = build_property_control_event(
        item,
        MarketingControlAction.PENDING,
        reason="Contract signed.",
        requested_by="Sabrina",
        conversion_ledger=conversion_ledger,
        buyers=buyers,
        winning_conversion_record_id=winner.record_id,
        now=NOW,
    )

    assert updated.status == PropertyStatus.PENDING
    assert len(event.channel_tasks) == len(CHANNELS) == 15
    assert event.channel_tasks[0].status == ControlTaskStatus.CONFIRMED
    winner_task = next(
        task
        for task in event.buyer_tasks
        if task.conversion_record_id == winner.record_id
    )
    other_task = next(
        task
        for task in event.buyer_tasks
        if task.conversion_record_id == other.record_id
    )
    assert winner_task.status == ControlTaskStatus.NOT_APPLICABLE
    assert other_task.status == ControlTaskStatus.READY
    assert "another available Dwelyx home" in other_task.action


def test_filled_status_hides_public_property_and_blocks_launch() -> None:
    item = property_record()
    updated, _ = build_property_control_event(
        item,
        MarketingControlAction.FILLED,
        reason="Buyer moved in.",
        requested_by="Sabrina",
        now=NOW,
    )

    assert updated.status == PropertyStatus.FILLED
    assert not is_public_property(updated)
    validation = validate_property_for_launch(updated)
    assert not validation.can_launch
    assert any("Filled" in error for error in validation.errors)


def test_resume_requires_complete_launch_ready_property() -> None:
    paused = property_record(
        status=PropertyStatus.PAUSED,
        photo_urls=[],
    )

    with pytest.raises(PropertyControlError, match="launch gate"):
        build_property_control_event(
            paused,
            MarketingControlAction.RESUME,
            reason="Repairs completed.",
            requested_by="Sabrina",
            now=NOW,
        )

    complete = property_record(status=PropertyStatus.PAUSED)
    updated, event = build_property_control_event(
        complete,
        MarketingControlAction.RESUME,
        reason="Property is available again.",
        requested_by="Sabrina",
        now=NOW,
    )
    assert updated.status == PropertyStatus.LIVE
    assert event.operation.value == "Resume"
    assert is_public_property(updated)


def test_control_payload_contains_no_buyer_personal_data() -> None:
    item = property_record()
    buyers, conversion_ledger, _, _ = buyers_and_ledger(item)
    _, event = build_property_control_event(
        item,
        MarketingControlAction.SOLD,
        reason="Sale completed.",
        requested_by="Sabrina",
        conversion_ledger=conversion_ledger,
        buyers=buyers,
        now=NOW,
    )

    payload = build_property_control_payload(event)
    serialized = str(payload)

    assert payload["buyer_destination"]["old_property_links_redirect_to_full_inventory"] is True
    assert payload["buyer_destination"]["publish_property_to_dwelyx"] is False
    assert payload["buyer_reroute"]["affected_active_records"] == 2
    assert payload["buyer_reroute"]["send_buyer_personal_data"] is False
    assert "Jordan" not in serialized
    assert "Morgan" not in serialized
    assert len(payload["channels"]) == 15


def test_successful_dispatch_updates_automatic_tasks_but_not_manual_tasks() -> None:
    item = property_record()
    _, event = build_property_control_event(
        item,
        MarketingControlAction.PAUSE,
        reason="Repairs in progress.",
        requested_by="Sabrina",
        now=NOW,
    )
    ledger = append_control_event(PropertyControlLedger(), event)
    updated = mark_control_dispatch(
        ledger,
        event_id=event.event_id,
        status=ControlDispatchStatus.SUCCEEDED,
        detail="Accepted.",
        now=NOW,
    )
    saved = updated.events[0]

    assert saved.dispatch_status == ControlDispatchStatus.SUCCEEDED
    assert next(
        task for task in saved.channel_tasks if task.channel_key == "email"
    ).status == ControlTaskStatus.DISPATCHED
    assert next(
        task for task in saved.channel_tasks if task.channel_key == "nextdoor"
    ).status == ControlTaskStatus.READY
    assert next(
        task for task in saved.channel_tasks if task.channel_key == "property_page"
    ).status == ControlTaskStatus.CONFIRMED


def test_campaign_state_reflects_shutdown_and_resume_work() -> None:
    item = property_record()
    _, shutdown_event = build_property_control_event(
        item,
        MarketingControlAction.SOLD,
        reason="Sale completed.",
        requested_by="Sabrina",
        now=NOW,
    )
    state = new_launch_state(item.property_id, "owner_finance_homes", now=NOW)
    stopped = campaign_state_after_control(
        state,
        shutdown_event,
        dispatch_status=ControlDispatchStatus.SUCCEEDED,
        now=NOW,
    )

    assert stopped.channels["property_page"].status == LaunchStatus.PAUSED
    assert stopped.channels["email"].status == LaunchStatus.PAUSED
    assert stopped.channels["nextdoor"].status == LaunchStatus.READY

    paused = item.model_copy(update={"status": PropertyStatus.PAUSED})
    _, resume_event = build_property_control_event(
        paused,
        MarketingControlAction.RESUME,
        reason="Available again.",
        requested_by="Sabrina",
        now=NOW,
    )
    resumed = campaign_state_after_control(
        stopped,
        resume_event,
        dispatch_status=ControlDispatchStatus.SUCCEEDED,
        now=NOW,
    )
    assert resumed.channels["property_page"].status == LaunchStatus.POSTED
    assert resumed.channels["email"].status == LaunchStatus.SCHEDULED
    assert resumed.channels["nextdoor"].status == LaunchStatus.READY


def test_manual_channel_and_buyer_tasks_can_be_confirmed() -> None:
    item = property_record()
    buyers, conversion_ledger, _, other = buyers_and_ledger(item)
    _, event = build_property_control_event(
        item,
        MarketingControlAction.SOLD,
        reason="Sale completed.",
        requested_by="Sabrina",
        conversion_ledger=conversion_ledger,
        buyers=buyers,
        now=NOW,
    )
    ledger = append_control_event(PropertyControlLedger(), event)
    ledger = update_channel_task(
        ledger,
        event_id=event.event_id,
        channel_key="nextdoor",
        status=ControlTaskStatus.CONFIRMED,
        updated_by="Sabrina",
        notes="Business Post removed and paid ad paused.",
        now=NOW,
    )
    ledger = update_buyer_task(
        ledger,
        event_id=event.event_id,
        conversion_record_id=other.record_id,
        status=ControlTaskStatus.CONFIRMED,
        updated_by="Carlos",
        notes="Sent two available alternatives.",
        now=NOW,
    )

    saved = ledger.events[0]
    assert next(
        task for task in saved.channel_tasks if task.channel_key == "nextdoor"
    ).status == ControlTaskStatus.CONFIRMED
    assert next(
        task
        for task in saved.buyer_tasks
        if task.conversion_record_id == other.record_id
    ).status == ControlTaskStatus.CONFIRMED


def test_dispatch_uses_property_control_event_header(monkeypatch) -> None:
    item = property_record()
    _, event = build_property_control_event(
        item,
        MarketingControlAction.PAUSE,
        reason="Repairs in progress.",
        requested_by="Sabrina",
        now=NOW,
    )
    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b"accepted"

    def fake_urlopen(request, timeout):
        captured["event"] = request.headers["X-cfh-event"]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "cfh_disposition.property_shutdown.urlopen",
        fake_urlopen,
    )
    receipt = dispatch_property_control(
        event,
        AutomationDispatchSettings(
            webhook_url="https://automation.example.com/property-control",
            signing_secret="secret",
        ),
    )

    assert receipt.status_code == 202
    assert captured["event"] == "credit_friendly_homes.property.marketing_control"
    assert captured["timeout"] == 30


def test_dispatch_failure_leaves_manual_task_board_available(monkeypatch) -> None:
    item = property_record()
    _, event = build_property_control_event(
        item,
        MarketingControlAction.PAUSE,
        reason="Repairs in progress.",
        requested_by="Sabrina",
        now=NOW,
    )

    def fail_urlopen(request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(
        "cfh_disposition.property_shutdown.urlopen",
        fail_urlopen,
    )
    with pytest.raises(PropertyControlError, match="task board"):
        dispatch_property_control(
            event,
            AutomationDispatchSettings(
                webhook_url="https://automation.example.com/property-control"
            ),
        )
