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
    sheet_address_parts,
    text,
)


class CoveredRows(tuple):
    def __new__(cls, rows, coverage):
        instance = super().__new__(cls, rows)
        instance.coverage = coverage
        return instance


class Coverage(dict):
    """Ephemeral matching keys are not serialized into the aggregate checkpoint."""

    identity_keys: frozenset[str]


def address_columns(worksheet):
    """Explicit per-section address columns; legacy regional layout uses column A."""
    column = 0
    result = {}
    for number, values in enumerate(worksheet, 1):
        labels = [header_key(value) for value in values]
        if sum(label in HEADER_FIELDS for label in labels) >= 3:
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
    tabs = []
    for ws in worksheets:
        colors = Counter()
        states = Counter()
        sections = []
        tab_keys = Counter()
        incomplete = 0
        columns = address_columns(ws)
        for number, values in enumerate(ws, 1):
            if ws.tab_name == "_REIBB_CACHE":
                continue
            labels = [header_key(value) for value in values]
            if sum(label in HEADER_FIELDS for label in labels) >= 3:
                sections.append(number)
                continue
            col = columns[number]
            leading = text(values[col]) if col < len(values) else ""
            if not re.match(r"^\d+\s+", leading):
                continue
            row = by_location.get((ws.tab_name, number))
            colors[row.marketing_status if row else "unknown"] += 1
            parts = sheet_address_parts(leading)
            key = address_key(parts) if all(parts.values()) else ""
            if key:
                tab_keys[key] += 1
                keys[key] += 1
                states[parts["state"]] += 1
            else:
                incomplete += 1
        tabs.append({
            "tab": ws.tab_name, "candidate_rows": sum(colors.values()),
            "colors": dict(colors), "unique_complete_addresses": len(tab_keys),
            "unresolved_address_rows": incomplete, "states": dict(states),
            "header_rows": sections, "header_blocks": len(sections),
            "source_classification": "identity cache" if ws.tab_name == "_REIBB_CACHE" else
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
    })
    result.identity_keys = frozenset(keys)
    return result


def reconcile_coverage(coverage, rows, properties):
    preview = compare_properties(rows, properties)
    canonical_keys = {address_key(prop) for prop in properties}
    return {**coverage, "canonical_properties": len(properties),
            "complete_source_addresses_outside_canonical": len(coverage.identity_keys - canonical_keys),
            "eligible_canonical_yellow": sum(bool(item.property_id) and REVIEW not in item.categories and
                                             row.marketing_status == "yellow" and row.fields.get("availability") == "Available"
                                             for row, item in zip(rows, preview.items, strict=False)),
            "accepted_new": sum("NEW PROPERTY" in item.categories and REVIEW not in item.categories for item in preview.items),
            "needs_review": sum(REVIEW in item.categories for item in preview.items)}


def coverage_lines(coverage):
    if not coverage:
        return ("Full-workbook source coverage has not yet been verified in this checkpoint.",)
    return (
        f"Workbook coverage: {coverage['tab_count']} tabs inspected; {coverage['source_colors'].get('yellow', 0)} yellow source candidates. "
        f"Only {coverage.get('eligible_canonical_yellow', 0)} validated canonical properties are eligible for marketing-age tracking.",
        f"{coverage['unresolved_address_rows']} source rows have unresolved addresses. Source totals are not import approval or verified unique inventory totals.",
    )
