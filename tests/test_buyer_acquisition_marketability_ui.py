from pathlib import Path


def test_buyer_acquisition_only_offers_marketable_properties() -> None:
    source = Path("pages/15_AI_Buyer_Acquisition_Growth.py").read_text(encoding="utf-8")

    assert "from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES" in source
    assert "item.status in MARKETABLE_PROPERTY_STATUSES" in source
    assert "No properties are currently Ready to Launch or Marketing Live" in source
    assert "disabled=create_disabled" in source
