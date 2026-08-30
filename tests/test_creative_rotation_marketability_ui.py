from pathlib import Path


def test_creative_rotation_only_offers_marketable_properties_for_new_tests() -> None:
    source = Path("pages/14_AI_Creative_Winner_Rotation.py").read_text(encoding="utf-8")

    assert "from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES" in source
    assert "item.status in MARKETABLE_PROPERTY_STATUSES" in source
    assert "No properties are currently Ready to Launch or Marketing Live" in source
    assert "ledger.experiments" in source
