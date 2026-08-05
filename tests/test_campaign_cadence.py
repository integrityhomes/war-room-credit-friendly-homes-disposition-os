from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.automatic_launch import AutomationDispatchSettings, LaunchAction
from cfh_disposition.campaign_cadence import (
    CADENCE_BUCKET,
    CADENCE_PATH,
    CadenceAction,
    CadencePriority,
    CampaignCadenceError,
    CampaignCadenceLedger,
    CampaignCadenceStore,
    ChannelCadencePolicy,
    RefreshTaskStatus,
    approve_refresh_task,
    build_cadence_queue,
    build_refresh_materials,
    build_refresh_payload,
    cadence_snapshot,
    create_refresh_batch,
    default_cadence_policies,
    ensure_all_policies,
    update_refresh_task,
    upsert_policy,
)
from cfh_disposition.campaign_launch import (
    LaunchStatus,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.channels import CHANNELS
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionEvent,
    DwelyxEventType,
)
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus

NOW = datetime(2026, 8, 5, 21, 30, tzinfo=UTC)


def sample_property(**overrides) -> OwnerFinanceProperty:
    values = {
        "status": PropertyStatus.LIVE,
        "address": "101 Test Street",
        "city": "Bristol",
        "state": "VA",
        "zip_code": "24201",
        "bedrooms": 3,
        "bathrooms": Decimal("1"),
        "total_price": Decimal("100000"),
        "down_payment": Decimal("5000"),
        "monthly_payment": Decimal("1200"),
        "condition_summary": "Habitable property sold as-is.",
        "repairs_needed": "Kitchen updates are needed.",
        "showing_instructions": "Appointment required.",
        "public_disclosures": "Terms and availability are subject to verification.",
        "created_at": NOW - timedelta(days=60),
        "updated_at": NOW - timedelta(days=20),
    }
    values.update(overrides)
    return OwnerFinanceProperty(**values)


def launch_state_for(
    property_record: OwnerFinanceProperty,
    *,
    channel_key: str,
    status: LaunchStatus,
    updated_at: datetime,
):
    state = new_launch_state(property_record.property_id, "owner_finance_homes", now=updated_at)
    return set_channel_status(
        state,
        channel_key,
        status,
        updated_by="Sabrina",
        notes="Test placement.",
        now=updated_at,
    )


def event_record(
    property_record: OwnerFinanceProperty,
    *,
    event_type: DwelyxEventType,
    channel_key: str = "email",
    event_id: str = "event_12345678",
) -> DwelyxAttributionEvent:
    return DwelyxAttributionEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=NOW - timedelta(days=1),
        dwelyx_buyer_id="buyer_abc123",
        cfh_property_id=str(property_record.property_id),
        source="credit_friendly_homes",
        medium=channel_key,
        campaign="owner_finance_homes",
    )


def test_default_policies_and_active_queue_cover_all_15_channels() -> None:
    property_record = sample_property()
    ledger = CampaignCadenceLedger()

    policies = default_cadence_policies(NOW)
    queue = build_cadence_queue([property_record], ledger=ledger, now=NOW)

    assert len(policies) == len(CHANNELS) == 15
    assert {policy.channel_key for policy in policies} == {channel.key for channel in CHANNELS}
    assert len(queue) == 15
    assert {item.channel_key for item in queue} == {channel.key for channel in CHANNELS}
    assert all(item.priority == CadencePriority.OVERDUE for item in queue)
    assert all(item.action == CadenceAction.LAUNCH_MISSING for item in queue)


def test_inactive_property_does_not_create_refresh_work() -> None:
    property_record = sample_property(status=PropertyStatus.PAUSED)

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )

    assert len(queue) == 15
    assert all(item.priority == CadencePriority.INACTIVE for item in queue)
    assert all(item.action == CadenceAction.NOT_ACTIVE for item in queue)


def test_saved_channel_activity_becomes_overdue_after_internal_cadence() -> None:
    property_record = sample_property()
    state = launch_state_for(
        property_record,
        channel_key="facebook_groups",
        status=LaunchStatus.POSTED,
        updated_at=NOW - timedelta(days=10),
    )

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        launch_states={str(property_record.property_id): state},
        now=NOW,
    )
    row = next(item for item in queue if item.channel_key == "facebook_groups")

    assert row.cadence_days == 7
    assert row.priority == CadencePriority.OVERDUE
    assert row.action == CadenceAction.REFRESH
    assert row.days_overdue >= 3


