"""Fail-closed read-only runtime boundary for the existing CFD Builder Google source."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .commandcore_property_inventory import CanonicalPropertyRecord, plan_inventory_sync
from .google_property_source_adapter import (
    V14PropertySourceContext,
    V14PropertySourceType,
    adapt_v14_property_rows,
)

GOOGLE_SERVICE_ACCOUNT_SECRET = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_SHEET_ID_SECRET = "GOOGLE_SHEET_ID"
APPROVED_READ_ONLY_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)
FIRST_LIVE_TEST_ROW_LIMIT = 3


class GoogleBridgeError(RuntimeError):
    """A sanitized, fail-closed runtime bridge error."""


class GoogleExecutionMode(StrEnum):
    READ_ONLY_TEST = "read_only_test"


class ReadOnlySourceBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: V14PropertySourceType
    tab_name: str
    rows: tuple[Mapping[str, Any], ...]


class SafePropertyPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: str
    worksheet_or_tab: str
    property_address: str
    canonical_identity: str | None
    status: str
    sales_price: Decimal | None
    down_payment: Decimal | None
    total_monthly_payment: Decimal | None
    last_update: str | None
    normalization_result: str
    duplicate_result: str


class ReadOnlyBridgeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows_read: int
    rows_displayed: int
    previews: tuple[SafePropertyPreview, ...]
    google_writes: int = 0
    commandcore_persistence: int = 0
    external_actions_started: bool = False


CredentialFactory = Callable[[Mapping[str, Any], tuple[str, ...]], object]
ReadOnlySheetLoader = Callable[[object, str, int], ReadOnlySourceBatch]


def _required_secret(secrets: Mapping[str, Any], name: str) -> str:
    value = secrets.get(name)
    if not isinstance(value, str) or not value.strip():
        raise GoogleBridgeError(f"Required CommandCore runtime secret is missing: {name}.")
    return value.strip()


def _credential_payload(raw: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        raise GoogleBridgeError("The configured Google service account secret is malformed.") from None
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(field), str) and payload[field].strip()
        for field in ("type", "client_email", "private_key")
    ):
        raise GoogleBridgeError("The configured Google service account secret is malformed.")
    return payload


def run_read_only_property_source_test(
    *,
    secrets: Mapping[str, Any],
    credential_factory: CredentialFactory,
    sheet_loader: ReadOnlySheetLoader,
    existing_records: Sequence[CanonicalPropertyRecord] = (),
    mode: GoogleExecutionMode = GoogleExecutionMode.READ_ONLY_TEST,
    scopes: Sequence[str] = APPROVED_READ_ONLY_SCOPES,
) -> ReadOnlyBridgeResult:
    """Plan up to three property rows without Google writes or CommandCore persistence."""
    if mode is not GoogleExecutionMode.READ_ONLY_TEST:
        raise GoogleBridgeError("Only the approved read-only test mode is permitted.")
    if tuple(scopes) != APPROVED_READ_ONLY_SCOPES:
        raise GoogleBridgeError("Google scopes must be exactly the approved read-only scopes.")

    credential_json = _required_secret(secrets, GOOGLE_SERVICE_ACCOUNT_SECRET)
    sheet_id = _required_secret(secrets, GOOGLE_SHEET_ID_SECRET)
    payload = _credential_payload(credential_json)
    try:
        credentials = credential_factory(payload, APPROVED_READ_ONLY_SCOPES)
        batch = sheet_loader(credentials, sheet_id, FIRST_LIVE_TEST_ROW_LIMIT)
    except GoogleBridgeError:
        raise
    except Exception:
        raise GoogleBridgeError("The read-only Google property source could not be opened safely.") from None

    if batch.source_type is not V14PropertySourceType.DIRECT_GOOGLE_SHEET:
        raise GoogleBridgeError("The configured property source type is not the approved direct Google Sheet source.")
    if not batch.tab_name.strip():
        raise GoogleBridgeError("The property source worksheet or tab identity is ambiguous.")
    if len(batch.rows) > FIRST_LIVE_TEST_ROW_LIMIT:
        raise GoogleBridgeError("The read-only source returned more than the three-row safety limit.")

    context = V14PropertySourceContext(
        source_type=batch.source_type,
        source_reference=sheet_id,
        tab_name=batch.tab_name,
    )
    try:
        normalized = adapt_v14_property_rows(batch.rows, context=context)
        plans = plan_inventory_sync(normalized, existing_records)
    except Exception:
        raise GoogleBridgeError("Property rows could not be normalized safely.") from None

    previews: list[SafePropertyPreview] = []
    for result, plan in zip(normalized, plans, strict=True):
        row = result.normalized
        if row is None:
            raise GoogleBridgeError("A property source row was incomplete or malformed.")
        previews.append(
            SafePropertyPreview(
                source_type=row.source_type or batch.source_type.value,
                worksheet_or_tab=row.source_tab or batch.tab_name,
                property_address=f"{row.address}, {row.city}, {row.state} {row.zip_code}",
                canonical_identity=plan.commandcore_property_id,
                status=row.availability.value,
                sales_price=row.total_price,
                down_payment=row.down_payment,
                total_monthly_payment=row.monthly_payment,
                last_update=row.source_updated_at,
                normalization_result=result.state.value,
                duplicate_result=plan.state.value,
            )
        )
    return ReadOnlyBridgeResult(
        rows_read=len(batch.rows),
        rows_displayed=len(previews),
        previews=tuple(previews),
    )
