"""Aggregate workbook evidence, never a second property store or import gate."""
import re
from collections import Counter

from .property_sync_preview import (
    HEADER_FIELDS,
    INVENTORY_TABS,
    REGIONAL_TABS,
    REVIEW,
    address_key,
    compare_properties,
    confirmed_section_row,
    header_key,
    inventory_header,
    sheet_address_parts,
    text,
    worksheet_classification,
)


class CoveredRows(tuple):
    def __new__(cls, rows, coverage):
        instance = super().__new__(cls, rows)
        instance.coverage = coverage
        return instance


class Coverage(dict):
    """Ephemeral matching keys are not serialized into the aggregate checkpoint."""

    identity_keys: frozenset[str]
    legitimate_keys: frozenset[str]
    row_keys: tuple[str, ...]


def address_columns(worksheet):
    """Explicit per-section address columns; legacy regional layout uses column A."""
    column = 0
    result = {}
    for number, values in enumerate(worksheet, 1):
        labels = [header_key(value) for value in values]
        if inventory_header(values):
            explicit = [i for i, label in enumerate(labels) if HEADER_FIELDS.get(label) == "property_address"]
            column = explicit[0] if len(explicit) == 1 else 0
        elif confirmed_section_row(values):
            column = 0
        result[number] = column
    return result


def source_coverage(worksheets, rows):
    """Count source candidates independently of fact-validation and CRM membership.

    A number-leading address cell is a candidate, not a verified property. No
    mailing addresses, lockbox cells, notes or raw identity values leave here.
    """
    by_location = {(row.tab, row.row): row for row in rows}
    keys = Counter()
    legitimate_keys = set()
    row_keys = []
    lifecycle_counts = Counter()
    lifecycle_keys = {kind: set() for kind in ("yellow", "white", "sold", "unknown")}
    tabs = []
    for ws in worksheets:
        classification = worksheet_classification(ws)
        colors = Counter()
        states = Counter()
        sections = []
        tab_keys = Counter()
        incomplete = 0
        columns = address_columns(ws)
        for number, values in enumerate(ws, 1):
            if classification == "support/cache/system":
                continue
            if inventory_header(values):
                sections.append(number)
                continue
            col = columns[number]
            leading = text(values[col]) if col < len(values) else ""
            if not re.match(r"^\d+\s+", leading):
                continue
            row = by_location.get((ws.tab_name, number))
            color = row.marketing_status if row else "unknown"
            colors[color] += 1
            lifecycle = ("sold" if ws.tab_name == "SOLD" else color
                         if classification == "property/inventory" else "unknown")
            lifecycle_counts[lifecycle] += 1
            parts = sheet_address_parts(leading)
            key = address_key(parts) if all(parts.values()) else ""
            if key:
                tab_keys[key] += 1
                keys[key] += 1
                row_keys.append(key)
                lifecycle_keys[lifecycle].add(key)
                if classification == "property/inventory":
                    legitimate_keys.add(key)
                states[parts["state"]] += 1
            else:
                incomplete += 1
        tabs.append({
            "tab": ws.tab_name, "classification": classification, "candidate_rows": sum(colors.values()),
            "colors": dict(colors), "unique_complete_addresses": len(tab_keys),
            "unresolved_address_rows": incomplete, "states": dict(states),
            "header_rows": sections, "header_blocks": len(sections),
            "source_classification": "identity cache" if ws.tab_name == "_REIBB_CACHE" else
            "support data" if classification == "support/cache/system" else
            "sold / unavailable" if ws.tab_name == "SOLD" else
            "regional inventory" if ws.tab_name in REGIONAL_TABS else "unverified / non-inventory",
            "previously_outside_inventory_list": ws.tab_name not in (*INVENTORY_TABS, "_REIBB_CACHE"),
        })
    totals = Counter()
    for tab in tabs:
        totals.update(tab["colors"])
    result = Coverage({
        "tabs": tabs, "tab_count": len(tabs), "candidate_rows": sum(totals.values()),
        "source_colors": dict(totals), "unique_complete_addresses": len(keys),
        "duplicate_address_rows": sum(count - 1 for count in keys.values()),
        "unresolved_address_rows": sum(tab["unresolved_address_rows"] for tab in tabs),
        "header_blocks": sum(tab["header_blocks"] for tab in tabs),
        "sold_candidate_rows": sum(tab["candidate_rows"] for tab in tabs if tab["source_classification"] == "sold / unavailable"),
        "counts_are_candidates_not_import_approval": True,
        "legitimate_property_tabs": sum(tab["classification"] == "property/inventory" for tab in tabs),
        "legitimate_unique_complete_addresses": len(legitimate_keys),
        "lifecycle_candidate_rows": dict(lifecycle_counts),
        "lifecycle_unique_complete_addresses": {kind: len(values) for kind, values in lifecycle_keys.items()},
    })
    result.identity_keys = frozenset(keys)
    result.legitimate_keys = frozenset(legitimate_keys)
    result.row_keys = tuple(row_keys)
    return result


def reconcile_coverage(coverage, rows, properties):
    from .property_marketing_eligibility import compare_source_identity
    from .property_sync_preview import HISTORY
    identities = compare_source_identity(rows, properties)
    preview = compare_properties(rows, properties)
    canonical_keys = {address_key(prop) for prop in properties}
    return {**coverage, "canonical_properties": len(properties),
            "historical_occurrences_retained": sum(HISTORY in item.categories for item in preview.items),
            "current_yellow_with_history": len({address_key(row.fields) for row, item in zip(rows, preview.items, strict=False)
                                                 if row.marketing_status == "yellow" and item.historical_occurrences}),
            "complete_source_addresses_outside_canonical": len(coverage.identity_keys - canonical_keys),
            "legitimate_complete_addresses_outside_canonical": len(coverage.legitimate_keys - canonical_keys),
            "source_unique_addresses_in_canonical": len(coverage.identity_keys & canonical_keys),
            "source_address_rows_in_canonical": sum(key in canonical_keys for key in coverage.row_keys),
            "property_candidate_review_rows": sum(REVIEW in item.categories and
                                                  bool(re.match(r"^\d+\s+", text(row.fields.get("address"))))
                                                  for row, item in zip(rows, preview.items, strict=False)),
            "eligible_canonical_yellow": len({item.property_id for row, item in zip(rows, identities.items, strict=False)
                                               if item.property_id and REVIEW not in item.categories and row.tab in REGIONAL_TABS and row.marketing_status == 'yellow'}),
            "accepted_new": sum("NEW PROPERTY" in item.categories and REVIEW not in item.categories for item in preview.items),
            "needs_review": sum(REVIEW in item.categories for item in preview.items)}


def coverage_lines(coverage):
    if not coverage:
        return ("Full-workbook source coverage has not yet been verified in this checkpoint.",)
    return (
        f"Workbook coverage: {coverage['tab_count']} tabs inspected; {coverage['source_colors'].get('yellow', 0)} yellow source candidates. "
        "Source candidates include repeated and unresolved rows; they are not the current marketed-property count.",
        f"{coverage['unresolved_address_rows']} source rows have unresolved addresses. Source totals are not import approval or verified unique inventory totals.",
        "Historical SOLD occurrences do not override verified current yellow/white inventory; competing current rows still require review.",
    )
