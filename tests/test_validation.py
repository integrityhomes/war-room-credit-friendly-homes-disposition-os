from cfh_disposition.sample_data import SAMPLE_PROPERTIES
from cfh_disposition.validation import validate_property_for_launch


def test_complete_sample_property_can_launch() -> None:
    result = validate_property_for_launch(SAMPLE_PROPERTIES[0])
    assert result.can_launch


def test_incomplete_sample_property_is_blocked() -> None:
    result = validate_property_for_launch(SAMPLE_PROPERTIES[1])
    assert not result.can_launch
    assert any("Showing instructions" in error for error in result.errors)


def test_photo_warning_does_not_replace_required_photo_error() -> None:
    property_record = SAMPLE_PROPERTIES[0].model_copy(update={"photo_urls": []})
    result = validate_property_for_launch(property_record)
    assert not result.can_launch
    assert any("photo" in error.lower() for error in result.errors)