def test_recorded_active_placement_with_no_traffic_is_verified_before_reposting() -> None:
    property_record = sample_property()
    state = launch_state_for(
        property_record,
        channel_key="blog",
        status=LaunchStatus.POSTED,
        updated_at=NOW - timedelta(days=20),
    )

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        launch_states={str(property_record.property_id): state},
        click_events=[],
        now=NOW,
    )
    row = next(item for item in queue if item.channel_key == "blog")

    assert row.cadence_days == 30
    assert row.priority == CadencePriority.DUE_NOW
    assert row.action == CadenceAction.VERIFY
    assert "no tracked clicks" in row.reason.lower()


def test_recent_clicks_keep_a_current_channel_current() -> None:
    property_record = sample_property()
    state = launch_state_for(
        property_record,
        channel_key="blog",
        status=LaunchStatus.POSTED,
        updated_at=NOW - timedelta(days=5),
    )
    click = ClickEvent(
        occurred_at=NOW - timedelta(days=1),
        source="credit_friendly_homes",
        medium="blog",
        campaign="owner_finance_homes",
        property_id=str(property_record.property_id),
    )

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        launch_states={str(property_record.property_id): state},
        click_events=[click],
        now=NOW,
    )
    row = next(item for item in queue if item.channel_key == "blog")

    assert row.priority == CadencePriority.CURRENT
    assert row.action == CadenceAction.KEEP
    assert row.clicks_7 == 1
    assert row.clicks_30 == 1


def test_signed_contract_protects_every_property_channel_from_refresh() -> None:
    property_record = sample_property()
    contract = event_record(
        property_record,
        event_type=DwelyxEventType.CONTRACT_SIGNED,
        channel_key="google_ads",
        event_id="event_contract_123",
    )

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        attribution_events=[contract],
        now=NOW,
    )

    assert len(queue) == 15
    assert all(item.priority == CadencePriority.BLOCKED for item in queue)
    assert all(item.action == CadenceAction.PROTECT_CONTRACT for item in queue)


def test_failed_launch_is_blocked_for_repair() -> None:
    property_record = sample_property()
    state = launch_state_for(
        property_record,
        channel_key="instagram",
        status=LaunchStatus.FAILED,
        updated_at=NOW - timedelta(days=1),
    )

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        launch_states={str(property_record.property_id): state},
        now=NOW,
    )
    row = next(item for item in queue if item.channel_key == "instagram")

    assert row.priority == CadencePriority.BLOCKED
    assert row.action == CadenceAction.REPAIR_FAILED


def test_editable_policy_changes_only_selected_channel() -> None:
    ledger = ensure_all_policies(CampaignCadenceLedger(), now=NOW)
    edited = ChannelCadencePolicy(
        channel_key="nextdoor",
        cadence_days=21,
        warning_days=4,
        enabled=True,
        default_owner="Carlos",
        notes="Internal test rule.",
        updated_at=NOW,
    )

    updated = upsert_policy(ledger, edited, now=NOW)
    nextdoor = next(item for item in updated.policies if item.channel_key == "nextdoor")
    email = next(item for item in updated.policies if item.channel_key == "email")

    assert len(updated.policies) == 15
    assert nextdoor.cadence_days == 21
    assert nextdoor.warning_days == 4
    assert nextdoor.default_owner == "Carlos"
    assert email.cadence_days == 14


def test_policy_rejects_warning_window_equal_to_cadence() -> None:
    with pytest.raises(ValueError, match="Warning days"):
        ChannelCadencePolicy(
            channel_key="email",
            cadence_days=7,
            warning_days=7,
        )


