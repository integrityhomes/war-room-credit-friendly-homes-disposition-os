from cfh_disposition.external_app_integration import (
    IntegrationDisposition,
    active_integrations,
    deferred_integrations,
)


def test_current_external_apps_have_commandcore_targets() -> None:
    rows = active_integrations()
    repositories = {row.repository for row in rows}

    assert repositories == {
        "integrityhomes/agent-contact-finder",
        "integrityhomes/integrity-illinois-cfd-builder",
        "integrityhomes/war-room-offer-engine",
    }
    assert all(row.target_area in {"Leads & CRM", "Deals"} for row in rows)
    assert all(row.consume_from_deal for row in rows)
    assert all(row.write_back_to_deal for row in rows)


def test_war_room_os_is_deferred_not_retired() -> None:
    rows = deferred_integrations()

    assert len(rows) == 1
    assert rows[0].repository == "integrityhomes/war-room-os"
    assert rows[0].disposition == IntegrationDisposition.DEFERRED_REVIEW


def test_contract_and_offer_integrations_preserve_human_authority() -> None:
    boundaries = {
        row.repository: row.authority_boundary.lower()
        for row in active_integrations()
    }

    assert "signing" in boundaries["integrityhomes/integrity-illinois-cfd-builder"]
    assert "human approval" in boundaries["integrityhomes/war-room-offer-engine"]
