"""Synthetic identity continuity; no production clients, channels or records."""

import json
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.corepilot_conversation import answer
from cfh_disposition.dwelyx_attribution import DwelyxAttributionEvent
from cfh_disposition.marketing_attribution import UNKNOWN, bind, dwelyx_event, project, save, touch, tracked_click

WHEN = "2026-09-10T12:00:00+00:00"
REFS = {"property_id": {"source": "cfh_properties", "external_id": "legacy-property"},
        "contact_id": {"source": "cfh_buyers", "external_id": "legacy-buyer"}}


@pytest.fixture
def records():
    return {"properties": [{"id": "property-1", "source": "cfh_properties", "external_id": "legacy-property", "availability": "Available"}],
            "contacts": [{"id": "contact-1", "source": "cfh_buyers", "external_id": "legacy-buyer"}],
            "deals": [{"id": "deal-1", "links": {"property_id": "property-1", "contact_id": "contact-1"}}],
            "activities": [], "transactions": [], "communications": [], "tasks": []}


@pytest.fixture
def observations():
    return {"property-1": {"status": "available", "marketing_status": "yellow", "marketing_observed_since": "2026-09-01T00:00:00Z", "checked_at": WHEN}}


def receipt(records, observations=None, event_id="lead-1", medium="facebook_groups", **evidence):
    activity = touch("synthetic", event_id, {"occurred_at": WHEN, "source": "fictional", "medium": medium,
                                            "campaign": "fictional-campaign", "post_id": "post-1", "list_id": "list-1", **evidence},
                     references=REFS, records=records, observations=observations)
    records["activities"].append(activity)
    return activity


@pytest.mark.parametrize("medium,channel", [("facebook_groups", "facebook_groups"), ("google_search_ads", "google_ads"),
                                            ("facebook_marketplace", "marketplace"), ("chatgpt_ads", "chatgpt_ads")])
def test_supported_lead_to_existing_property_buyer_deal(records, observations, medium, channel):
    before = deepcopy(records)
    receipt(records, observations, medium=medium)
    row, = project(records, observations)
    assert (row["channel"], row["property_id"], row["contact_id"], row["deal_id"]) == (channel, "property-1", "contact-1", "deal-1")
    assert row["current_marketing"] and row["result"] == UNKNOWN
    assert all(records[k] == before[k] for k in records if k != "activities")
    assert (row["post_id"], row["list_id"], row["campaign"]) == ("post-1", "list-1", "fictional-campaign")


def test_existing_dwelyx_and_click_contracts_preserved(records, observations):
    event = DwelyxAttributionEvent(event_id="synthetic-event-1", event_type="home.filled", occurred_at=WHEN,
                                  dwelyx_buyer_id="dwelyx-buyer", cfh_property_id="legacy-property", medium="google", test_mode=True)
    activity = dwelyx_event(event, references={"contact_id": "contact-1"}, records=records, observations=observations)
    records["activities"].append(activity)
    click = ClickEvent(datetime.fromisoformat(WHEN), "dwelyx", "facebook_groups", "campaign", "legacy-property", "test")
    records["activities"].append(tracked_click(click, "clicks/existing-receipt.json", references={"contact_id": "contact-1"}, records=records))
    rows = project(records)
    assert rows[0]["original_evidence"] == event.model_dump(mode="json")
    assert rows[1]["original_evidence"] == click.to_payload()
    assert all(r["deal_id"] == "deal-1" and r["result"] == UNKNOWN for r in rows)


def test_delayed_binding_of_legacy_event_without_crosswalk(records, observations):
    records["contacts"][0]["source"] = "existing-crm"
    a = receipt(records, observations)
    original = deepcopy(a)
    assert project(records)[0]["contact_id"] == UNKNOWN
    link = bind(a, "verified-link-1", {"contact_id": "contact-1"}, records, observations=observations)
    records["activities"].append(link)
    assert project(records)[0]["deal_id"] == "deal-1"
    assert a == original


def test_anonymous_touch_then_canonical_communication_binding(records):
    a = touch("manual", "receipt", {"occurred_at": WHEN, "medium": "facebook_marketplace"})
    records["activities"].append(a)
    records["communications"].append({"id": "inquiry-1", "links": {"deal_id": "deal-1"}})
    records["activities"].append(bind(a, "binding", {"communication_id": "inquiry-1"}, records))
    assert project(records)[0]["contact_id"] == "contact-1"
    assert a["attribution"]["references"] == {}


