import pytest

from cfh_disposition.agent_contact_finder import (
    AgentFinderError,
    AgentLookupRequest,
    build_agent_search_queries,
    normalize_agent_result,
)


def test_lookup_requires_name_city_and_state() -> None:
    with pytest.raises(AgentFinderError):
        build_agent_search_queries(AgentLookupRequest(agent_name="", city="Decatur", state="Illinois"))


def test_queries_use_property_brokerage_and_public_agent_sources() -> None:
    queries = build_agent_search_queries(
        AgentLookupRequest(
            agent_name="Jane Agent",
            brokerage="Example Realty",
            city="Decatur",
            state="Illinois",
            property_address="123 Main St",
        )
    )

    joined = "\n".join(queries)
    assert '"123 Main St" "Jane Agent" realtor' in joined
    assert '"Jane Agent" "Example Realty" phone email' in joined
    assert 'site:realtor.com "Jane Agent" "Decatur, Illinois"' in joined
    assert 'site:linkedin.com/in "Jane Agent" real estate' in joined


def test_result_prefers_trusted_sources_and_dedupes_links() -> None:
    result = normalize_agent_result(
        {
            "agent_name": "Jane Agent",
            "best_phone": "(217) 555-1212",
            "best_email": "jane@example.com",
            "confidence_score": 62,
            "source_links": [
                "https://www.realtor.com/realestateagents/jane",
                "https://www.realtor.com/realestateagents/jane/",
            ],
        }
    )

    assert result.confidence_score == 77
    assert result.status == "Strong match"
    assert len(result.source_links) == 1
    assert "Verify" in result.next_action


def test_low_confidence_result_never_implies_verified_contact() -> None:
    result = normalize_agent_result(
        {
            "agent_name": "Jane Agent",
            "confidence_score": 20,
            "source_links": ["https://rocketreach.co/example"],
        }
    )

    assert result.status == "Needs verification"
    assert result.confidence_score == 0
