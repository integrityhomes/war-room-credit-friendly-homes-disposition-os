from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

DEFAULT_DWELYX_URL = "https://www.dwelyx.com"


def dwelyx_base_url(values: Mapping[str, Any] | None = None) -> str:
    configured = str((values or {}).get("DWELYX_URL", DEFAULT_DWELYX_URL)).strip()
    if not configured:
        configured = DEFAULT_DWELYX_URL
    if "://" not in configured:
        configured = f"https://{configured}"
    return configured.rstrip("/")


def build_dwelyx_url(
    base_url: str,
    *,
    source: str,
    medium: str,
    campaign: str = "owner_finance_homes",
    property_id: UUID | str | None = None,
) -> str:
    """Build a Dwelyx destination link with marketing attribution."""
    parts = urlsplit(dwelyx_base_url({"DWELYX_URL": base_url}))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "utm_source": source.strip().lower().replace(" ", "_"),
            "utm_medium": medium.strip().lower().replace(" ", "_"),
            "utm_campaign": campaign.strip().lower().replace(" ", "_"),
        }
    )
    if property_id:
        query["utm_content"] = f"property_{property_id}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
