from datetime import UTC, datetime

from cfh_disposition.operational_failures import (
    CriticalFailureType,
    FailureStatus,
    OperationalFailure,
    OperationalFailureLedger,
    append_failure,
    close_failure,
    open_failures,
)


def _failure() -> OperationalFailure:
    return OperationalFailure(
        failure_type=CriticalFailureType.FACEBOOK_TASK,
        summary="Facebook post could not be confirmed.",
        property_id="property-1",
        channel="facebook_groups",
        campaign="owner_finance_homes",
        occurrence_key="facebook task|property-1|facebook_groups|owner_finance_homes|",
        occurred_at=datetime(2026, 8, 22, 20, 0, tzinfo=UTC),
    )


def test_repeated_open_failure_is_counted_instead_of_hidden():
    ledger = append_failure(OperationalFailureLedger(), _failure())
    repeated = _failure().model_copy(
        update={"occurred_at": datetime(2026, 8, 22, 21, 0, tzinfo=UTC)}
    )
    updated = append_failure(ledger, repeated)
    assert len(updated.failures) == 1
    assert updated.failures[0].repeat_count == 2


def test_closed_failure_keeps_learning_fields():
    ledger = append_failure(OperationalFailureLedger(), _failure())
    failure_id = ledger.failures[0].failure_id
    updated = close_failure(
        ledger,
        failure_id=failure_id,
        actor="Sabrina",
        root_cause="Facebook group URL was stale.",
        resolution="Updated the saved group URL and posted manually.",
        prevention_note="Validate group URLs during weekly directory review.",
    )
    closed = updated.failures[0]
    assert closed.status == FailureStatus.RESOLVED
    assert closed.resolved_by == "Sabrina"
    assert "weekly" in closed.prevention_note
    assert open_failures(updated) == []


def test_manual_override_is_distinct_from_verified_fix():
    ledger = append_failure(OperationalFailureLedger(), _failure())
    failure_id = ledger.failures[0].failure_id
    updated = close_failure(
        ledger,
        failure_id=failure_id,
        actor="VA",
        root_cause="Unknown",
        resolution="Posted manually while automation was unavailable.",
        prevention_note="Review automation connection.",
        manual_override=True,
    )
    assert updated.failures[0].status == FailureStatus.MANUAL_OVERRIDE
