"""Full-spreadsheet, zero-persistence audit for the existing Google property source."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from .commandcore_property_inventory import (
    CanonicalPropertyRecord,
    SyncResultState,
    plan_inventory_sync,
)
from .google_property_readonly_loader import (
    FULL_AUDIT_BATCH_SIZE,
    V14_PROPERTY_COLUMNS,
    ReadOnlyWorksheetValues,
    build_read_only_google_credentials,
    load_all_read_only_worksheet_values,
)
from .google_property_runtime_bridge import (
    CredentialFactory,
    GoogleBridgeError,
    SafePropertyPreview,
    resolve_read_only_google_access,
)
from .google_property_source_adapter import (
    V14PropertySourceContext,
    V14PropertySourceType,
    adapt_v14_property_row,
)

FullWorksheetLoader = Callable[
    [object, str], tuple[ReadOnlyWorksheetValues, ...]
]


class PropertyTabSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_tab: str
    physical_rows_inspected: int
    valid_property_rows: int
    malformed_or_skipped_rows: int


class FullPropertySourceAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    worksheets_discovered: int
    worksheets_processed: int
    total_physical_rows_inspected: int
    valid_property_rows_found: int
    normalized_properties: int
    duplicate_candidates: int
    malformed_or_skipped_rows: int
    sold_count: int
    do_not_sell_count: int
    active_available_count: int
    properties_by_source_tab: tuple[PropertyTabSummary, ...]
    safe_previews: tuple[SafePropertyPreview, ...]
    google_writes: int = 0
    commandcore_persistence: int = 0
    external_actions_started: bool = False


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


_HEADER_ALIASES = {
    **{_key(name): name for name in V14_PROPERTY_COLUMNS},
    "address": "property_address",
    "property": "property_address",
    "sq_ft": "square_feet",
    "sqft": "square_feet",
    "price": "sales_price",
    "monthly_payment": "total_monthly_payment",
    "status": "status",
    "availability": "status",
}


def _header_map(values: Sequence[object]) -> dict[int, str] | None:
    mapped = {
        index: _HEADER_ALIASES[key]
        for index, value in enumerate(values)
        if (key := _key(value)) in _HEADER_ALIASES
    }
    return mapped if "property_address" in mapped.values() else None


def _blank(values: Sequence[object]) -> bool:
    return not any(str(value or "").strip() for value in values)


def _tab_status(tab_name: str) -> str:
    key = _key(tab_name)
    if "do_not_sell" in key:
        return "Paused"
    if re.search(r"(?:^|_)sold(?:_|$)", key):
        return "Sold / Unavailable"
    return "Coming Soon"


def _mapped_row(
    values: Sequence[object], row_number: int, headers: Mapping[int, str] | None
) -> dict[str, object]:
    if headers:
        row = {
            field: values[index] if index < len(values) else None
            for index, field in headers.items()
        }
    else:
        row = {
            column: values[index] if index < len(values) else None
            for index, column in enumerate(V14_PROPERTY_COLUMNS)
        }
    row["sheet_row"] = row_number
    return row


def _safe_preview(normalized: Any, plan: Any) -> SafePropertyPreview:
    row = normalized.normalized
    if row is None:
        raise GoogleBridgeError("A property row could not be previewed safely.")
    return SafePropertyPreview(
        source_type=row.source_type or V14PropertySourceType.DIRECT_GOOGLE_SHEET.value,
        worksheet_or_tab=row.source_tab or "Unknown",
        property_address=f"{row.address}, {row.city}, {row.state} {row.zip_code}",
        canonical_identity=plan.commandcore_property_id,
        status=row.availability.value,
        sales_price=row.total_price,
        down_payment=row.down_payment,
        total_monthly_payment=row.monthly_payment,
        last_update=row.source_updated_at,
        normalization_result=normalized.state.value,
        duplicate_result=plan.state.value,
    )


def run_full_property_source_audit(
    secrets: Mapping[str, Any],
    *,
    existing_records: Sequence[CanonicalPropertyRecord] = (),
    credential_factory: CredentialFactory = build_read_only_google_credentials,
    worksheet_loader: FullWorksheetLoader = load_all_read_only_worksheet_values,
) -> FullPropertySourceAudit:
    """Read, normalize, and plan the entire source without writing anywhere."""
    credentials, sheet_id = resolve_read_only_google_access(
        secrets, credential_factory
    )
    try:
        worksheets = worksheet_loader(credentials, sheet_id)
    except GoogleBridgeError:
        raise
    except Exception:
        raise GoogleBridgeError(
            "The full property source audit could not read worksheets safely."
        ) from None
    if not worksheets:
        raise GoogleBridgeError("No property worksheets were discovered.")

    normalized = []
    tab_counts: list[PropertyTabSummary] = []
    skipped_total = 0
    for worksheet in worksheets:
        context = V14PropertySourceContext(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            source_reference=sheet_id,
            tab_name=worksheet.tab_name,
        )
        headers: dict[int, str] | None = None
        tab_valid = 0
        tab_skipped = 0
        values = tuple(worksheet)
        for start in range(0, len(values), FULL_AUDIT_BATCH_SIZE):
            for row_number, physical_row in enumerate(
                values[start : start + FULL_AUDIT_BATCH_SIZE], start=start + 1
            ):
                if _blank(physical_row):
                    tab_skipped += 1
                    continue
                if detected := _header_map(physical_row):
                    headers = detected
                    tab_skipped += 1
                    continue
                mapped = _mapped_row(physical_row, row_number, headers)
                if not str(mapped.get("property_address") or "").strip():
                    tab_skipped += 1
                    continue
                mapped["availability"] = mapped.get("status") or _tab_status(
                    worksheet.tab_name
                )
                result = adapt_v14_property_row(
                    mapped, context=context, sheet_row_number=row_number
                )
                normalized.append(result)
                if result.normalized is None:
                    tab_skipped += 1
                else:
                    tab_valid += 1
        skipped_total += tab_skipped
        tab_counts.append(
            PropertyTabSummary(
                source_tab=worksheet.tab_name,
                physical_rows_inspected=len(values),
                valid_property_rows=tab_valid,
                malformed_or_skipped_rows=tab_skipped,
            )
        )

    plans = plan_inventory_sync(normalized, existing_records)
    previews = tuple(
        _safe_preview(item, plan)
        for item, plan in zip(normalized, plans, strict=True)
        if item.normalized is not None
    )
    statuses = Counter(item.status for item in previews)
    duplicate_count = sum(plan.state is SyncResultState.DUPLICATE for plan in plans)
    result = FullPropertySourceAudit(
        worksheets_discovered=len(worksheets),
        worksheets_processed=len(tab_counts),
        total_physical_rows_inspected=sum(len(item) for item in worksheets),
        valid_property_rows_found=len(previews),
        normalized_properties=len(previews),
        duplicate_candidates=duplicate_count,
        malformed_or_skipped_rows=skipped_total,
        sold_count=statuses["Sold / Unavailable"],
        do_not_sell_count=sum(
            count.valid_property_rows
            for count in tab_counts
            if "do_not_sell" in _key(count.source_tab)
        ),
        active_available_count=statuses["Available"],
        properties_by_source_tab=tuple(tab_counts),
        safe_previews=previews,
    )
    if result.google_writes or result.commandcore_persistence or result.external_actions_started:
        raise GoogleBridgeError("The full property source audit did not remain read-only.")
    return result
