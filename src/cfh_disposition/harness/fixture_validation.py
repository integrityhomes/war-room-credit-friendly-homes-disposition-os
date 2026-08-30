from __future__ import annotations

from typing import Any

from .fixtures import FIXTURE_SOURCE

_RECORD_KEYS = (
    "contact",
    "property",
    "deal",
    "offer",
    "contract_draft",
    "task",
    "communication",
    "approval",
)


def validate_fixture_family(fixture: dict[str, Any]) -> None:
    """Fail closed if canonical harness data could be mistaken for live data."""
    for key in _RECORD_KEYS:
        record = fixture[key]
        if record.get("internal_only") is not True:
            raise ValueError(f"Fixture {key} must be internal_only.")
        if record.get("fixture_source") != FIXTURE_SOURCE:
            raise ValueError(f"Fixture {key} must preserve harness provenance.")
        if not str(record.get("id", "")).startswith("FIXTURE-"):
            raise ValueError(f"Fixture {key} must use an obviously fake stable ID.")

    contact = fixture["contact"]
    if not str(contact.get("email", "")).endswith(".invalid"):
        raise ValueError("Fixture contact email must use the reserved .invalid domain.")
    if not str(contact.get("phone", "")).startswith("+1555"):
        raise ValueError("Fixture contact phone must use the obvious +1555 fake range.")

    property_record = fixture["property"]
    if "TEST" not in str(property_record.get("address", "")).upper():
        raise ValueError("Fixture property address must be visibly marked TEST.")
    if not str(property_record.get("parcel_number", "")).startswith("FIXTURE-"):
        raise ValueError("Fixture parcel number must be visibly fake.")

    deal = fixture["deal"]
    if deal.get("external_action_started") is not False:
        raise ValueError("Fixture Deal must default external_action_started to false.")
    if deal.get("links", {}).get("contact_id") != contact["id"]:
        raise ValueError("Fixture Deal contact link is inconsistent.")
    if deal.get("links", {}).get("property_id") != property_record["id"]:
        raise ValueError("Fixture Deal property link is inconsistent.")

    contract = fixture["contract_draft"]
    if not str(contract.get("storage_object_path", "")).startswith("fixtures/"):
        raise ValueError("Fixture contract storage must remain under fixtures/.")
    if contract.get("signing_started") is not False:
        raise ValueError("Fixture contract must remain unsigned.")

    for key in ("offer", "contract_draft", "task", "communication", "approval"):
        if fixture[key].get("deal_id") != deal["id"]:
            raise ValueError(f"Fixture {key} must link to the canonical fixture Deal.")
