from datetime import UTC, datetime
from decimal import Decimal

import cfh_disposition.automatic_launch as automatic_launch
from cfh_disposition.ai_campaign import build_fallback_campaign
from cfh_disposition.automatic_launch import (
    AUTOMATION_EVENT,
    AutomationDispatchSettings,
    LaunchAction,
    automation_plan_rows,
    build_automatic_launch_payload,
    channel_copy_with_link,
    dispatch_automatic_launch,
    launch_action_for_channel,
    serialize_launch_payload,
    sign_launch_payload,
)
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS, CHANNELS_BY_KEY
from cfh_disposition.dwelyx import DEFAULT_DWELYX_URL
from cfh_disposition.models import OwnerFinanceProperty


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="101 Test Street",
        city="Bristol",
        state="VA",
        zip_code="24201",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("100000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="New flooring and working utilities were reported.",
        repairs_needed="Buyer should verify all property condition details.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms and availability are subject to verification.",
        photo_urls=["https://example.com/front.jpg"],
    )


def launch_fixture():
    item = sample_property()
    links = build_channel_links(
        DEFAULT_DWELYX_URL,
        campaign="August Bristol",
        property_id=item.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    links_by_key = {row["Channel key"]: row for row in links}
    package = build_fallback_campaign(
        item,
        links_by_key["property_page"]["Tracked Dwelyx link"],
    )
    return item, links_by_key, package


def test_automatic_launch_payload_contains_all_channels_and_never_syncs_dwelyx() -> None:
    item, links_by_key, package = launch_fixture()
    approved_at = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)

    payload = build_automatic_launch_payload(
        item,
        package,
        links_by_key,
        campaign="august_bristol",
        approved_by="Sabrina",
        approved_at=approved_at,
    )

    assert payload["event"] == AUTOMATION_EVENT
    assert payload["buyer_destination"]["publish_property_to_dwelyx"] is False
    assert payload["buyer_destination"]["property_sync_to_dwelyx"] is False
    assert payload["buyer_destination"]["facebook_marketplace_direct_link"] is False
    assert payload["buyer_destination"]["facebook_groups_direct_link"] is True
    assert len(payload["channels"]) == len(CHANNELS) == 14
    assert payload["property"]["address"] == "101 Test Street"
    assert payload["property"]["photo_urls"] == ["https://example.com/front.jpg"]

    rows = {row["channel_key"]: row for row in payload["channels"]}
    marketplace = rows["marketplace"]
    assert marketplace["tracked_buyer_link"] is None
    assert marketplace["public_external_link_allowed"] is False
    assert "https://" not in marketplace["copy"]
    assert "dwelyx" not in marketplace["copy"].lower()
    assert "facebook marketplace message" in marketplace["copy"].lower()

    groups = rows["facebook_groups"]
    assert "tracking.example.com" in groups["tracked_buyer_link"]
    assert groups["public_external_link_allowed"] is True
    assert "tracking.example.com" in groups["copy"]

    for key, row in rows.items():
        if key != "marketplace":
            assert "tracking.example.com" in row["tracked_buyer_link"]
            assert row["public_external_link_allowed"] is True


def test_marketplace_sanitizer_removes_existing_urls_but_groups_keep_tracked_link() -> None:
    _, links_by_key, package = launch_fixture()
    dirty = package.model_copy(
        update={
            "marketplace_description": (
                f"{package.marketplace_description}\nVisit Dwelyx here: https://example.com/register"
            ),
            "facebook_group_post": (
                f"{package.facebook_group_post}\nOld link: https://example.com/register"
            ),
        }
    )

    marketplace_copy = channel_copy_with_link(
        dirty,
        "marketplace",
        links_by_key["marketplace"]["Tracked Dwelyx link"],
    )
    group_copy = channel_copy_with_link(
        dirty,
        "facebook_groups",
        links_by_key["facebook_groups"]["Tracked Dwelyx link"],
    )

    assert "https://" not in marketplace_copy
    assert "dwelyx" not in marketplace_copy.lower()
    assert "facebook marketplace message" in marketplace_copy.lower()
    assert "tracking.example.com" in group_copy
    assert "example.com/register" not in group_copy


def test_marketplace_monthly_block_removes_copy_from_automation_payload() -> None:
    item, links_by_key, package = launch_fixture()
    payload = build_automatic_launch_payload(
        item,
        package,
        links_by_key,
        campaign="august_bristol",
        approved_by="Sabrina",
        marketplace_blocked=True,
        marketplace_block_reason="Five of five listings used until September 1.",
    )
    rows = {row["channel_key"]: row for row in payload["channels"]}
    marketplace = rows["marketplace"]
    assert marketplace["posting_blocked"] is True
    assert marketplace["copy"] == ""
    assert "Five of five" in marketplace["block_reason"]
    assert rows["facebook_groups"]["posting_blocked"] is False
    assert "tracking.example.com" in rows["facebook_groups"]["copy"]


def test_launch_actions_keep_restricted_platforms_manual() -> None:
    assert launch_action_for_channel(CHANNELS_BY_KEY["property_page"]) == LaunchAction.INTERNAL_LIVE
    assert launch_action_for_channel(CHANNELS_BY_KEY["email"]) == LaunchAction.AUTO_PUBLISH
    assert launch_action_for_channel(CHANNELS_BY_KEY["marketplace"]) == LaunchAction.MANUAL_FINAL_POST
    assert launch_action_for_channel(CHANNELS_BY_KEY["facebook_groups"]) == LaunchAction.MANUAL_FINAL_POST
    assert launch_action_for_channel(CHANNELS_BY_KEY["classifieds"]) == LaunchAction.MANUAL_FINAL_POST
    assert len(automation_plan_rows()) == 14


def test_settings_accept_make_aliases_and_require_a_real_url() -> None:
    configured = AutomationDispatchSettings.from_mapping(
        {
            "MAKE_WEBHOOK_URL": "https://hook.example.com/campaign",
            "MAKE_WEBHOOK_SECRET": "secret",
        }
    )
    assert configured.configured
    assert configured.signing_secret == "secret"
    assert not AutomationDispatchSettings.from_mapping({}).configured


def test_payload_signature_is_stable() -> None:
    body = serialize_launch_payload({"event": "test", "value": 1})
    assert sign_launch_payload(body, "secret") == sign_launch_payload(body, "secret")
    assert sign_launch_payload(body, "") == ""
    assert sign_launch_payload(body, "secret").startswith("sha256=")


def test_dispatch_posts_signed_json(monkeypatch) -> None:
    requests = []

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"accepted":true}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(automatic_launch, "urlopen", fake_urlopen)
    settings = AutomationDispatchSettings(
        webhook_url="https://hook.example.com/campaign",
        signing_secret="secret",
        timeout_seconds=5,
    )

    receipt = dispatch_automatic_launch({"event": AUTOMATION_EVENT}, settings)

    assert receipt.status_code == 202
    assert len(requests) == 1
    request, timeout = requests[0]
    assert timeout == 5
    assert request.method == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert request.headers["X-cfh-event"] == AUTOMATION_EVENT
    assert request.headers["X-cfh-signature"].startswith("sha256=")