def test_refresh_batches_skip_current_and_prevent_duplicate_open_tasks() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    selected = [item for item in queue if item.channel_key in {"email", "nextdoor"}]

    ledger, created = create_refresh_batch(
        CampaignCadenceLedger(),
        selected,
        requested_by="Sabrina",
        now=NOW,
    )

    assert len(created) == 2
    assert {task.channel_key for task in created} == {"email", "nextdoor"}
    assert len({task.batch_id for task in created}) == 1

    with pytest.raises(CampaignCadenceError, match="No new refresh tasks"):
        create_refresh_batch(
            ledger,
            selected,
            requested_by="Sabrina",
            now=NOW + timedelta(minutes=1),
        )


def test_manager_approval_is_required_before_nextdoor_confirmation() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    nextdoor = next(item for item in queue if item.channel_key == "nextdoor")
    ledger, created = create_refresh_batch(
        CampaignCadenceLedger(),
        [nextdoor],
        requested_by="Sabrina",
        now=NOW,
    )
    task = created[0]

    with pytest.raises(CampaignCadenceError, match="Management approval"):
        update_refresh_task(
            ledger,
            task_id=task.task_id,
            status=RefreshTaskStatus.CONFIRMED,
            actor="Posting Team",
            now=NOW,
        )

    approved = approve_refresh_task(
        ledger,
        property_record,
        task_id=task.task_id,
        approved_by="Sabrina",
        now=NOW,
    )
    confirmed = update_refresh_task(
        approved,
        task_id=task.task_id,
        status=RefreshTaskStatus.CONFIRMED,
        actor="Posting Team",
        notes="Verified live on Nextdoor.",
        now=NOW + timedelta(hours=1),
    )
    saved = next(item for item in confirmed.tasks if item.task_id == task.task_id)

    assert saved.status == RefreshTaskStatus.CONFIRMED
    assert saved.approved_by == "Sabrina"
    assert saved.completed_by == "Posting Team"


def test_property_change_blocks_stale_refresh_package_and_approval() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    email = next(item for item in queue if item.channel_key == "email")
    ledger, created = create_refresh_batch(
        CampaignCadenceLedger(),
        [email],
        requested_by="Sabrina",
        now=NOW,
    )
    stale_property = property_record.model_copy(
        update={"updated_at": property_record.updated_at + timedelta(minutes=1)}
    )

    with pytest.raises(CampaignCadenceError, match="property record changed"):
        approve_refresh_task(
            ledger,
            stale_property,
            task_id=created[0].task_id,
            approved_by="Sabrina",
            now=NOW,
        )

    with pytest.raises(CampaignCadenceError, match="property record changed"):
        build_refresh_materials(
            created[0],
            stale_property,
            "https://www.dwelyx.com/buyer/register",
        )


def test_manual_channels_stay_manual_and_marketplace_has_no_external_link() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    selected = [
        item
        for item in queue
        if item.channel_key in {"marketplace", "facebook_groups", "classifieds", "nextdoor"}
    ]
    _, tasks = create_refresh_batch(
        CampaignCadenceLedger(),
        selected,
        requested_by="Sabrina",
        now=NOW,
    )

    materials = {
        task.channel_key: build_refresh_materials(
            task,
            property_record,
            "https://www.dwelyx.com/buyer/register",
        )
        for task in tasks
    }

    assert all(item.requires_manual_final_post for item in materials.values())
    assert all(item.launch_action == LaunchAction.MANUAL_FINAL_POST for item in materials.values())
    assert "https://" not in materials["marketplace"].copy
    assert "dwelyx" not in materials["marketplace"].copy.lower()
    assert materials["facebook_groups"].tracked_link in materials["facebook_groups"].copy
    assert materials["nextdoor"].tracked_link in materials["nextdoor"].copy


