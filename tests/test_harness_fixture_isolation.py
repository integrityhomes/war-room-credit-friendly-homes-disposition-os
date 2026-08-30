from __future__ import annotations

import pytest

from cfh_disposition.harness.fixture_validation import validate_fixture_family
from cfh_disposition.harness.fixtures import load_fixture_family


def test_canonical_fixture_family_is_visibly_fake_and_isolated() -> None:
    fixture = load_fixture_family()

    validate_fixture_family(fixture)

    assert fixture["contact"]["email"].endswith(".invalid")
    assert fixture["deal"]["external_action_started"] is False
    assert fixture["contract_draft"]["storage_object_path"].startswith("fixtures/")


@pytest.mark.parametrize(
    ("record", "field", "unsafe_value"),
    (
        ("contact", "email", "real-person@example.com"),
        ("deal", "external_action_started", True),
        ("contract_draft", "storage_object_path", "deals/live/generated_contract/v1/contract.docx"),
        ("approval", "internal_only", False),
    ),
)
def test_fixture_validation_fails_closed_on_live_like_mutations(
    record: str,
    field: str,
    unsafe_value: object,
) -> None:
    fixture = load_fixture_family()
    fixture[record][field] = unsafe_value

    with pytest.raises(ValueError):
        validate_fixture_family(fixture)
