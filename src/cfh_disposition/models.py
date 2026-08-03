from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class PropertyStatus(StrEnum):
    DRAFT = "Draft"
    NEEDS_INFORMATION = "Needs Information"
    READY = "Ready to Launch"
    LIVE = "Marketing Live"
    PENDING = "Pending"
    SOLD = "Sold"
    PAUSED = "Paused"


class CommunicationPreference(StrEnum):
    EMAIL = "Email"
    SMS = "SMS"
    PHONE = "Phone"
    ANY = "Any"


class OwnerFinanceProperty(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_id: UUID = Field(default_factory=uuid4)
    status: PropertyStatus = PropertyStatus.DRAFT
    address: str = ""
    city: str = ""
    state: str = Field(default="", max_length=2)
    zip_code: str = ""
    county: str = ""
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=20)
    square_feet: int | None = Field(default=None, ge=0)
    acreage: Decimal | None = Field(default=None, ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)
    down_payment: Decimal | None = Field(default=None, ge=0)
    monthly_payment: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    term_months: int | None = Field(default=None, ge=1, le=600)
    estimated_taxes: Decimal | None = Field(default=None, ge=0)
    estimated_insurance: Decimal | None = Field(default=None, ge=0)
    condition_summary: str = ""
    repairs_needed: str = ""
    occupancy: str = "Vacant"
    available_date: str = ""
    photo_urls: list[HttpUrl] = Field(default_factory=list)
    video_url: HttpUrl | None = None
    application_url: HttpUrl | None = None
    showing_instructions: str = ""
    public_disclosures: str = ""
    internal_notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str) -> str:
        return value.upper()

    @field_validator("zip_code")
    @classmethod
    def validate_zip(cls, value: str) -> str:
        if value and (len(value) not in {5, 10} or not value.replace("-", "").isdigit()):
            raise ValueError("ZIP code must be 5 digits or ZIP+4")
        return value

    @property
    def display_address(self) -> str:
        parts = [self.address, self.city, self.state, self.zip_code]
        return ", ".join(part for part in parts if part)


class BuyerProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    buyer_id: UUID = Field(default_factory=uuid4)
    first_name: str
    last_name: str = ""
    email: str = ""
    phone: str = ""
    preferred_cities: list[str] = Field(default_factory=list)
    preferred_states: list[str] = Field(default_factory=list)
    minimum_bedrooms: int | None = Field(default=None, ge=0)
    maximum_monthly_payment: Decimal | None = Field(default=None, ge=0)
    available_down_payment: Decimal | None = Field(default=None, ge=0)
    move_timeframe_days: int | None = Field(default=None, ge=0)
    repair_tolerance: str = "Unknown"
    communication_preference: CommunicationPreference = CommunicationPreference.ANY
    email_consent: bool = False
    sms_consent: bool = False
    call_consent: bool = False
    do_not_contact: bool = False
    source: str = "Unknown"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