def test_multitouch_keeps_repeat_buyer_and_property_channels(records):
    receipt(records, event_id="first", medium="facebook_groups")
    receipt(records, event_id="second", medium="google", campaign="second-campaign")
    rows = project(records)
    assert len(rows) == 2 and len({r["touch_id"] for r in rows}) == 2
    assert {r["channel"] for r in rows} == {"facebook_groups", "google_ads"}
    assert {r["contact_id"] for r in rows} == {"contact-1"}
    assert {r["property_id"] for r in rows} == {"property-1"}
    assert rows[0]["campaign"] == "fictional-campaign"


def fake_client(records, *, lost_ack=False):
    stored = {}

    class Bucket:
        def upload(self, path, data, file_options):
            assert path.startswith("activities/") and file_options["upsert"] == "false"
            if path in stored:
                raise RuntimeError("duplicate")
            stored[path] = data
            records["activities"].append(json.loads(data))
            if lost_ack:
                raise RuntimeError("response lost")

        def download(self, path):
            return stored[path]

    def bucket(name):
        assert name == "commandcore-crm-core"
        return Bucket()

    return SimpleNamespace(storage=SimpleNamespace(from_=bucket))


@pytest.mark.parametrize("lost_ack", [False, True])
def test_duplicate_create_only_survives_retry_and_uncertain_response(records, lost_ack):
    client = fake_client(records, lost_ack=lost_ack)
    a = touch("provider", "stable-receipt", {"occurred_at": WHEN}, references=REFS)
    save(client, a)
    assert save(client, deepcopy(a)) is False
    assert len(records["activities"]) == 1
    changed = touch("provider", "stable-receipt", {"occurred_at": WHEN, "campaign": "changed"}, references=REFS)
    with pytest.raises(RuntimeError):
        save(client, changed)
    assert len(records["contacts"]) == len(records["properties"]) == len(records["deals"]) == 1


def test_ambiguous_crosswalk_and_conflicting_links_fail_closed(records):
    receipt(records)
    records["contacts"].append({**records["contacts"][0], "id": "contact-2"})
    assert project(records)[0]["contact_id"] == UNKNOWN
    records["contacts"].pop()
    records["deals"][0]["property_id"] = "other"
    records["properties"].append({"id": "other"})
    # Explicit conflicting deal reference cannot be saved as an identity binding.
    with pytest.raises(ValueError):
        bind(records["activities"][0], "conflict", {"deal_id": "deal-1"}, records)


def test_competing_later_bindings_do_not_overwrite(records):
    a = touch("manual", "lead", {"occurred_at": WHEN})
    records["activities"].append(a)
    records["contacts"].append({"id": "contact-2"})
    records["activities"].extend([bind(a, "one", {"contact_id": "contact-1"}, records), bind(a, "two", {"contact_id": "contact-2"}, records)])
    assert project(records)[0]["contact_id"] == UNKNOWN
    assert len(records["activities"]) == 3


@pytest.mark.parametrize("status", ["Sold / Unavailable", "Pending", "Paused"])
def test_historical_or_noncurrent_property_never_current(records, observations, status):
    records["properties"][0]["availability"] = status
    receipt(records, observations)
    assert not project(records, observations)[0]["current_marketing"]


def test_returned_yellow_has_new_period_preserving_old_touch(records, observations):
    old = receipt(records, observations)
    old_period = old["attribution"]["marketing_period"]
    observations["property-1"].update(status="sold / unavailable", marketing_status="white", marketing_observed_since="")
    assert not project(records, observations)[0]["current_marketing"]
    observations["property-1"].update(status="available", marketing_status="yellow", marketing_observed_since="2026-09-11T00:00:00Z",
                                    checked_at="2026-09-12T00:00:00Z", historical_occurrences=(("SOLD", 8),))
    receipt(records, observations, "returned", occurred_at="2026-09-11T12:00:00Z")
    rows = project(records, observations)
    assert rows[0]["marketing_period"] == old_period and not rows[0]["current_marketing"]
    assert rows[1]["marketing_period"] not in {old_period, UNKNOWN} and rows[1]["current_marketing"]
    assert observations["property-1"]["historical_occurrences"] == (("SOLD", 8),)


def closing(**changes):
    return {"id": "closing-1", "transaction_type": "closing", "status": "closed", "closing_verified": True,
            "ownership_or_control_confirmed": True, "closed_at": "2026-09-11T14:00:00Z", "links": {"deal_id": "deal-1"}, **changes}


