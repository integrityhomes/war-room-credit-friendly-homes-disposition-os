from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from .facebook_groups import (
    DEFAULT_GROUP_COOLDOWN_DAYS,
    FacebookGroupLedger,
    FacebookGroupRecord,
    upsert_group,
)

MAX_IMPORT_ROWS = 500


@dataclass(frozen=True, slots=True)
class FacebookGroupImportRow:
    row_number: int
    name: str
    group_url: str
    cooldown_days: int
    notes: str
    action: str
    existing_group_id: str | None = None
    issue: str = ""


@dataclass(frozen=True, slots=True)
class FacebookGroupImportResult:
    ledger: FacebookGroupLedger
    added: int
    updated: int
    skipped: int


def _normalize_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    normalized = cleaned if "://" in cleaned else f"https://{cleaned}"
    return normalized.rstrip("/")


def _facebook_group_id(group_url: str) -> str:
    match = re.search(r"/groups/([^/?#]+)", group_url, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _inferred_name(group_url: str) -> str:
    group_id = _facebook_group_id(group_url)
    return f"Facebook Group {group_id}" if group_id else "Facebook Group"


def _parse_cooldown(value: str | int | None, default: int) -> int:
    raw = str(value or "").strip()
    if not raw:
        return default
    parsed = int(raw)
    if not 1 <= parsed <= 90:
        raise ValueError("Cooldown days must be between 1 and 90")
    return parsed


def _existing_by_url(ledger: FacebookGroupLedger, group_url: str) -> FacebookGroupRecord | None:
    wanted = _normalize_url(group_url).casefold()
    if not wanted:
        return None
    return next(
        (
            group
            for group in ledger.groups
            if _normalize_url(group.group_url).casefold() == wanted
        ),
        None,
    )


def _existing_by_name(ledger: FacebookGroupLedger, name: str) -> FacebookGroupRecord | None:
    wanted = name.strip().casefold()
    return next(
        (group for group in ledger.groups if group.name.strip().casefold() == wanted),
        None,
    )


def _validated_row(
    ledger: FacebookGroupLedger,
    *,
    row_number: int,
    name: str,
    group_url: str,
    cooldown_days: int,
    notes: str,
    seen_urls: set[str],
    seen_names: set[str],
) -> FacebookGroupImportRow:
    normalized_url = _normalize_url(group_url)
    final_name = name.strip() or _inferred_name(normalized_url)
    final_notes = notes.strip()[:1000]

    try:
        validated = FacebookGroupRecord(
            name=final_name,
            group_url=normalized_url,
            cooldown_days=cooldown_days,
            notes=final_notes,
        )
    except ValidationError as exc:
        return FacebookGroupImportRow(
            row_number=row_number,
            name=final_name,
            group_url=normalized_url,
            cooldown_days=cooldown_days,
            notes=final_notes,
            action="Skip",
            issue=str(exc.errors()[0].get("msg", "Invalid group record")),
        )

    url_key = validated.group_url.casefold()
    name_key = validated.name.casefold()
    if url_key and url_key in seen_urls:
        return FacebookGroupImportRow(
            row_number=row_number,
            name=validated.name,
            group_url=validated.group_url,
            cooldown_days=validated.cooldown_days,
            notes=validated.notes,
            action="Skip",
            issue="Duplicate Facebook URL inside this import batch.",
        )
    if name_key in seen_names:
        return FacebookGroupImportRow(
            row_number=row_number,
            name=validated.name,
            group_url=validated.group_url,
            cooldown_days=validated.cooldown_days,
            notes=validated.notes,
            action="Skip",
            issue="Duplicate group name inside this import batch.",
        )

    if url_key:
        seen_urls.add(url_key)
    seen_names.add(name_key)

    existing = _existing_by_url(ledger, validated.group_url) or _existing_by_name(
        ledger,
        validated.name,
    )
    return FacebookGroupImportRow(
        row_number=row_number,
        name=validated.name,
        group_url=validated.group_url,
        cooldown_days=validated.cooldown_days,
        notes=validated.notes,
        action="Update" if existing else "Add",
        existing_group_id=existing.group_id if existing else None,
    )


def parse_pasted_groups(
    text: str,
    ledger: FacebookGroupLedger,
    *,
    default_cooldown_days: int = DEFAULT_GROUP_COOLDOWN_DAYS,
) -> list[FacebookGroupImportRow]:
    rows: list[FacebookGroupImportRow] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()

    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if len(rows) >= MAX_IMPORT_ROWS:
            break

        delimiter = "|" if "|" in line else "\t" if "\t" in line else None
        if delimiter:
            parts = [part.strip() for part in line.split(delimiter)]
        elif line.lower().startswith(("https://", "http://", "facebook.com", "www.facebook.com")):
            parts = ["", line]
        else:
            parts = [line, ""]

        name = parts[0] if parts else ""
        group_url = parts[1] if len(parts) > 1 else ""
        try:
            cooldown = _parse_cooldown(
                parts[2] if len(parts) > 2 else None,
                default_cooldown_days,
            )
            issue = ""
        except (TypeError, ValueError) as exc:
            cooldown = default_cooldown_days
            issue = str(exc)
        notes = parts[3] if len(parts) > 3 else ""

        row = _validated_row(
            ledger,
            row_number=row_number,
            name=name,
            group_url=group_url,
            cooldown_days=cooldown,
            notes=notes,
            seen_urls=seen_urls,
            seen_names=seen_names,
        )
        if issue and row.action != "Skip":
            row = FacebookGroupImportRow(
                row_number=row.row_number,
                name=row.name,
                group_url=row.group_url,
                cooldown_days=row.cooldown_days,
                notes=row.notes,
                action="Skip",
                issue=issue,
            )
        rows.append(row)

    return rows


def parse_csv_groups(
    content: bytes | str,
    ledger: FacebookGroupLedger,
    *,
    default_cooldown_days: int = DEFAULT_GROUP_COOLDOWN_DAYS,
) -> list[FacebookGroupImportRow]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    normalized_fields = {field.strip().lower(): field for field in reader.fieldnames if field}
    name_field = normalized_fields.get("group_name") or normalized_fields.get("name")
    url_field = normalized_fields.get("group_url") or normalized_fields.get("url")
    cooldown_field = normalized_fields.get("cooldown_days") or normalized_fields.get("cooldown")
    notes_field = normalized_fields.get("notes") or normalized_fields.get("rules")

    rows: list[FacebookGroupImportRow] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()
    for row_number, source in enumerate(reader, start=2):
        if len(rows) >= MAX_IMPORT_ROWS:
            break
        name = str(source.get(name_field, "") if name_field else "")
        group_url = str(source.get(url_field, "") if url_field else "")
        notes = str(source.get(notes_field, "") if notes_field else "")
        try:
            cooldown = _parse_cooldown(
                source.get(cooldown_field) if cooldown_field else None,
                default_cooldown_days,
            )
            issue = ""
        except (TypeError, ValueError) as exc:
            cooldown = default_cooldown_days
            issue = str(exc)

        row = _validated_row(
            ledger,
            row_number=row_number,
            name=name,
            group_url=group_url,
            cooldown_days=cooldown,
            notes=notes,
            seen_urls=seen_urls,
            seen_names=seen_names,
        )
        if issue and row.action != "Skip":
            row = FacebookGroupImportRow(
                row_number=row.row_number,
                name=row.name,
                group_url=row.group_url,
                cooldown_days=row.cooldown_days,
                notes=row.notes,
                action="Skip",
                issue=issue,
            )
        rows.append(row)
    return rows


def import_preview_rows(rows: Iterable[FacebookGroupImportRow]) -> list[dict[str, str | int]]:
    return [
        {
            "Row": row.row_number,
            "Action": row.action,
            "Group Name": row.name,
            "Facebook URL": row.group_url or "—",
            "Cooldown": row.cooldown_days,
            "Notes": row.notes or "—",
            "Issue": row.issue or "—",
        }
        for row in rows
    ]


def apply_group_import(
    ledger: FacebookGroupLedger,
    rows: Iterable[FacebookGroupImportRow],
) -> FacebookGroupImportResult:
    updated = ledger
    added = 0
    changed = 0
    skipped = 0

    for row in rows:
        if row.action == "Skip":
            skipped += 1
            continue
        updated = upsert_group(
            updated,
            name=row.name,
            group_url=row.group_url,
            cooldown_days=row.cooldown_days,
            notes=row.notes,
            group_id=row.existing_group_id,
        )
        if row.action == "Update":
            changed += 1
        else:
            added += 1

    return FacebookGroupImportResult(
        ledger=updated,
        added=added,
        updated=changed,
        skipped=skipped,
    )


def csv_template() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["group_name", "group_url", "cooldown_days", "notes"])
    writer.writerow(
        [
            "Owner Financing Homes for Sale",
            "https://www.facebook.com/groups/1305510733671893",
            7,
            "Owner-finance posts allowed.",
        ]
    )
    return output.getvalue().encode("utf-8")
