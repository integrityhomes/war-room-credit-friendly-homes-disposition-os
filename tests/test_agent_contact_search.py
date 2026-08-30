import pytest
import requests

from cfh_disposition.agent_contact_finder import AgentFinderError, AgentLookupRequest
from cfh_disposition.agent_contact_search import search_agent_contacts


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_search_agent_contacts_returns_ranked_public_contact() -> None:
    def transport(url, *, params, timeout):
        assert "searchapi.io" in url
        assert timeout == 30
        assert params["api_key"] == "secret-key"
        return FakeResponse(
            200,
            {
                "organic_results": [
                    {
                        "title": "Jane Agent - Example Realty",
                        "snippet": "Jane Agent Decatur Illinois 217-555-1212 jane.agent@example-realty.com",
                        "link": "https://www.realtor.com/realestateagents/jane-agent",
                    }
                ]
            },
        )

    result = search_agent_contacts(
        AgentLookupRequest(
            agent_name="Jane Agent",
            brokerage="Example Realty",
            city="Decatur",
            state="Illinois",
        ),
        api_key="secret-key",
        transport=transport,
    )

    assert result.phone == "(217) 555-1212"
    assert result.email == "jane.agent@example-realty.com"
    assert result.status == "Strong match"


def test_missing_searchapi_connection_fails_with_plain_english_message() -> None:
    with pytest.raises(AgentFinderError, match="not connected"):
        search_agent_contacts(
            AgentLookupRequest(agent_name="Jane Agent", city="Decatur", state="Illinois"),
            api_key="",
        )


def test_provider_connection_error_is_not_exposed_as_raw_exception() -> None:
    def transport(*args, **kwargs):
        raise requests.RequestException("sensitive transport details")

    with pytest.raises(AgentFinderError, match="could not reach"):
        search_agent_contacts(
            AgentLookupRequest(agent_name="Jane Agent", city="Decatur", state="Illinois"),
            api_key="secret-key",
            transport=transport,
        )
