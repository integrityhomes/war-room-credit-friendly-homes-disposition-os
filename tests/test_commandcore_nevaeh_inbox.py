from cfh_disposition.commandcore_nevaeh_inbox import (
    NevaehInboxCategory,
    NevaehInboxItem,
    build_nevaeh_inbox,
    inbox_category_counts,
)

CONTACTS = ({"id": "contact-1", "name": "Known Seller", "phone": "2175550100", "relationship": "Seller"},)
PROPERTIES = ({"id": "property-1", "address": "100 Example Street"},)
DEALS = (
    {
        "id": "deal-1",
        "title": "100 Example Street",
        "assigned_to": "Alex Morgan",
        "status": "active",
        "links": {"contact_id": "contact-1", "property_id": "property-1"},
    },
)


def communication(identifier: str, message: str, **values: object) -> dict[str, object]:
    return {
        "id": identifier,
        "direction": "inbound",
        "channel": "sms",
        "message_text": message,
        "received_at": "2026-09-04T12:00:00Z",
        **values,
    }


def test_known_deal_scheduling_message_is_safe_and_assigned() -> None:
    items = build_nevaeh_inbox(
        [communication("message-1", "Can we schedule a showing?", contact_phone="2175550100")],
        contacts=CONTACTS,
        properties=PROPERTIES,
        deals=DEALS,
    )
    item = items[0]
    assert item.person == "Known Seller"
    assert item.related_deal == "100 Example Street"
    assert item.assigned_worker == "Alex Morgan"
    assert item.classification == "Appointment or scheduling request"
    assert NevaehInboxCategory.MATCHED_TO_DEAL in item.categories
    assert item.records_written == item.tasks_created == item.external_actions_started == 0


def test_unknown_and_ambiguous_contacts_need_review_without_guessing() -> None:
    duplicate_contacts = (*CONTACTS, {**CONTACTS[0], "id": "contact-2"})
    items = build_nevaeh_inbox(
        [
            communication("unknown", "Hello", contact_phone="2175550199"),
            communication("ambiguous", "Hello", contact_phone="2175550100"),
        ],
        contacts=duplicate_contacts,
        properties=PROPERTIES,
        deals=DEALS,
    )
    assert len(items) == 2
    assert all(NevaehInboxCategory.NEEDS_REVIEW in item.categories for item in items)
    assert all(NevaehInboxCategory.UNASSIGNED in item.categories for item in items)


def test_stop_money_and_legal_messages_receive_visible_priority_categories() -> None:
    items = build_nevaeh_inbox(
        [
            communication("stop", "STOP", contact_phone="2175550100"),
            communication("money", "I need to change the bank payment", contact_phone="2175550100"),
            communication("legal", "My attorney says this is a legal issue", contact_phone="2175550100"),
        ],
        contacts=CONTACTS,
        properties=PROPERTIES,
        deals=DEALS,
    )
    by_id = {item.communication_id: item for item in items}
    assert NevaehInboxCategory.STOP_CONSENT in by_id["stop"].categories
    assert NevaehInboxCategory.MONEY_LEGAL in by_id["money"].categories
    assert NevaehInboxCategory.MONEY_LEGAL in by_id["legal"].categories
    assert all(NevaehInboxCategory.HIGH_PRIORITY in item.categories for item in items)
    assert all(item.approval_required for item in items)


def test_email_facebook_and_sms_are_supported_without_showing_message_body() -> None:
    items = build_nevaeh_inbox(
        [
            communication("email-1", "Can we schedule?", channel="email"),
            communication("facebook-1", "I saw your Facebook listing", channel="facebook"),
            communication("sms-1", "Checking in", channel="sms"),
        ],
        contacts=(),
        properties=(),
        deals=(),
    )
    assert {item.channel for item in items} == {"Email", "Facebook", "SMS"}
    assert "message_text" not in NevaehInboxItem.model_fields


def test_outbound_records_are_excluded_and_counts_are_deterministic() -> None:
    inbound = communication("inbound", "STOP")
    outbound = communication("outbound", "Sent message", direction="outbound")
    items = build_nevaeh_inbox([outbound, inbound], contacts=(), properties=(), deals=())
    assert [item.communication_id for item in items] == ["inbound"]
    counts = inbox_category_counts(items)
    assert counts["New communications"] == 1
    assert counts["STOP / Consent"] == 1


def test_malformed_record_is_skipped_safely() -> None:
    assert build_nevaeh_inbox([{"direction": "inbound"}], contacts=(), properties=(), deals=()) == ()
