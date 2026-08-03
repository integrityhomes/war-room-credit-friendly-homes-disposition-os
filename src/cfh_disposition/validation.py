from __future__ import annotations

from dataclasses import dataclass, field

from .models import OwnerFinanceProperty, PropertyStatus


@dataclass(slots=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_launch(self) -> bool:
        return not self.errors


REQUIRED_TEXT_FIELDS = {
    "address": "Street address",
    "city": "City",
    "state": "State",
    "zip_code": "ZIP code",
    "condition_summary": "Condition summary",
    "showing_instructions": "Showing instructions",
    "public_disclosures": "Public disclosures",
}


def validate_property_for_launch(property_record: OwnerFinanceProperty) -> ValidationResult:
    result = ValidationResult()

    if property_record.status in {PropertyStatus.SOLD, PropertyStatus.PENDING}:
        result.errors.append(f"Property status is {property_record.status}; active marketing cannot launch.")

    for field_name, label in REQUIRED_TEXT_FIELDS.items():
        if not getattr(property_record, field_name):
            result.errors.append(f"Missing required field: {label}.")

    required_numbers = {
        "bedrooms": "Bedrooms",
        "bathrooms": "Bathrooms",
        "total_price": "Total price",
        "down_payment": "Down payment",
        "monthly_payment": "Monthly payment",
    }
    for field_name, label in required_numbers.items():
        value = getattr(property_record, field_name)
        if value is None:
            result.errors.append(f"Missing required field: {label}.")

    if property_record.down_payment is not None and property_record.total_price is not None:
        if property_record.down_payment > property_record.total_price:
            result.errors.append("Down payment cannot exceed the total price.")

    if not property_record.photo_urls:
        result.errors.append("At least one real property photo is required.")
    elif len(property_record.photo_urls) < 8:
        result.warnings.append("Fewer than 8 photos may reduce buyer response.")

    if not property_record.application_url:
        result.warnings.append("No application URL is connected; application follow-up will be limited.")

    if not property_record.video_url:
        result.warnings.append("No video is attached; video channels will use a photo slideshow.")

    if not property_record.repairs_needed:
        result.warnings.append("Repairs-needed field is blank. Confirm that this accurately means no known repairs.")

    return result
