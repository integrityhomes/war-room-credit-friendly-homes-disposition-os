from cfh_disposition.commandcore_agent_finder_ui import _linked_property_context


def test_agent_finder_prefills_linked_property_context() -> None:
    deals = [
        {
            "id": "deal-1",
            "listing_url": "https://example.com/listing",
            "links": {"contact_id": "contact-1", "property_id": "property-1"},
        }
    ]
    properties = [
        {
            "id": "property-1",
            "address": "123 Main St",
            "city": "Decatur",
            "state": "Illinois",
        }
    ]

    assert _linked_property_context("contact-1", deals, properties) == (
        "123 Main St",
        "Decatur",
        "Illinois",
        "https://example.com/listing",
    )


def test_agent_finder_context_is_empty_when_contact_is_not_linked() -> None:
    assert _linked_property_context("missing", [], []) == ("", "", "", "")
