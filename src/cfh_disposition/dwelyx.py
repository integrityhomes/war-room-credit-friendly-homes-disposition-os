from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

DEFAULT_DWELYX_URL = "https://www.dwelyx.com/buyer/register"
DEFAULT_TRACKING_APP_URL = (
    "https://war-room-credit-friendly-homes-disposition-os-a6eb96y5qwg7uvts.streamlit.app"
)
DEFAULT_SOURCE = "credit_friendly_homes"


def dwelyx_base_url(values: Mapping[str, Any] | None = None) -> str:
    """Return the buyer registration/login destination used by every campaign."""
    configured = str((values or {}).get("DWELYX_BUYER_URL", DEFAULT_DWELYX_URL)).strip()
    if not configured:
        configured = DEFAULT_DWELYX_URL
    if "://" not in configured:
        configured = f"https://{configured}"
    return configured.rstrip("/")


def tracking_app_base_url(values: Mapping[str, Any] | None = None) -> str:
    configured = str((values or {}).get("PUBLIC_APP_URL", DEFAULT_TRACKING_APP_URL)).strip()
    if not configured:
        configured = DEFAULT_TRACKING_APP_URL
    if "://" not in configured:
        configured = f"https://{configured}"
    return configured.rstrip("/")


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def build_direct_dwelyx_url(
    base_url: str,
    *,
    source: str,
    medium: str,
    campaign: str = "owner_finance_homes",
    property_id: UUID | str | None = None,
) -> str:
    """Build the final Dwelyx buyer-account URL with standard attribution."""
    parts = urlsplit(dwelyx_base_url({"DWELYX_BUYER_URL": base_url}))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "utm_source": _slug(source),
            "utm_medium": _slug(medium),
            "utm_campaign": _slug(campaign),
        }
    )
    if property_id:
        query["utm_content"] = f"property_{property_id}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_dwelyx_url(
    base_url: str,
    *,
    source: str,
    medium: str,
    campaign: str = "owner_finance_homes",
    property_id: UUID | str | None = None,
    tracking_base_url: str = DEFAULT_TRACKING_APP_URL,
) -> str:
    """Build a compact tracked redirect to Dwelyx buyer registration/login."""
    tracking_parts = urlsplit(tracking_app_base_url({"PUBLIC_APP_URL": tracking_base_url}))
    destination = dwelyx_base_url({"DWELYX_BUYER_URL": base_url})
    source_slug = _slug(source)
    query = {
        "go": "dwelyx",
        "medium": _slug(medium),
        "campaign": _slug(campaign),
    }

    # The redirect page already defaults to the standard buyer-registration URL
    # and Credit Friendly Homes source. Omitting those repeated values keeps SMS
    # and other character-limited campaign fields below their hard limits.
    if destination != DEFAULT_DWELYX_URL:
        query["target"] = destination
    if source_slug != DEFAULT_SOURCE:
        query["source"] = source_slug
    if property_id:
        query["property_id"] = str(property_id)

    return urlunsplit(
        (
            tracking_parts.scheme,
            tracking_parts.netloc,
            tracking_parts.path or "/",
            urlencode(query),
            "",
        )
    )
