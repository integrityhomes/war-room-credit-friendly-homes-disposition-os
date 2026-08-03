from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .content import build_deterministic_campaign_draft
from .models import OwnerFinanceProperty

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"


class CampaignFactoryError(RuntimeError):
    """Raised when the AI campaign factory cannot produce a safe package."""


@dataclass(frozen=True)
class CampaignFactorySettings:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> CampaignFactorySettings:
        return cls(
            api_key=str(values.get("OPENAI_API_KEY", "")).strip(),
            model=str(values.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)).strip() or DEFAULT_OPENAI_MODEL,
        )


class CampaignPackage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    headline: str = Field(min_length=1, max_length=120)
    short_description: str = Field(min_length=1, max_length=500)
    marketplace_description: str = Field(min_length=1, max_length=2500)
    facebook_group_post: str = Field(min_length=1, max_length=1800)
    email_subject: str = Field(min_length=1, max_length=120)
    email_body: str = Field(min_length=1, max_length=2500)
    sms_message: str = Field(min_length=1, max_length=480)
    classified_ad: str = Field(min_length=1, max_length=1800)
    social_caption: str = Field(min_length=1, max_length=1000)
    video_script: str = Field(min_length=1, max_length=1800)
    dwelyx_call_to_action: str = Field(min_length=1, max_length=500)

    def channel_rows(self) -> list[tuple[str, str]]:
        return [
            ("Headline", self.headline),
            ("Short Description", self.short_description),
            ("Facebook Marketplace", self.marketplace_description),
            ("Facebook Groups", self.facebook_group_post),
            ("Email Subject", self.email_subject),
            ("Email Body", self.email_body),
            ("SMS", self.sms_message),
            ("Classified Ad", self.classified_ad),
            ("Social Caption", self.social_caption),
            ("Video Script", self.video_script),
            ("Dwelyx Call to Action", self.dwelyx_call_to_action),
        ]


CAMPAIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "short_description": {"type": "string"},
        "marketplace_description": {"type": "string"},
        "facebook_group_post": {"type": "string"},
        "email_subject": {"type": "string"},
        "email_body": {"type": "string"},
        "sms_message": {"type": "string"},
        "classified_ad": {"type": "string"},
        "social_caption": {"type": "string"},
        "video_script": {"type": "string"},
        "dwelyx_call_to_action": {"type": "string"},
    },
    "required": [
        "headline",
        "short_description",
        "marketplace_description",
        "facebook_group_post",
        "email_subject",
        "email_body",
        "sms_message",
        "classified_ad",
        "social_caption",
        "video_script",
        "dwelyx_call_to_action",
    ],
}

PROHIBITED_CLAIMS = (
    "guaranteed approval",
    "everyone approved",
    "no one denied",
    "bad credit guaranteed",
    "no credit check",
    "instant approval",
    "perfect for families",
    "safe neighborhood",
    "crime-free",
)


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def marketing_address(property_record: OwnerFinanceProperty) -> str:
    city_state = ", ".join(part for part in [property_record.city, property_record.state] if part)
    locality = f"{city_state} {property_record.zip_code}".strip()
    return ", ".join(part for part in [property_record.address, locality] if part)


def property_fact_packet(property_record: OwnerFinanceProperty, dwelyx_url: str) -> dict[str, Any]:
    address = marketing_address(property_record)
    return {
        "marketing_address": address,
        "bedrooms": property_record.bedrooms,
        "bathrooms": str(property_record.bathrooms) if property_record.bathrooms is not None else None,
        "purchase_price": _money(property_record.total_price),
        "down_payment": _money(property_record.down_payment),
        "monthly_payment": _money(property_record.monthly_payment),
        "condition_summary": property_record.condition_summary,
        "known_repairs": property_record.repairs_needed or "No repair statement provided; tell buyers to verify condition.",
        "public_disclosures": property_record.public_disclosures,
        "dwelyx_url": dwelyx_url,
        "instructions": [
            "Use only these facts. Never invent amenities, financing terms, approval criteria, neighborhood claims, or repair details.",
            "Include the exact marketing_address in every output field, including the headline, email subject, SMS, and Dwelyx call to action.",
            "Do not promise approval or use discriminatory/fair-housing-risk language.",
            "Every buyer call to action must direct the buyer to Dwelyx so they can browse all owner-finance inventory.",
            "Keep the tone practical, clear, and conversational.",
        ],
    }


