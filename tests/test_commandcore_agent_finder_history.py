from cfh_disposition.commandcore_agent_finder_ui import _linked_property_context, _research_activity


def test_agent_finder_uses_linked_deal_context_and_writes_safe_history() -> None:
    deal_id, address, city, state, listing_url = _linked_property_context(
        "contact-1",
        [
            {
                "id": "deal-9",
                "links": {"contact_id": "contact-1", "property_id": "property-2"},
            }
        ],
        [
            {
                "id": "property-2",
                "address": "123 Main St",
                "city": "Decatur",
                "state": "IL",
                "zillow_url": "https://example.com/listing",
            }
        ],
    )

    assert deal_id == "deal-9"
    assert (address, city, state) == ("123 Main St", "Decatur", "IL")
    assert listing_url == "https://example.com/listing"

    activity = _research_activity(
        deal_id=deal_id,
        contact_id="contact-1",
        contact_name="Alex Agent",
        status="Strong match",
        confidence_score=88,
        source_links=("https://example.com/agent",),
        phone_saved=True,
        email_saved=False,
    )

    assert activity["activity_type"] == "agent_contact_research_saved"
    assert activity["links"] == {"deal_id": "deal-9", "contact_id": "contact-1"}
    assert activity["details"]["confidence_score"] == 88
    assert activity["details"]["source_count"] == 1
    assert activity["details"]["requires_verification_before_outreach"] is True
    assert "phone" in activity["summary"]
