from cfh_disposition.go_live_connections import build_connection_status


def _agent_finder_row(values):
    return next(row for row in build_connection_status(values) if row.key == "agent_finder")


def test_agent_finder_connection_is_missing_without_searchapi_key() -> None:
    row = _agent_finder_row({})
    assert row.configured is False
    assert row.status_label == "Needs connection"
    assert row.name == "Agent Contact Finder"


def test_agent_finder_connection_is_present_without_granting_outreach_authority() -> None:
    row = _agent_finder_row({"SEARCHAPI_API_KEY": "configured-secret"})
    assert row.configured is True
    assert row.status_label == "Connected"
    assert "verification before outreach" in row.next_step
