"""Synthetic conservative address equivalence and evidence-assisted parsing."""

import pytest

from cfh_disposition.property_sync_preview import address_key, verified_address_parts


@pytest.mark.parametrize("short,long", [("W Oak Ave", "West Oak Avenue"), ("E Oak St", "East Oak Street"), ("N Oak Rd", "North Oak Road"), ("S Oak Dr", "South Oak Drive")])
def test_equivalent_complete_addresses(short, long):
    assert address_key({"address": f"42 {short}, Sampleton, IL 62001"}) == address_key({"address": f"42 {long}, Sampleton, Illinois 62001"})


@pytest.mark.parametrize(
    "other",
    [
        "43 W Oak Ave, Sampleton, IL 62001",
        "42 E Oak Ave, Sampleton, IL 62001",
        "42 W Oak Rd, Sampleton, IL 62001",
        "42 W Oak Ave, Elsewhere, IL 62001",
        "42 W Oak Ave, Sampleton, IL 62002",
        "42 W Oak Ave Apt 2, Sampleton, IL 62001",
    ],
)
def test_distinct_properties_not_merged(other):
    assert address_key({"address": other}) != address_key({"address": "42 W Oak Ave, Sampleton, IL 62001"})


def test_suffixless_address_requires_unique_complete_evidence():
    source = "42 W Oak Sampleton IL 62001"
    candidate = {"address": "42 West Oak Avenue", "city": "Sampleton", "state": "IL", "zip": "62001"}
    assert verified_address_parts(source, [candidate])["city"] == "Sampleton"
    assert not all(verified_address_parts(source, []).values())
    assert not all(verified_address_parts(source, [candidate, candidate]).values())
    assert not all(verified_address_parts(source, [candidate, {**candidate, "address": "42 West Oak Road"}]).values())
    assert not all(verified_address_parts(source, [{**candidate, "zip": "62002"}]).values())
    assert not all(verified_address_parts("42 Oak Sampleton IL 62001", [candidate]).values())
