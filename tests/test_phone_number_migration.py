from datetime import date

import pytest
from pydantic import ValidationError

from cfh_disposition.phone_number_migration import (
    CancellationSafetyStatus,
    PhoneNumberMigrationInventory,
    PhoneNumberMigrationRecord,
    PortStatus,
)
from cfh_disposition.phone_number_migration import TestStatus as MigrationTestStatus


def sample_record(**overrides: object) -> PhoneNumberMigrationRecord:
    values: dict[str, object] = {
        "phone_number": "(555) 010-1200",
        "current_provider": "Example Phone Provider",
        "business_purpose": "Fictional seller inquiry line",
        "assigned_team_or_person": "Acquisitions team",
        "market_or_campaign": "Example County",
    }
    values.update(overrides)
    return PhoneNumberMigrationRecord(**values)


def test_inventory_tracks_only_safe_migration_metadata() -> None:
    record = sample_record()
    assert record.phone_number == "+15550101200"
    assert record.port_status == PortStatus.NOT_PLANNED
    assert record.test_call_status == MigrationTestStatus.NOT_TESTED
    assert record.test_sms_status == MigrationTestStatus.NOT_TESTED
    assert record.old_provider_cancellation_safety_status == CancellationSafetyStatus.KEEP_ACTIVE
    inventory = PhoneNumberMigrationInventory(records=[record])
    assert inventory.live_porting_authorized is False
    assert inventory.external_action_started is False


@pytest.mark.parametrize("secret_field", ["carrier_pin", "password", "api_key", "access_token", "oauth_secret"])
def test_inventory_rejects_credentials(secret_field: str) -> None:
    with pytest.raises(ValidationError):
        sample_record(**{secret_field: "do-not-store"})


def test_inventory_cannot_authorize_or_start_porting() -> None:
    with pytest.raises(ValidationError, match="cannot authorize or start"):
        PhoneNumberMigrationInventory(live_porting_authorized=True)
    with pytest.raises(ValidationError, match="cannot authorize or start"):
        PhoneNumberMigrationInventory(external_action_started=True)


def test_completed_port_requires_ordered_dates() -> None:
    with pytest.raises(ValidationError, match="requested date"):
        sample_record(port_status=PortStatus.COMPLETED, completed_date=date(2026, 9, 4))
    with pytest.raises(ValidationError, match="cannot be before"):
        sample_record(requested_date=date(2026, 9, 5), completed_date=date(2026, 9, 4))
    completed = sample_record(
        port_status=PortStatus.COMPLETED,
        requested_date=date(2026, 9, 1),
        completed_date=date(2026, 9, 4),
    )
    assert completed.completed_date == date(2026, 9, 4)
