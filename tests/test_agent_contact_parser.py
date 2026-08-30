from cfh_disposition.agent_contact_parser import (
    best_contact_values,
    extract_contact_candidates,
    relevance_score,
)


def test_relevance_rewards_named_trusted_agent_source() -> None:
    result = {
        "title": "Jane Agent - Realtor in Decatur Illinois",
        "snippet": "Jane Agent with Example Realty. Call 217-555-1212.",
        "link": "https://www.realtor.com/realestateagents/jane-agent",
    }
    assert (
        relevance_score(
            result,
            agent_name="Jane Agent",
            brokerage="Example Realty",
            city="Decatur",
            state="Illinois",
        )
        >= 100
    )


def test_parser_prefers_relevant_public_phone_and_email() -> None:
    results = [
        {
            "title": "Jane Agent - Example Realty",
            "snippet": "Jane Agent 217-555-1212 jane.agent@example-realty.com Decatur Illinois",
            "link": "https://example-realty.com/jane-agent",
        },
        {
            "title": "Data broker",
            "snippet": "Jane Agent 999-555-0000",
            "link": "https://rocketreach.co/jane",
        },
    ]
    candidates = extract_contact_candidates(
        results,
        agent_name="Jane Agent",
        brokerage="Example Realty",
        city="Decatur",
        state="Illinois",
    )
    best = best_contact_values(candidates)

    assert best["phone"] == "(217) 555-1212"
    assert best["email"] == "jane.agent@example-realty.com"


def test_parser_rejects_unrelated_generic_email() -> None:
    candidates = extract_contact_candidates(
        [
            {
                "title": "Jane Agent",
                "snippet": "Contact info@example.com for details",
                "link": "https://example.org/jane",
            }
        ],
        agent_name="Jane Agent",
        brokerage="Example Realty",
        city="Decatur",
        state="Illinois",
    )

    assert all(candidate.kind != "email" for candidate in candidates)
