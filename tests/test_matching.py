from decimal import Decimal

from cfh_disposition.matching import match_buyer_to_property
from cfh_disposition.models import BuyerProfile
from cfh_disposition.sample_data import SAMPLE_PROPERTIES


def test_matching_buyer_is_eligible() -> None:
    buyer = BuyerProfile(
        first_name="Test",
        preferred_states=["VA"],
        preferred_cities=["Saltville"],
        minimum_bedrooms=2,
        maximum_monthly_payment=Decimal("1300"),
        available_down_payment=Decimal("6000"),
    )
    result = match_buyer_to_property(buyer, SAMPLE_PROPERTIES[0])
    assert result.is_eligible
    assert result.score >= 80


def test_do_not_contact_buyer_is_never_eligible() -> None:
    buyer = BuyerProfile(first_name="Suppressed", do_not_contact=True)
    result = match_buyer_to_property(buyer, SAMPLE_PROPERTIES[0])
    assert not result.is_eligible
