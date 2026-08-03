from decimal import Decimal

import pytest
from pydantic import ValidationError

from cfh_disposition.models import OwnerFinanceProperty


def test_state_is_normalized() -> None:
    property_record = OwnerFinanceProperty(state="va")
    assert property_record.state == "VA"


def test_zip_validation_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        OwnerFinanceProperty(zip_code="ABC")


def test_down_payment_accepts_decimal() -> None:
    property_record = OwnerFinanceProperty(down_payment=Decimal("2500"))
    assert property_record.down_payment == Decimal("2500")