def test_approved_automatic_refresh_payload_preserves_safety_controls() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    email = next(item for item in queue if item.channel_key == "email")
    ledger, created = create_refresh_batch(
        CampaignCadenceLedger(),
        [email],
        requested_by="Sabrina",
        now=NOW,
    )
    task = created[0]
    ledger = approve_refresh_task(
        ledger,
        property_record,
        task_id=task.task_id,
        approved_by="Sabrina",
        now=NOW,
    )
    task = next(item for item in ledger.tasks if item.task_id == task.task_id)
    materials = build_refresh_materials(
        task,
        property_record,
        "https://www.dwelyx.com/buyer/register",
    )
    payload = build_refresh_payload(
        task,
        property_record,
        materials,
        requested_by="Sabrina",
        now=NOW,
    )

    assert materials.launch_action == LaunchAction.AUTO_PUBLISH
    assert payload["channel"]["channel_key"] == "email"
    assert payload["channel"]["tracked_buyer_link"] == materials.tracked_link
    assert payload["buyer_destination"]["publish_property_to_dwelyx"] is False
    assert payload["buyer_destination"]["property_sync_to_dwelyx"] is False
    assert payload["controls"]["change_budget"] is False
    assert payload["controls"]["change_targeting"] is False
    assert payload["controls"]["mark_external_post_live_without_confirmation"] is False


def test_unapproved_automatic_refresh_payload_is_blocked() -> None:
    property_record = sample_property()
    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        now=NOW,
    )
    email = next(item for item in queue if item.channel_key == "email")
    _, created = create_refresh_batch(
        CampaignCadenceLedger(),
        [email],
        requested_by="Sabrina",
        now=NOW,
    )
    task = created[0]
    materials = build_refresh_materials(
        task,
        property_record,
        "https://www.dwelyx.com/buyer/register",
    )

    with pytest.raises(CampaignCadenceError, match="requires management approval"):
        build_refresh_payload(
            task,
            property_record,
            materials,
            requested_by="Sabrina",
            now=NOW,
        )


def test_snapshot_counts_current_and_open_work() -> None:
    property_record = sample_property()
    state = new_launch_state(property_record.property_id, "owner_finance_homes", now=NOW)
    for channel in CHANNELS:
        state = set_channel_status(
            state,
            channel.key,
            LaunchStatus.POSTED,
            updated_by="Sabrina",
            notes="Current placement.",
            now=NOW - timedelta(days=1),
        )
    clicks = [
        ClickEvent(
            occurred_at=NOW - timedelta(hours=1),
            source="credit_friendly_homes",
            medium=channel.key,
            campaign="owner_finance_homes",
            property_id=str(property_record.property_id),
        )
        for channel in CHANNELS
    ]

    queue = build_cadence_queue(
        [property_record],
        ledger=CampaignCadenceLedger(),
        launch_states={str(property_record.property_id): state},
        click_events=clicks,
        now=NOW,
    )
    snapshot = cadence_snapshot(queue, CampaignCadenceLedger())

    assert snapshot.total_active_lanes == 15
    assert snapshot.current == 15
    assert snapshot.coverage_rate == 1.0
    assert snapshot.open_tasks == 0


class FakeBucket:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def download(self, path: str):
        if path not in self.files:
            raise RuntimeError("missing")
        return self.files[path]

    def upload(self, *, path: str, file: bytes, file_options):
        self.files[path] = file


class FakeStorageApi:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.created = False
        self.bucket_options = None

    def get_bucket(self, name: str):
        if not self.created:
            raise RuntimeError("missing")
        return {"name": name}

    def create_bucket(self, name: str, options):
        self.created = True
        self.bucket_options = options
        return {"name": name}

    def from_(self, name: str):
        assert name == CADENCE_BUCKET
        return self.bucket


class FakeClient:
    def __init__(self) -> None:
        self.storage = FakeStorageApi()


def test_private_store_bootstraps_defaults_and_round_trips_tasks() -> None:
    client = FakeClient()
    store = CampaignCadenceStore(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "secret",
        },
        client=client,
    )

    empty = store.load()
    assert len(empty.policies) == 15

    property_record = sample_property()
    queue = build_cadence_queue([property_record], ledger=empty, now=NOW)
    email = next(item for item in queue if item.channel_key == "email")
    ledger, _ = create_refresh_batch(
        empty,
        [email],
        requested_by="Sabrina",
        now=NOW,
    )
    store.save(ledger)
    loaded = store.load()

    assert client.storage.created is True
    assert client.storage.bucket_options["public"] is False
    assert CADENCE_PATH in client.storage.bucket.files
    assert len(loaded.policies) == 15
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].channel_key == "email"


def test_dispatch_settings_remain_optional() -> None:
    settings = AutomationDispatchSettings.from_mapping({})
    assert settings.configured is False
