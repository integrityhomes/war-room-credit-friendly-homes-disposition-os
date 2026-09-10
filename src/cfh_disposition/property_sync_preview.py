"""Read-only sheet comparison against the existing canonical CRM property records."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal, InvalidOperation
from typing import Any

from .google_property_full_audit import _normalize_source_date
from .google_property_source_adapter import V14PropertySourceContext, V14PropertySourceType, _address_parts, adapt_v14_property_row
from .property_source_fields import ALIASES

REGIONAL_TABS = (
    "Decatur/Quincy/Cerro Gordo", "Springfield/Pekin/New Athens", "Peoria/Assumption/Moweaqua",
    "ESTL/Alton/GraniteCity/Cahokia", "Saint Louis MO", "Indiana", "Virginia", "Louisiana", "Ohio", "Michigan", "Mississippi",
)
INVENTORY_TABS = (*REGIONAL_TABS, "SOLD", "DO NOT SELL LIST")
NEW = "NEW PROPERTY"
PRICE = "PRICE CHANGE"
TERMS = "PAYMENT/TERMS CHANGE"
STATUS = "STATUS CHANGE"
SOLD = "SOLD"
OTHER = "OTHER MEANINGFUL CHANGE"
MISSING = "MISSING FROM SHEET / NEEDS REVIEW"
REVIEW = "NEEDS REVIEW"
HISTORY = "HISTORICAL SOURCE EVIDENCE"
CATEGORIES = (NEW, PRICE, TERMS, STATUS, SOLD, OTHER, MISSING, REVIEW)
FIELD_ALIASES = {
    "asking_or_sale_price": ("asking_or_sale_price", "total_price", "sales_price", "asking_price"),
    "down_payment": ("down_payment",), "monthly_payment": ("monthly_payment", "total_monthly_payment"),
    "interest_rate": ("interest_rate",), "monthly_principal_interest": ("monthly_principal_interest",),
    "monthly_insurance": ("monthly_insurance",), "monthly_taxes": ("monthly_taxes",),
    "insurance_included": ("insurance_included",), "availability": ("availability", "status"),
    "bedrooms": ("bedrooms", "beds"), "bathrooms": ("bathrooms", "baths"), "square_feet": ("square_feet", "sqft"),
    "photo_link": ("photo_link",), "legal_description": ("legal_description",), "parcel_number": ("parcel_number", "parcel_id"),
    "notes": ("notes",),
}
TERM_FIELDS = frozenset(("down_payment", "monthly_payment", "interest_rate", "monthly_principal_interest", "monthly_insurance", "monthly_taxes", "insurance_included"))
NUMERIC_FIELDS = (TERM_FIELDS - {"insurance_included"}) | {"asking_or_sale_price", "bedrooms", "bathrooms", "square_feet"}
HEADER_FIELDS = {
    "property": "property_address", "address": "property_address", "property address": "property_address",
    "beds": "beds", "bedrooms": "beds", "baths": "baths", "bathrooms": "baths", "sq ft": "square_feet",
    "down payment": "down_payment", "monthly": "total_monthly_payment", "monthly payment": "total_monthly_payment",
    "sales price": "sales_price", "interest rate": "interest_rate", "monthly payment principal": "monthly_principal_interest",
    "insurance": "monthly_insurance", "monthly taxes": "monthly_taxes", "insurance included": "insurance_included",
    "photo folder": "photo_link", "link to photos": "photo_link", "photos": "photo_link",
    "legal description": "legal_description", "parcel": "parcel_number", "notes": "notes",
    "date added to sheet": "date_added", "last update": "last_update",
    "lockbox": "lockbox_code", "lockbox code": "lockbox_code", "lock box": "lockbox_code", "lock box code": "lockbox_code",
}
HEADER_FIELDS.update(ALIASES)


def header_key(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text(value).casefold()))


def inventory_header(values: Sequence[Any]) -> bool:
    fields = {"beds", "baths", "sales_price", "purchase_price", "down_payment", "total_monthly_payment"}
    return len({HEADER_FIELDS.get(header_key(value)) for value in values} & fields) >= 3


def worksheet_classification(worksheet: Any) -> str:
    if worksheet.tab_name == "_REIBB_CACHE":
        return "support/cache/system"
    if worksheet.tab_name in (*REGIONAL_TABS, "SOLD"):
        return "property/inventory"
    if worksheet.tab_name == "DO NOT SELL LIST":
        populated = [row for row in worksheet if any(text(value) for value in row)]
        if (populated and header_key(populated[0][0]) == "do not sell to"
                and not any(inventory_header(row) or re.match(r"^\d+\s+", text(row[0])) for row in populated)):
            return "support/cache/system"
    return "unknown / needs review"


def sheet_address_parts(value: Any, *, verified_format_recovery: bool = False) -> dict[str, Any]:
    """Accept explicit components only; an ambiguous street/city split stays unresolved."""
    value = " ".join(text(value).split())
    original = _address_parts({"property_address": value})
    if all(original.values()):
        return original
    # A spelled-out state immediately before an explicit ZIP is the same address
    # fact in scheduled reads and reconciliation. Street/city ambiguity checks
    # below still apply; never obtain components from a tab or another row.
    state_names = {"West Virginia": "WV", "Illinois": "IL", "Missouri": "MO", "Indiana": "IN", "Virginia": "VA",
                   "Louisiana": "LA", "Ohio": "OH", "Michigan": "MI", "Mississippi": "MS"}
    for name, code in state_names.items():
        value = re.sub(rf"\b{name}(?=[,\s]+\d{{5}}(?:-\d{{4}})?$)", code, value, flags=re.IGNORECASE)
    # A terminal state abbreviation period is punctuation, not a missing fact.
    # Require an explicit, separately spaced ZIP; broader recovery stays opt-in.
    value = re.sub(r"\b([A-Za-z]{2})\.(?=\s+\d{5}(?:-\d{4})?$)", r"\1", value)
    if verified_format_recovery:
        value = re.sub(r"\b([A-Za-z]{2})\.?\s*,?\s*(\d{5}(?:-\d{4})?)$", r"\1 \2", value)
        if value.count("|") == 1:
            value = re.sub(r"\s*\|\s*", ", ", value)
        explicit = _address_parts({"property_address": value})
        if all(explicit.values()):
            return explicit
    tail = re.fullmatch(r"(.+?)[,\s]+([A-Za-z]{2})[,\s]+(\d{5}(?:-\d{4})?)", value)
    if not tail:
        return original
    location, state, zip_code = tail.groups()
    candidates = []
    if location.count(",") == 1:
        candidates = [tuple(part.strip() for part in location.split(",", 1))]
    elif "," not in location:
        suffixes = r"st|street|ave|avenue|rd|road|ln|lane|dr|drive|ct|court|blvd|boulevard|way|pl|place|ter|terrace|cir|circle|pkwy|parkway"
        for suffix in re.finditer(rf"\b(?:{suffixes})\.?\s+", location, re.IGNORECASE):
            street, city = location[:suffix.end()].strip(), location[suffix.end():].strip()
            # Post-street directions and unit numbers make the split ambiguous.
            if re.match(r"^(?:n|s|e|w|ne|nw|se|sw|north|south|east|west)\b", city, re.IGNORECASE):
                continue
            candidates.append((street, city))
    candidates = [(street, city) for street, city in candidates
                  if re.fullmatch(r"\d+\s+.+", street) and re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", city)]
    if len(candidates) != 1:
        return original
    street, city = candidates[0]
    return {"address": street, "city": city, "state": state.upper(), "zip_code": zip_code}


def explicit_numeric_units(field: str, value: Any) -> Any:
    """Remove an exact unit suffix only; alternatives, notes and fees stay invalid."""
    unit = r"(?:sq\.?\s*ft\.?|square\s+feet)" if field == "square_feet" else r"(?:/\s*month|PITI)" if field == "total_monthly_payment" else r"/\s*month" if field in {
        "monthly_insurance", "total_monthly_payment"} else None
    if unit:
        match = re.fullmatch(rf"\s*(\$?\s*\d[\d,]*(?:\.\d+)?)\s*{unit}\s*", text(value), re.IGNORECASE)
        if match:
            return match[1].replace("$", "").strip()
    return value


def confirmed_section_row(values: Sequence[Any]) -> bool:
    """Skip only known, single-cell section labels, never arbitrary text or addresses."""
    nonempty = [text(value) for value in values if text(value)]
    if len(nonempty) != 1:
        return False
    labels = {header_key(tab) for tab in INVENTORY_TABS}
    labels.update(header_key(part) for tab in REGIONAL_TABS for part in tab.split("/"))
    labels.update({"properties", "property inventory", "available properties", "sold properties", "for sale"})
    return header_key(nonempty[0]) in labels


def text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def first(record: Mapping[str, Any], fields: Sequence[str]) -> Any:
    return next((record[field] for field in fields if record.get(field) not in (None, "")), None)


def address_label(record: Mapping[str, Any]) -> str:
    street = text(first(record, ("address", "property_address")))
    if "," in street:
        return street
    return ", ".join(part for part in (street, text(record.get("city")), " ".join(
        part for part in (text(record.get("state")), text(first(record, ("zip_code", "zip")))) if part
    )) if part)


def address_key(record: Mapping[str, Any]) -> str:
    value = address_label(record)
    # A complete address is required for fallback; a street alone is not unique.
    if not re.search(r",\s*[A-Za-z]{2}\s+\d{5}(?:-\d{4})?\s*$", value):
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def comparable(field: str, value: Any) -> str:
    result = " ".join(text(value).split())
    if field in NUMERIC_FIELDS and result:
        try:
            number = Decimal(result.replace("$", "").replace(",", "").rstrip("%"))
            return str(number.normalize()) if number.is_finite() else result
        except InvalidOperation:
            return result
    if field == "availability":
        return {"sold": "sold / unavailable", "unavailable": "sold / unavailable", "filled": "sold / unavailable",
                "under contract": "pending", "hold": "paused", "ready": "available"}.get(result.casefold(), result.casefold())
    return result.casefold() if field == "insurance_included" else result


@dataclass(frozen=True)
class SheetProperty:
    tab: str
    row: int
    fields: Mapping[str, Any] = dataclass_field(repr=False)
    external_id: str = ""
    issues: tuple[str, ...] = ()
    marketing_status: str = "unknown"
    lockbox_observed: bool = False
    source_fields: tuple[Mapping[str, Any], ...] = dataclass_field(default=(), repr=False)


@dataclass(frozen=True)
class FieldChange:
    field: str
    current: str
    proposed: str


@dataclass(frozen=True)
class PreviewItem:
    address: str
    tab: str
    row: int
    property_id: str
    categories: tuple[str, ...]
    changes: tuple[FieldChange, ...] = ()
    reason: str = ""
    match_method: str = ""
    linked_deals: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    historical_occurrences: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SyncPreview:
    items: tuple[PreviewItem, ...]
    warnings: tuple[str, ...] = ()
    records_written: int = 0
    external_actions_started: int = 0

    @property
    def counts(self) -> dict[str, int]:
        return {category: sum(category in item.categories for item in self.items) for category in CATEGORIES}

    @property
    def review_reason_counts(self) -> dict[str, int]:
        return dict(Counter(reason for item in self.items if REVIEW in item.categories
                            for reason in set(item.review_reasons or (item.reason,))))


def regional_sheet_properties(worksheets: Sequence[Any], source_reference: str, *, verified_format_recovery: bool = False) -> tuple[SheetProperty, ...]:
    """Normalize only the explicit regional inventory and restriction tabs.

    The cache supplies identity only, never inventory facts or extra properties.
    """
    tabs = {sheet.tab_name: sheet for sheet in worksheets}
    missing = set(INVENTORY_TABS) - tabs.keys()
    if missing:
        raise ValueError("Inventory tabs are missing; a complete preview cannot be built.")
    cache = tabs.get("_REIBB_CACHE", ())
    cache_rows = [dict(zip(cache[0], row, strict=False)) for row in cache[1:]] if cache else []
    id_counts = Counter(text(row.get("external_id")) for row in cache_rows if text(row.get("external_id")))
    cache_addresses = Counter(address_key(row) for row in cache_rows if address_key(row))
    identities = {address_key(row): text(row["external_id"]) for row in cache_rows
                  if address_key(row) and text(row.get("external_id")) and id_counts[text(row["external_id"])] == 1
                  and cache_addresses[address_key(row)] == 1}
    cache_identity_fields = {address_key(row): row for row in cache_rows if address_key(row) and cache_addresses[address_key(row)] == 1}
    results = []
    for tab in tabs:
        if tab == "Sheet36":
            continue  # Explicitly excluded source, never inventory.
        if worksheet_classification(tabs[tab]) == "support/cache/system":
            continue  # Cache and confirmed non-property restriction lists are not inventory.
        context = V14PropertySourceContext(source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET, source_reference=source_reference, tab_name=tab)
        header_map: dict[str, int] = {}
        section_headers = []
        for number, values in enumerate(tabs[tab], 1):
            if not any(text(value) for value in values):
                continue
            address_column = header_map.get("property_address", 0)
            leading = text(values[address_column]) if address_column < len(values) else ""
            labels = [header_key(value) for value in values]
            if inventory_header(values):
                section_headers = list(values)
                header_map = {HEADER_FIELDS[label]: index for index, label in enumerate(labels) if label in HEADER_FIELDS}
                continue
            if leading.casefold() in {"address", "property", "property_address", "property address"}:
                continue
            if confirmed_section_row(values):
                header_map = {}  # A new section must confirm its own column layout.
                continue
            if not leading:
                continue  # Blank address cells are separators or ancillary notes, not inventory.
            if not re.match(r"^\d+\s+", leading):
                if tab not in INVENTORY_TABS:
                    continue  # Unknown non-property text is never promoted to inventory.
                results.append(SheetProperty(tab, number, {"address": "Unrecognized source row"}, issues=("Row layout needs review; no property facts inferred.",)))
                continue
            if not header_map:
                results.append(SheetProperty(tab, number, {"address": leading}, issues=("Column headers have not been confirmed for this property row.",)))
                continue
            mapped = {key: values[index] if index < len(values) else None for key, index in header_map.items()}
            from .property_source_fields import NUMBERS, read_source_fields
            source_fields = read_source_fields(section_headers, values, address_column=address_column)
            mapped["property_address"] = leading
            parts = sheet_address_parts(leading, verified_format_recovery=verified_format_recovery)
            if all(parts.values()):
                mapped.update(parts)
            for field in ("beds", "baths", "square_feet", "down_payment", "total_monthly_payment", "sales_price", "interest_rate",
                          "monthly_principal_interest", "monthly_insurance", "monthly_taxes"):
                if text(mapped.get(field)).casefold() in {"n/a", "na", "not applicable", "not-applicable"}:
                    mapped[field] = None  # Explicit absence is never zero or a guessed amount.
                elif verified_format_recovery:
                    mapped[field] = explicit_numeric_units(field, mapped.get(field))
            # Only use cache address components when the entire normalized address
            # is identical; never fill identity from region names or partial matches.
            cache_match = cache_identity_fields.get(header_key(leading))
            if cache_match:
                mapped.update({key: cache_match.get(key) for key in ("address", "city", "state", "zip")})
            mapped["availability"] = "Sold / Unavailable" if tab == "SOLD" else "Paused" if tab == "DO NOT SELL LIST" else "Available" if tab in REGIONAL_TABS else "Unknown"
            mapped["last_update"], date_issue = _normalize_source_date(mapped.get("last_update"))
            normalized = adapt_v14_property_row(mapped, context=context, sheet_row_number=number)
            layout_issues = () if "sales_price" in header_map else ("Sales price column is not confirmed; purchase price is not assumed to be asking price.",)
            if worksheet_classification(tabs[tab]) == "unknown / needs review":
                layout_issues += ("Source tab availability has not been verified; review only.",)
            errors = normalized.errors
            if not all(_address_parts(mapped).values()):
                address_errors = {"Stable source record ID is required; a row number is not sufficient.",
                                  "Address is required.", "City is required.", "State is required.", "Zip Code is required."}
                errors = ("Address is incomplete or ambiguous; explicit street, city, state and ZIP are required.",
                          *(error for error in errors if error not in address_errors))
            duplicate_issues = tuple(f"Repeated {detail['field']} header; verify which source cell applies."
                                     for detail in source_fields if detail["review"].startswith("Repeated field"))
            issues = (*errors, *layout_issues, *dict.fromkeys(duplicate_issues), *((date_issue,) if date_issue else ()))
            if normalized.normalized:
                fields = normalized.normalized.model_dump(mode="json")
                fields["asking_or_sale_price"] = fields.pop("total_price")
            else:
                # Retain identity even when a separate fact is malformed. This
                # prevents an existing property from also appearing as missing.
                fields = _address_parts(mapped)
                # Keep independently verified details even when another field is
                # invalid. Original import issues remain; evidence is not an import.
                clean = dict(mapped)
                for detail in source_fields:
                    key = detail["field"]
                    if detail["review"] or isinstance(detail["normalized"], dict):
                        clean[key] = None
                    elif key in NUMBERS:
                        clean[key] = detail["normalized"]
                clean["last_update"] = mapped.get("last_update")
                partial = adapt_v14_property_row(clean, context=context, sheet_row_number=number)
                if partial.normalized:
                    fields = partial.normalized.model_dump(mode="json")
                    fields["asking_or_sale_price"] = fields.pop("total_price")
            results.append(SheetProperty(tab, number, fields, identities.get(address_key(fields), ""), issues,
                                         lockbox_observed="lockbox_code" in header_map, source_fields=source_fields))
    return tuple(results)


def compare_properties(
    rows: Sequence[SheetProperty], properties: Sequence[Mapping[str, Any]], deals: Sequence[Mapping[str, Any]] = (),
    *, known_history_keys: Sequence[str] = (),
) -> SyncPreview:
    """Compute proposals only. Never create IDs, records, deals, or execution requests."""
    current_keys = {address_key(row.fields) for row in rows if row.tab in REGIONAL_TABS
                    and row.marketing_status in {"yellow", "white"} and address_key(row.fields)}
    history_keys = current_keys | set(known_history_keys)
    historical = {index for index, row in enumerate(rows) if row.tab == "SOLD" and address_key(row.fields) in history_keys}
    histories = {key: tuple((rows[i].tab, rows[i].row) for i in sorted(historical) if address_key(rows[i].fields) == key)
                 for key in current_keys}
    source_addresses = Counter(address_key(row.fields) for i, row in enumerate(rows) if i not in historical and address_key(row.fields))
    source_ids = Counter(row.external_id for i, row in enumerate(rows) if i not in historical and row.external_id)
    touched: set[int] = set()
    items = []
    source_incomplete = any(row.issues for row in rows)
    for row_index, row in enumerate(rows):
        key = address_key(row.fields)
        by_address = [i for i, prop in enumerate(properties) if key and address_key(prop) == key]
        by_id = [i for i, prop in enumerate(properties) if row.external_id and row.external_id == text(first(prop, ("external_id", "source_record_id")))]
        if row_index in historical:
            # Keep one result per source row for existing callers, but this row
            # cannot propose current fields, create another property, or age it.
            matched = by_address if len(by_address) == 1 and (not by_id or by_id == by_address) else []
            if matched and row.external_id and text(properties[matched[0]].get("external_id")) not in ("", row.external_id):
                matched = []
            items.append(PreviewItem(address_label(row.fields), row.tab, row.row,
                                     text(properties[matched[0]].get("id")) if matched else "", (HISTORY,),
                                     reason="Historical SOLD/unavailable occurrence retained; current inventory supplies current state. No closing is verified."))
            continue
        touched.update((*by_id, *by_address))
        problems = list(row.issues)
        related_ids = {candidate.external_id for candidate in rows if candidate.external_id and address_key(candidate.fields) == key}
        if len(related_ids) > 1:
            problems.append("Source IDs disagree for the same physical address; verify identity.")
        if row.external_id and any(candidate.external_id == row.external_id and address_key(candidate.fields) != key for candidate in rows):
            problems.append("Source ID identifies different addresses; verify identity.")
        if not key and not any(problem.startswith("Address is incomplete or ambiguous;") for problem in problems):
            problems.append("A complete normalized address is required to verify identity.")
        if (key and source_addresses[key] > 1) or (row.external_id and source_ids[row.external_id] > 1):
            problems.append("Duplicate sheet identity or address; no new property proposed.")
        if len(by_id) > 1 or len(by_address) > 1:
            problems.append("Multiple canonical properties match; choose the existing record before any future sync.")
        if by_id and by_address and set(by_id) != set(by_address):
            problems.append("The external ID and address identify different canonical properties.")
        chosen = by_id or by_address
        index = chosen[0] if len(chosen) == 1 else None
        existing = properties[index] if index is not None else {}
        if by_id and address_key(existing) != key:
            problems.append("The external ID matches but the address differs; verify the address correction.")
        if not by_id and by_address and row.external_id and text(existing.get("external_id")) not in ("", row.external_id):
            problems.append("The address matches but the existing external ID differs.")
        if index is not None and not text(existing.get("id")):
            problems.append("Canonical property ID is missing.")
        if existing.get("archived"):
            problems.append("The matching canonical property is archived; review its identity and lifecycle.")
        property_id = text(existing.get("id"))
        linked = tuple(text(deal.get("id")) for deal in deals if property_id and
                       text((deal.get("links") or {}).get("property_id") or deal.get("property_id")) == property_id)
        if problems:
            items.append(PreviewItem(address_label(row.fields), row.tab, row.row, property_id, (REVIEW,), reason=" ".join(problems),
                                     linked_deals=linked, review_reasons=tuple(problems), historical_occurrences=histories.get(key, ())))
            continue
        changes = tuple(FieldChange(field, text(first(existing, aliases)), text(row.fields.get(field)))
                        for field, aliases in FIELD_ALIASES.items()
                        if comparable(field, first(existing, aliases)) != comparable(field, row.fields.get(field)))
        categories = []
        if index is None:
            categories.append(NEW)
            if comparable("availability", row.fields.get("availability")) == "sold / unavailable":
                categories.append(SOLD)
        else:
            for change in changes:
                category = PRICE if change.field == "asking_or_sale_price" else TERMS if change.field in TERM_FIELDS else STATUS if change.field == "availability" else OTHER
                if category not in categories:
                    categories.append(category)
                if change.field == "availability" and comparable("availability", change.proposed) == "sold / unavailable":
                    categories.append(SOLD)
        blank_changes = any(change.current and not change.proposed for change in changes)
        if blank_changes:
            categories.append(REVIEW)
        items.append(PreviewItem(address_label(row.fields), row.tab, row.row, property_id, tuple(categories), changes,
                                 "Source fields are blank; review before any future clearing." if blank_changes else "",
                                 "External ID" if by_id else "Normalized address" if by_address else "No existing match", linked,
                                 historical_occurrences=histories.get(key, ())))
    for index, prop in enumerate(properties):
        if index not in touched:
            items.append(PreviewItem(address_label(prop) or "Unidentified canonical property", "", 0, text(prop.get("id")),
                                     (REVIEW,) if source_incomplete else (MISSING,), reason=(
                                         "Unmatched; invalid sheet rows prevent confirming absence." if source_incomplete else
                                         "Not found in the inspected inventory tabs. It may be outside this sheet's scope. Never treated as sold or deleted."
                                     )))
    return SyncPreview(tuple(items), (
        "Regional availability is inferred from tab membership. Confirm these mappings before any future sync.",
        "SOLD means listed on the sheet as sold/unavailable. It does not independently verify a closing or change a deal stage.",
    ))


def read_canonical_records(client: Any, entity: str) -> list[dict[str, Any]]:
    """Read the existing CRM bucket completely, without bucket creation or writes."""
    if entity not in {"properties", "deals", "contacts", "communications", "tasks", "activities"}:
        raise ValueError("Unsupported preview source")
    bucket = client.storage.from_("commandcore-crm-core")
    records = []
    offset = 0
    while True:
        batch = bucket.list(entity, {"limit": 500, "offset": offset, "sortBy": {"column": "name", "order": "asc"}})
        if not isinstance(batch, list):
            raise ValueError("Canonical source could not be read completely")
        for obj in batch:
            name = text(obj.get("name"))
            if not name.endswith(".json"):
                continue
            record = json.loads(bucket.download(f"{entity}/{name}"))
            if not isinstance(record, dict):
                raise ValueError("Invalid canonical record")
            records.append(record)
        if len(batch) < 500:
            return records
        offset += 500


def load_sync_preview(secrets: Mapping[str, Any]) -> SyncPreview:
    from supabase import create_client

    from .property_baseline import load_baseline_source

    rows, _ = load_baseline_source(secrets, include_marketing=True)
    client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
    properties = read_canonical_records(client, "properties")
    deals = read_canonical_records(client, "deals")
    return compare_properties(rows, properties, deals)