def build_fallback_campaign(property_record: OwnerFinanceProperty, dwelyx_url: str) -> CampaignPackage:
    base = build_deterministic_campaign_draft(property_record)
    address = marketing_address(property_record)
    cta = f"Browse {address} and all available owner-finance homes on Dwelyx: {dwelyx_url}"
    return CampaignPackage(
        headline=base.headline,
        short_description=f"{base.short_description} {cta}",
        marketplace_description=f"{base.marketplace_description}\n\n{cta}",
        facebook_group_post=f"{base.short_description}\n\n{cta}",
        email_subject=base.email_subject,
        email_body=f"{base.marketplace_description}\n\n{cta}",
        sms_message=f"{base.sms_message} Browse all homes: {dwelyx_url}",
        classified_ad=f"{base.marketplace_description}\n\n{cta}",
        social_caption=f"{base.short_description}\n\n{cta}",
        video_script=f"Here is an owner-finance opportunity at {address}. {base.short_description} {cta}",
        dwelyx_call_to_action=cta,
    )


def _extract_output_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output", []) or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, Mapping) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise CampaignFactoryError("OpenAI returned no campaign text.")


def _allowed_money_values(property_record: OwnerFinanceProperty) -> set[str]:
    values: set[str] = set()
    for value in [property_record.total_price, property_record.down_payment, property_record.monthly_payment]:
        if value is None:
            continue
        values.add(f"{value:,.0f}")
        values.add(f"{value:.0f}")
    return values


def validate_campaign_facts(
    package: CampaignPackage,
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
) -> list[str]:
    errors: list[str] = []
    combined = "\n".join(text for _, text in package.channel_rows())
    lowered = combined.lower()

    for claim in PROHIBITED_CLAIMS:
        if claim in lowered:
            errors.append(f"Prohibited claim detected: {claim}")

    allowed_money = _allowed_money_values(property_record)
    for match in re.findall(r"\$([0-9][0-9,]*(?:\.[0-9]{1,2})?)", combined):
        normalized = match.rstrip("0").rstrip(".") if "." in match else match
        if normalized not in allowed_money and match not in allowed_money:
            errors.append(f"Unapproved dollar amount detected: ${match}")

    if dwelyx_url.rstrip("/") not in combined:
        errors.append("Dwelyx destination is missing from the campaign package.")

    address = marketing_address(property_record)
    if address:
        for label, text in package.channel_rows():
            if address.lower() not in text.lower():
                errors.append(f"Property address is missing from {label}.")

    return sorted(set(errors))


def generate_ai_campaign(
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
    settings: CampaignFactorySettings,
    timeout_seconds: int = 45,
) -> CampaignPackage:
    if not settings.configured:
        raise CampaignFactoryError("OPENAI_API_KEY is not configured.")

    developer_prompt = (
        "You are the Credit Friendly Homes campaign writer. Produce accurate, compliant owner-finance marketing copy. "
        "Use only the supplied fact packet. Do not infer or embellish. Include the exact marketing address in every output field. "
        "Avoid protected-class targeting, neighborhood safety claims, credit approval promises, and pressure language. "
        "Every channel must direct buyers to Dwelyx, where they can browse all inventory."
    )
    payload = {
        "model": settings.model,
        "input": [
            {"role": "developer", "content": [{"type": "input_text", "text": developer_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(property_fact_packet(property_record, dwelyx_url), ensure_ascii=False),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "credit_friendly_homes_campaign",
                "description": "A multi-channel owner-finance campaign package.",
                "strict": True,
                "schema": CAMPAIGN_SCHEMA,
            }
        },
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CampaignFactoryError(f"OpenAI request failed ({exc.code}): {detail[:500]}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CampaignFactoryError(f"OpenAI request failed: {exc}") from exc

    try:
        package = CampaignPackage.model_validate_json(_extract_output_text(response_data))
    except ValidationError as exc:
        raise CampaignFactoryError(f"OpenAI returned an invalid campaign package: {exc}") from exc

    fact_errors = validate_campaign_facts(package, property_record, dwelyx_url)
    if fact_errors:
        raise CampaignFactoryError("Campaign fact guard blocked the draft: " + "; ".join(fact_errors))
    return package
