from cfh_disposition.commandcore_closing_controls import verified_closing


def valid_closing() -> dict:
    return {
        "status": "closed",
        "transaction_type": "acquisition_closing",
        "closing_verified": True,
        "ownership_or_control_confirmed": True,
        "closed_at": "2026-08-29T15:30:00Z",
    }


def test_verified_closing_requires_all_evidence() -> None:
    assert verified_closing(valid_closing()) is True


def test_owner_control_confirmation_is_required() -> None:
    record = valid_closing()
    record["ownership_or_control_confirmed"] = False
    assert verified_closing(record) is False


def test_open_closing_does_not_release_dispo() -> None:
    record = valid_closing()
    record["status"] = "open"
    assert verified_closing(record) is False
