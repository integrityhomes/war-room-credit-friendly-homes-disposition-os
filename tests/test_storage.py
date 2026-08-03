from decimal import Decimal

import pytest

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty
from cfh_disposition.storage import (
    InMemoryStorage,
    StorageError,
    SupabaseSettings,
    SupabaseStorage,
    _photo_path_from_url,
    _public_photo_url,
    validate_photo_upload,
)


def test_password_matching_is_exact():
    assert password_matches("correct horse", "correct horse")
    assert not password_matches("Correct horse", "correct horse")
    assert not password_matches("", "")


def test_configured_password_reads_mapping():
    assert configured_password({"APP_PASSWORD": " secret "}) == "secret"


def test_supabase_settings_prefer_new_secret_key():
    settings = SupabaseSettings.from_mapping(
        {
            "SUPABASE_URL": "https://demo.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_test",
            "SUPABASE_SERVICE_ROLE_KEY": "legacy",
        }
    )
    assert settings.configured
    assert settings.secret_key == "sb_secret_test"


def test_in_memory_storage_upserts_and_deletes_records():
    storage = InMemoryStorage()
    property_record = OwnerFinanceProperty(address="101 Demo Road", state="VA")
    storage.save_property(property_record)
    property_record.monthly_payment = Decimal("1200")
    storage.save_property(property_record)
    assert len(storage.list_properties()) == 1
    assert storage.list_properties()[0].monthly_payment == Decimal("1200")

    buyer = BuyerProfile(first_name="Jordan")
    storage.save_buyer(buyer)
    buyer.phone = "555-0100"
    storage.save_buyer(buyer)
    assert len(storage.list_buyers()) == 1
    assert storage.list_buyers()[0].phone == "555-0100"

    storage.delete_property(property_record.property_id)
    storage.delete_buyer(buyer.buyer_id)
    assert storage.list_properties() == []
    assert storage.list_buyers() == []


def test_supabase_row_serialization_round_trips():
    property_record = OwnerFinanceProperty(
        address="101 Demo Road",
        city="Saltville",
        state="va",
        zip_code="24370",
        monthly_payment=Decimal("1200"),
    )
    row = SupabaseStorage._property_row(property_record)
    rebuilt = OwnerFinanceProperty.model_validate(row["payload"])
    assert rebuilt.property_id == property_record.property_id
    assert rebuilt.state == "VA"
    assert rebuilt.monthly_payment == Decimal("1200")

    buyer = BuyerProfile(first_name="Jordan", maximum_monthly_payment=Decimal("1300"))
    buyer_row = SupabaseStorage._buyer_row(buyer)
    rebuilt_buyer = BuyerProfile.model_validate(buyer_row["payload"])
    assert rebuilt_buyer.buyer_id == buyer.buyer_id
    assert rebuilt_buyer.maximum_monthly_payment == Decimal("1300")


def test_photo_public_url_round_trip():
    base_url = "https://demo.supabase.co"
    object_path = "property-id/front porch.jpg"
    public_url = _public_photo_url(base_url, object_path)
    assert public_url.endswith("/cfh-property-photos/property-id/front%20porch.jpg")
    assert _photo_path_from_url(base_url, public_url) == "property-id/front%20porch.jpg"


def test_photo_validation_accepts_supported_images():
    validate_photo_upload("front.jpg", b"photo-bytes", "image/jpeg")
    validate_photo_upload("kitchen.webp", b"photo-bytes", "image/webp")


def test_photo_validation_rejects_private_documents():
    with pytest.raises(StorageError, match="Only JPG, PNG, and WEBP"):
        validate_photo_upload("application.pdf", b"private-document", "application/pdf")


def test_photo_validation_rejects_oversized_files():
    with pytest.raises(StorageError, match="larger than 10 MB"):
        validate_photo_upload("front.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")
