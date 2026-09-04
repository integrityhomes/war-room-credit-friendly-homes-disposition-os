"""Full-spreadsheet, zero-persistence audit for the existing Google property source."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
from .google_sheet_property_rows import RowValidationState

FullWorksheetLoader = Callable[
    [object, str], tuple[ReadOnlyWorksheetValues, ...]
]


class PropertyTabSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_tab: str
    physical_rows_inspected: int
    detected_property_rows: int
    fully_normalized: int
    needs_review: int
    malformed: int
    non_property_rows: int


class NeedsReviewPropertyPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_tab: str
    source_row_number: int
    property_address: str
    source_identity: str
    status: str
    sales_price: Decimal | None
    down_payment: Decimal | None
    total_monthly_payment: Decimal | None
    last_update: str | None
    reasons: tuple[str, ...]
    possible_duplicate: bool


class FullPropertySourceAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    worksheets_discovered: int
    worksheets_processed: int
    total_physical_rows_inspected: int
    source_property_rows_detected: int
    fully_normalized_properties: int
    properties_needing_review: int
    true_malformed_property_rows: int
    non_property_header_blank_rows: int
    duplicate_candidates: int
    sold_count: int
    do_not_sell_count: int
    active_available_count: int
    properties_by_source_tab: tuple[PropertyTabSummary, ...]
    safe_previews: tuple[SafePropertyPreview, ...]
    needs_review_previews: tuple[NeedsReviewPropertyPreview, ...]
    google_writes: int = 0
    commandcore_persistence: int = 0
    external_actions_started: bool = False


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def _is_header(values: Sequence[object]) -> bool:
    return bool(values and _key(values[0]) in {"address", "property", "property_address"})


def _blank(values: Sequence[object]) -> bool:
    return not any(str(value or "").strip() for value in values)


def _tab_status(tab_name: str) -> str:
    key = _key(tab_name)
    if "do_not_sell" in key:
        return "Paused"
    if re.search(r"(?:^|_)sold(?:_|$)", key):
        return "Sold / Unavailable"
    return "Available"


def _mapped_row(
    values: Sequence[object], row_number: int
) -> dict[str, object]:
    row = {
        column: values[index] if index < len(values) else None
        for index, column in enumerate(V14_PROPERTY_COLUMNS)
    }
    row["sheet_row"] = row_number
    return row


def _is_v14_property_row(values: Sequence[object]) -> bool:
    address = str(values[0] or "").strip() if values else ""
    return bool(address and re.match(r"^\d+\s+", address))


def _normalize_source_date(value: object) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    for date_format in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m/%d/%Y %H:%M:%S",
        "%m-%d-%Y",
    ):
        try:
            parsed = datetime.strptime(text, date_format)
        except ValueError:
            continue
        return parsed.isoformat(), None
    return None, "Last update needs review because its date format was not recognized."


def _safe_decimal(value: object) -> Decimal | None:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _review_identity(tab_name: str, row_number: int, address: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", address.casefold())
    basis = normalized or f"{tab_name.casefold()}:{row_number}"
    return "source-property-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _review_preview(
    row: Mapping[str, object],
    *,
    tab_name: str,
    row_number: int,
    status: str,
    reasons: Sequence[str],
    possible_duplicate: bool = False,
) -> NeedsReviewPropertyPreview:
    return NeedsReviewPropertyPreview(
        source_tab=tab_name,
        source_row_number=row_number,
        property_address=str(row.get("property_address") or "").strip(),
        source_identity=_review_identity(
            tab_name, row_number, str(row.get("property_address") or "")
        ),
        status=status,
        sales_price=_safe_decimal(row.get("sales_price")),
        down_payment=_safe_decimal(row.get("down_payment")),
        total_monthly_payment=_safe_decimal(row.get("total_monthly_payment")),
        last_update=str(row.get("last_update") or "").strip() or None,
        reasons=tuple(reasons) or ("Property details need review.",),
        possible_duplicate=possible_duplicate,
    )


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
    review_candidates: list[NeedsReviewPropertyPreview] = []
    tab_counts: list[PropertyTabSummary] = []
    detected_total = 0
    malformed_total = 0
    non_property_total = 0
    for worksheet in worksheets:
        context = V14PropertySourceContext(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            source_reference=sheet_id,
            tab_name=worksheet.tab_name,
        )
        tab_detected = 0
        tab_normalized = 0
        tab_review = 0
        tab_malformed = 0
        tab_non_property = 0
        values = tuple(worksheet)
        for start in range(0, len(values), FULL_AUDIT_BATCH_SIZE):
            for row_number, physical_row in enumerate(
                values[start : start + FULL_AUDIT_BATCH_SIZE], start=start + 1
            ):
                if _blank(physical_row):
                    tab_non_property += 1
                    continue
                if _is_header(physical_row) or not _is_v14_property_row(physical_row):
                    tab_non_property += 1
                    continue
                tab_detected += 1
                detected_total += 1
                mapped = _mapped_row(physical_row, row_number)
                mapped["availability"] = mapped.get("status") or _tab_status(
                    worksheet.tab_name
                )
                normalized_date, date_reason = _normalize_source_date(
                    mapped.get("last_update")
                )
                mapped["last_update"] = normalized_date
                result = adapt_v14_property_row(
                    mapped, context=context, sheet_row_number=row_number
                )
                if result.state is RowValidationState.INVALID_SOURCE_ROW:
                    tab_malformed += 1
                    malformed_total += 1
                elif result.normalized is None or date_reason:
                    tab_review += 1
                    review_candidates.append(
                        _review_preview(
                            mapped,
                            tab_name=worksheet.tab_name,
                            row_number=row_number,
                            status=str(mapped["availability"]),
                            reasons=(*result.errors, *((date_reason,) if date_reason else ())),
                        )
                    )
                else:
                    normalized.append(result)
                    tab_normalized += 1
        non_property_total += tab_non_property
        tab_counts.append(
            PropertyTabSummary(
                source_tab=worksheet.tab_name,
                physical_rows_inspected=len(values),
                detected_property_rows=tab_detected,
                fully_normalized=tab_normalized,
                needs_review=tab_review,
                malformed=tab_malformed,
                non_property_rows=tab_non_property,
            )
        )

    plans = plan_inventory_sync(normalized, existing_records)
    previews = tuple(
        _safe_preview(item, plan)
        for item, plan in zip(normalized, plans, strict=True)
        if item.normalized is not None
    )
    known_addresses = Counter(
        re.sub(r"[^a-z0-9]+", "", item.property_address.casefold())
        for item in (*previews, *review_candidates)
    )
    reviewed = tuple(
        item.model_copy(
            update={
                "possible_duplicate": known_addresses[
                    re.sub(r"[^a-z0-9]+", "", item.property_address.casefold())
                ]
                > 1
            }
        )
        for item in review_candidates
    )
    duplicate_count = sum(
        plan.state is SyncResultState.DUPLICATE for plan in plans
    ) + sum(item.possible_duplicate for item in reviewed)
    result = FullPropertySourceAudit(
        worksheets_discovered=len(worksheets),
        worksheets_processed=len(tab_counts),
        total_physical_rows_inspected=sum(len(item) for item in worksheets),
        source_property_rows_detected=detected_total,
        fully_normalized_properties=len(previews),
        properties_needing_review=len(reviewed),
        true_malformed_property_rows=malformed_total,
        non_property_header_blank_rows=non_property_total,
        duplicate_candidates=duplicate_count,
        sold_count=sum(
            count.detected_property_rows
            for count in tab_counts
            if _tab_status(count.source_tab) == "Sold / Unavailable"
        ),
        do_not_sell_count=sum(
            count.detected_property_rows
            for count in tab_counts
            if "do_not_sell" in _key(count.source_tab)
        ),
        active_available_count=sum(
            count.detected_property_rows
            for count in tab_counts
            if _tab_status(count.source_tab) == "Available"
        ),
        properties_by_source_tab=tuple(tab_counts),
        safe_previews=previews,
        needs_review_previews=reviewed,
    )
    if result.google_writes or result.commandcore_persistence or result.external_actions_started:
        raise GoogleBridgeError("The full property source audit did not remain read-only.")
    return result