@pytest.mark.parametrize("change", [{"closing_verified": False}, {"ownership_or_control_confirmed": False}, {"closed_at": "invalid"},
                                   {"closed_at": "2026-09-09T00:00:00Z"}, {"status": "pending"}, {"transaction_type": "acquisition_closing"},
                                   {"links": {}}, {"archived": True}])
def test_closing_requires_verified_buyer_deal_evidence(records, change):
    receipt(records, event_type="home.filled", status="sold")
    records["deals"][0]["status"] = "closed"
    records["transactions"].append(closing(**change))
    assert project(records)[0]["result"] == UNKNOWN


def test_verified_closing_preserves_all_touches_and_counts_unique_closing(records):
    receipt(records, event_id="one")
    receipt(records, event_id="two", medium="google")
    records["transactions"].append(closing())
    assert all(r["result"] == "VERIFIED_CLOSING" for r in project(records))
    response = answer("Show marketing attribution", records)
    assert "Verified buyer closings: 1" in response.what_i_found
    assert response.records_written == response.external_actions_started == 0


@pytest.mark.parametrize("medium", ["", "facebook", "unknown", "unrecognized"])
def test_unknown_stays_unknown(records, medium):
    receipt(records, medium=medium)
    assert project(records)[0]["channel"] == UNKNOWN


def test_property_only_does_not_infer_buyer_or_deal(records):
    records["activities"].append(touch("source", "event", {"occurred_at": WHEN}, references={"property_id": "property-1"}))
    row, = project(records)
    assert row["property_id"] == "property-1" and row["contact_id"] == row["deal_id"] == UNKNOWN


def test_missing_id_or_timezone_rejected():
    for namespace, event_id, when in [("", "id", WHEN), ("source", "", WHEN), ("source", "id", "2026-09-10")]:
        with pytest.raises(ValueError):
            touch(namespace, event_id, {"occurred_at": when})


def test_real_inventory_observer_drives_period_restart():
    from test_corepilot_inventory import source_row
    from test_property_sync_preview import property_record

    from cfh_disposition.corepilot_inventory import observe_inventory
    prop = property_record()
    records = {"properties": [prop], "activities": []}
    first = observe_inventory([source_row()], [prop], checked_at=WHEN)
    records["activities"].append(touch("manual", "first", {"occurred_at": WHEN}, references={"property_id": prop["id"]}, records=records, observations=first))
    sold = observe_inventory([source_row(availability="Sold / Unavailable")], [prop], first, checked_at="2026-09-11T00:00:00Z")
    assert not project(records, sold)[0]["current_marketing"]
    later = "2026-09-12T00:00:00Z"
    returned = observe_inventory([source_row()], [prop], sold, checked_at=later)
    records["activities"].append(touch("manual", "returned", {"occurred_at": later}, references={"property_id": prop["id"]}, records=records, observations=returned))
    rows = project(records, returned)
    assert not rows[0]["current_marketing"] and rows[1]["current_marketing"]
    assert rows[0]["marketing_period"] != rows[1]["marketing_period"]


def test_distinct_upstream_sources_and_binding_duplicates(records):
    client = fake_client(records)
    for namespace in ("first-source", "second-source"):
        save(client, touch(namespace, "same-id", {"occurred_at": WHEN}))
    a = records["activities"][0]
    link = bind(a, "link-receipt", {"deal_id": "deal-1"}, records)
    assert save(client, link) and not save(client, link)
    assert len(records["activities"]) == 3


def test_multiple_deals_do_not_guess_result(records):
    receipt(records)
    records["deals"].append({**records["deals"][0], "id": "deal-2"})
    records["transactions"].append(closing())
    assert project(records)[0]["deal_id"] == UNKNOWN
    with pytest.raises(ValueError):
        bind(records["activities"][0], "missing", {"contact_id": "absent"}, records)


def test_canonical_task_links_and_archived_records(records):
    records["tasks"].append({"id": "task-1", "links": {"deal_id": "deal-1"}})
    a = touch("manual", "receipt", {"occurred_at": WHEN}, references={"task_id": "task-1"})
    records["activities"].append(a)
    assert project(records)[0]["contact_id"] == "contact-1"
    records["contacts"][0]["archived"] = True
    assert project(records)[0]["contact_id"] == UNKNOWN
