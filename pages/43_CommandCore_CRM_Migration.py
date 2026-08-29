from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore CRM Migration", page_icon="📥", layout="wide")

STAGING_SERVICE = "commandcore-crm-import-staging"
COMMIT_SERVICE = "commandcore-crm-import-commit"
RECONCILIATION_SERVICE = "commandcore-crm-reconciliation"
ENTITY_OPTIONS = [
    "Contacts",
    "Properties",
    "Deals",
    "Activities",
    "Communications",
    "Tasks",
    "Offers",
    "Documents",
    "Transactions",
]
ENTITY_KEYS = [item.lower() for item in ENTITY_OPTIONS]


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore CRM Migration")
    with st.form("commandcore_crm_migration_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


def text(value: Any) -> str:
    return str(value or "").strip()


def service_config() -> tuple[str, str]:
    url = text(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    key = text(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
    return url, key


def call_service(service: str, payload: dict[str, Any]) -> dict[str, Any]:
    url, key = service_config()
    req = request.Request(
        f"{url}/functions/v1/{service}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=90) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{service} returned HTTP {exc.code}: {detail[:500]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Could not reach {service}: {exc.reason}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{service} returned an unexpected response.")
    return parsed


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def rows_from_upload(uploaded: Any) -> list[dict[str, Any]]:
    raw = uploaded.getvalue()
    name = text(uploaded.name).lower()
    if name.endswith(".json"):
        parsed = json.loads(raw.decode("utf-8-sig"))
        if isinstance(parsed, dict):
            parsed = parsed.get("rows", parsed.get("records", parsed.get("data", [])))
        if not isinstance(parsed, list):
            raise ValueError("JSON export must contain a list of records or a rows/records/data list.")
        return [row for row in parsed if isinstance(row, dict)]

    frame = pd.read_csv(io.BytesIO(raw), dtype=object, keep_default_na=False)
    return [
        {str(key): clean_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def table_rows(staged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in staged:
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        output.append(
            {
                "row": row.get("row_number"),
                "entity": row.get("entity"),
                "confidence": row.get("confidence"),
                "ready": row.get("ready_for_import") is True,
                "duplicate": row.get("duplicate_in_file") is True,
                "name/title": record.get("name") or record.get("title") or "",
                "phone": record.get("phone") or "",
                "email": record.get("email") or "",
                "address": record.get("address") or "",
                "status": record.get("status") or record.get("stage") or "",
                "external_id": record.get("external_id") or "",
            }
        )
    return output


def default_approvals(staged: list[dict[str, Any]]) -> dict[int, bool]:
    return {
        index: row.get("ready_for_import") is True and row.get("duplicate_in_file") is not True
        for index, row in enumerate(staged)
    }


def commit_rows(staged: list[dict[str, Any]], approvals: dict[int, bool]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, staged_row in enumerate(staged):
        record = staged_row.get("record") if isinstance(staged_row.get("record"), dict) else {}
        rows.append(
            {
                "approved": approvals.get(index, False),
                "entity": staged_row.get("entity"),
                "identity_key": staged_row.get("duplicate_key") or record.get("external_id"),
                "record": record,
                "seller_identity_key": record.get("seller_identity_key"),
                "contact_identity_key": record.get("contact_identity_key"),
                "property_identity_key": record.get("property_identity_key"),
                "deal_identity_key": record.get("deal_identity_key"),
            }
        )
    return rows


def payload_signature(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def external_id_hash(values: set[str]) -> str:
    canonical = "\n".join(sorted({text(value).lower() for value in values if text(value)}))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture_source_export_batch(source: str, uploaded: Any, staged: list[dict[str, Any]]) -> None:
    source_key = text(source).lower()
    current_source = text(st.session_state.get("crm_migration_manifest_source")).lower()
    if current_source and current_source != source_key:
        st.session_state.crm_migration_source_batches = {}
        for entity_key in ENTITY_KEYS:
            st.session_state.pop(f"crm_source_zero_{entity_key}", None)
        st.session_state.pop("crm_migration_reconciliation_preview", None)
        st.session_state.pop("crm_migration_reconciliation_result", None)
    st.session_state.crm_migration_manifest_source = source_key

    batches = st.session_state.get("crm_migration_source_batches")
    if not isinstance(batches, dict):
        batches = {}

    ids_by_entity: dict[str, set[str]] = {entity_key: set() for entity_key in ENTITY_KEYS}
    for staged_row in staged:
        entity_key = text(staged_row.get("entity")).lower()
        record = staged_row.get("record") if isinstance(staged_row.get("record"), dict) else {}
        external_id = text(record.get("external_id"))
        if entity_key in ids_by_entity and external_id:
            ids_by_entity[entity_key].add(external_id)

    batch_id = hashlib.sha256(uploaded.getvalue()).hexdigest()
    batches[batch_id] = {
        "file_name": text(uploaded.name),
        "source": source_key,
        "entity_ids": {key: sorted(values) for key, values in ids_by_entity.items() if values},
    }
    st.session_state.crm_migration_source_batches = batches
    st.session_state.pop("crm_migration_reconciliation_preview", None)
    st.session_state.pop("crm_migration_reconciliation_result", None)


def accumulated_source_ids() -> dict[str, set[str]]:
    accumulated = {entity_key: set() for entity_key in ENTITY_KEYS}
    batches = st.session_state.get("crm_migration_source_batches")
    if not isinstance(batches, dict):
        return accumulated
    for batch in batches.values():
        if not isinstance(batch, dict):
            continue
        entity_ids = batch.get("entity_ids") if isinstance(batch.get("entity_ids"), dict) else {}
        for entity_key in ENTITY_KEYS:
            values = entity_ids.get(entity_key) if isinstance(entity_ids.get(entity_key), list) else []
            accumulated[entity_key].update(text(value) for value in values if text(value))
    return accumulated


def build_source_manifest(source: str, real_source_export: bool) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ids_by_entity = accumulated_source_ids()
    entities: dict[str, dict[str, Any]] = {}
    status_rows: list[dict[str, Any]] = []
    incomplete = False

    for entity_key in ENTITY_KEYS:
        ids = ids_by_entity[entity_key]
        zero_confirmed = bool(st.session_state.get(f"crm_source_zero_{entity_key}", False))
        covered = bool(ids) or zero_confirmed
        if not covered:
            incomplete = True
        count = len(ids) if ids else 0
        status_rows.append(
            {
                "Entity": entity_key.title(),
                "Source Records": count if covered else "Not accounted for",
                "Coverage": "Export staged" if ids else "Confirmed zero" if zero_confirmed else "Missing",
            }
        )
        if covered:
            entities[entity_key] = {
                "count": count,
                "external_id_sha256": external_id_hash(ids),
            }

    if incomplete:
        return None, status_rows
    return {
        "source_system": text(source).lower(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "real_source_export": real_source_export,
        "entities": entities,
    }, status_rows


def reconciliation_rows(preview: dict[str, Any]) -> list[dict[str, Any]]:
    entities = preview.get("entities") if isinstance(preview.get("entities"), dict) else {}
    rows: list[dict[str, Any]] = []
    for entity_key in ENTITY_KEYS:
        item = entities.get(entity_key) if isinstance(entities.get(entity_key), dict) else {}
        rows.append(
            {
                "Entity": entity_key.title(),
                "Source": item.get("source_count"),
                "CommandCore": item.get("commandcore_count"),
                "Count Match": item.get("count_match") is True,
                "ID Fingerprint Match": item.get("external_id_hash_match") is True,
                "Exact Match": item.get("exact_match") is True,
            }
        )
    return rows


def safe_preview_for_display(preview: dict[str, Any]) -> dict[str, Any]:
    safe = dict(preview)
    safe.pop("preview_token", None)
    return safe


def preview_is_apply_ready(preview: Any) -> bool:
    return (
        isinstance(preview, dict)
        and preview.get("ok") is True
        and preview.get("apply_guard_ready") is True
        and isinstance(preview.get("preview_token"), str)
        and len(text(preview.get("preview_token"))) > 40
        and int(preview.get("invalid_count", 0) or 0) == 0
        and int(preview.get("duplicate_count", 0) or 0) == 0
    )


require_password()

if st.sidebar.button("Log out", key="commandcore_crm_migration_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore CRM Migration")
st.caption(
    "Upload CRM exports, let CommandCore stage and map them, review anything uncertain, run no-write previews, "
    "and import only deliberately approved records. Source reconciliation stays separate from import execution."
)

source = st.text_input("Migration source", value="rei-blackbook", help="Used to preserve original source identity during migration.")
entity = st.selectbox("Export type", ["Auto detect", *ENTITY_OPTIONS], index=0)
uploaded = st.file_uploader("Upload CRM export", type=["csv", "json"])

if uploaded and st.button("Stage & Map Export", type="primary"):
    try:
        rows = rows_from_upload(uploaded)
        if not rows:
            st.error("The export did not contain any usable rows.")
        else:
            requested = "" if entity == "Auto detect" else entity.lower()
            result = call_service(
                STAGING_SERVICE,
                {"source": source, "entity": requested, "rows": rows},
            )
            staged_result = result.get("staged", []) if isinstance(result.get("staged"), list) else []
            st.session_state.crm_migration_stage = result
            st.session_state.crm_migration_approvals = default_approvals(staged_result)
            capture_source_export_batch(text(result.get("source") or source), uploaded, staged_result)
            st.session_state.pop("crm_migration_preview", None)
            st.session_state.pop("crm_migration_preview_signature", None)
            st.session_state.pop("crm_migration_commit_result", None)
            st.success(f"Staged {result.get('staged_rows', 0)} rows. No CRM records were written.")
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        st.error(str(exc))

stage = st.session_state.get("crm_migration_stage")
if not isinstance(stage, dict):
    st.stop()

staged = stage.get("staged") if isinstance(stage.get("staged"), list) else []
summary_cols = st.columns(4)
summary_cols[0].metric("Input Rows", int(stage.get("input_rows", 0) or 0))
summary_cols[1].metric("Ready", int(stage.get("ready_for_import", 0) or 0))
summary_cols[2].metric("Needs Review", int(stage.get("needs_review", 0) or 0))
summary_cols[3].metric("Duplicate Groups", len(stage.get("duplicate_groups", [])))

if stage.get("duplicate_groups"):
    with st.expander("Duplicate groups found", expanded=True):
        st.dataframe(pd.DataFrame(stage.get("duplicate_groups", [])), use_container_width=True, hide_index=True)

st.subheader("Staged Records")
st.dataframe(pd.DataFrame(table_rows(staged)), use_container_width=True, hide_index=True)

approvals = st.session_state.get("crm_migration_approvals")
if not isinstance(approvals, dict):
    approvals = default_approvals(staged)
    st.session_state.crm_migration_approvals = approvals

st.subheader("Review & Approval")
st.caption("Clean, non-duplicate rows start approved. Anything uncertain stays off until someone reviews it.")
for index, row in enumerate(staged):
    record = row.get("record") if isinstance(row.get("record"), dict) else {}
    title = (
        text(record.get("name"))
        or text(record.get("title"))
        or text(record.get("address"))
        or text(record.get("external_id"))
        or f"Row {row.get('row_number', index + 1)}"
    )
    label = f"Approve row {row.get('row_number', index + 1)} — {row.get('entity', 'unknown')} — {title}"
    approvals[index] = st.checkbox(label, value=bool(approvals.get(index, False)), key=f"crm_migration_approve_{index}")
    if row.get("duplicate_in_file") is True:
        st.warning("Duplicate found in this export. Review before approving.")
    elif row.get("confidence") == "low" or row.get("ready_for_import") is not True:
        st.warning("Low-confidence or incomplete mapping. Review before approving.")

st.session_state.crm_migration_approvals = approvals
payload_rows = commit_rows(staged, approvals)
approved_count = sum(1 for row in payload_rows if row.get("approved") is True)
current_payload_signature = payload_signature(payload_rows)

preview = st.session_state.get("crm_migration_preview")
stored_preview_signature = text(st.session_state.get("crm_migration_preview_signature"))
if isinstance(preview, dict) and stored_preview_signature != current_payload_signature:
    st.session_state.pop("crm_migration_preview", None)
    st.session_state.pop("crm_migration_preview_signature", None)
    preview = None
    st.info("The approved migration rows changed. The old preview was cleared; run a fresh no-write preview.")

st.divider()
st.subheader("Live Import Preview")
st.write(f"Approved for preview: **{approved_count}** of **{len(payload_rows)}** staged rows.")
st.caption("Preview checks the approved rows against the live CommandCore CRM and writes nothing.")

if st.button("Run Fresh No-Write Preview", type="primary", use_container_width=True, disabled=approved_count == 0):
    try:
        preview = call_service(COMMIT_SERVICE, {"rows": payload_rows, "apply": False})
        st.session_state.crm_migration_preview = preview
        st.session_state.crm_migration_preview_signature = current_payload_signature
        if preview_is_apply_ready(preview):
            st.success(
                "Preview ready. "
                f"Would create {int(preview.get('would_create', 0) or 0)} and update {int(preview.get('would_update', 0) or 0)} records."
            )
        else:
            st.warning("Preview completed, but the import is not ready to apply. Resolve the reported issues and preview again.")
    except RuntimeError as exc:
        st.error(str(exc))

preview = st.session_state.get("crm_migration_preview")
apply_ready = preview_is_apply_ready(preview)
would_update = int(preview.get("would_update", 0) or 0) if isinstance(preview, dict) else 0

if isinstance(preview, dict):
    preview_cols = st.columns(4)
    preview_cols[0].metric("Would Create", int(preview.get("would_create", 0) or 0))
    preview_cols[1].metric("Would Update", would_update)
    preview_cols[2].metric("Invalid", int(preview.get("invalid_count", 0) or 0))
    preview_cols[3].metric("Duplicates", int(preview.get("duplicate_count", 0) or 0))
    expires = text(preview.get("preview_token_expires_at"))
    if expires:
        st.caption(f"This guarded preview expires at {expires}. If it expires or the live CRM changes, CommandCore will require a new preview.")
    with st.expander("Latest preview details"):
        st.json(safe_preview_for_display(preview))

st.divider()
st.subheader("Apply Approved Migration")
if not apply_ready:
    st.info("Run a fresh clean preview before an import can be applied.")
else:
    st.warning(
        "Applying changes writes approved records into the CommandCore CRM. CommandCore will re-check the live CRM and create a private backup before the first write."
    )

confirm = st.checkbox(
    "I reviewed the staged records and the live preview and approve this CRM import.",
    disabled=not apply_ready,
    key="crm_migration_confirm_apply",
)
allow_updates = False
if apply_ready and would_update > 0:
    allow_updates = st.checkbox(
        f"I explicitly approve updating {would_update} existing CommandCore CRM record(s).",
        key="crm_migration_allow_updates",
    )

commit_disabled = not apply_ready or not confirm or (would_update > 0 and not allow_updates)
if st.button("Apply Approved Records", type="primary", disabled=commit_disabled, use_container_width=True):
    try:
        result = call_service(
            COMMIT_SERVICE,
            {
                "rows": payload_rows,
                "apply": True,
                "confirm_apply": True,
                "allow_updates": allow_updates,
                "preview_token": preview.get("preview_token") if isinstance(preview, dict) else "",
            },
        )
        st.session_state.crm_migration_commit_result = result
        if result.get("ok") is True:
            st.success(
                f"Imported {result.get('committed_count', 0)} records into CommandCore. "
                f"Pre-import backup: {text(result.get('pre_apply_backup_snapshot_id')) or 'verified'}"
            )
            st.session_state.pop("crm_migration_preview", None)
            st.session_state.pop("crm_migration_preview_signature", None)
        else:
            st.warning(
                f"Imported {result.get('committed_count', 0)} records with {result.get('failed_count', 0)} failures."
            )
    except RuntimeError as exc:
        st.error(str(exc))

commit_result = st.session_state.get("crm_migration_commit_result")
if isinstance(commit_result, dict):
    with st.expander("Latest import result", expanded=True):
        st.json(commit_result)

st.divider()
st.subheader("Source CRM Reconciliation")
st.caption(
    "CommandCore builds a source manifest from the export files staged in this browser session. "
    "External IDs are fingerprinted locally and are not displayed. A category is never assumed to be zero."
)

ids_by_entity = accumulated_source_ids()
for entity_key in ENTITY_KEYS:
    if ids_by_entity[entity_key]:
        st.session_state[f"crm_source_zero_{entity_key}"] = False
    else:
        st.checkbox(
            f"I verified the source CRM has zero {entity_key} records.",
            key=f"crm_source_zero_{entity_key}",
        )

real_source_export = st.checkbox(
    "I confirm the staged files/counts came from the real source CRM export, not test or sample data.",
    key="crm_reconciliation_real_source_export",
)
manifest_source = text(st.session_state.get("crm_migration_manifest_source") or stage.get("source") or source)
source_manifest, manifest_status = build_source_manifest(manifest_source, real_source_export)
st.dataframe(pd.DataFrame(manifest_status), use_container_width=True, hide_index=True)

if source_manifest is None:
    st.info("Account for all nine source categories by staging their exports or explicitly confirming a true zero count.")

if st.button(
    "Run Source Reconciliation Preview",
    type="primary",
    use_container_width=True,
    disabled=source_manifest is None,
):
    try:
        reconciliation_preview = call_service(
            RECONCILIATION_SERVICE,
            {"action": "preview", "source_manifest": source_manifest},
        )
        st.session_state.crm_migration_reconciliation_preview = reconciliation_preview
        st.session_state.pop("crm_migration_reconciliation_result", None)
    except RuntimeError as exc:
        st.error(str(exc))

reconciliation_preview = st.session_state.get("crm_migration_reconciliation_preview")
if isinstance(reconciliation_preview, dict):
    exact_match = reconciliation_preview.get("exact_match") is True
    eligible = reconciliation_preview.get("eligible_for_owner_verification") is True
    if exact_match:
        st.success("Source manifest and CommandCore match across all nine CRM record categories.")
    else:
        mismatched = reconciliation_preview.get("mismatched_entities")
        mismatched_names = [str(item) for item in mismatched] if isinstance(mismatched, list) else []
        st.warning(
            "Reconciliation is not exact yet. "
            + ("Mismatched: " + ", ".join(mismatched_names) if mismatched_names else "Review the comparison below.")
        )
    st.dataframe(pd.DataFrame(reconciliation_rows(reconciliation_preview)), use_container_width=True, hide_index=True)

    st.markdown("#### Record Verified Reconciliation")
    st.caption(
        "This does not migrate, delete, or change CRM records. It records that a real source export exactly matches "
        "CommandCore. CommandCore will not accept test/synthetic data for this step."
    )
    owner_approve_reconciliation = st.checkbox(
        "I approve recording this exact real-source reconciliation as verified.",
        disabled=not eligible,
        key="crm_reconciliation_owner_approve",
    )
    confirmation_phrase = st.text_input(
        'Type "VERIFY CRM RECONCILIATION" to confirm.',
        disabled=not eligible,
        key="crm_reconciliation_confirmation_phrase",
    )
    verify_disabled = (
        not eligible
        or not owner_approve_reconciliation
        or confirmation_phrase != "VERIFY CRM RECONCILIATION"
        or source_manifest is None
    )
    if st.button("Record Verified Reconciliation", disabled=verify_disabled, use_container_width=True):
        try:
            reconciliation_result = call_service(
                RECONCILIATION_SERVICE,
                {
                    "action": "record_verified",
                    "source_manifest": source_manifest,
                    "owner_approved": True,
                    "confirmation_phrase": confirmation_phrase,
                },
            )
            st.session_state.crm_migration_reconciliation_result = reconciliation_result
            if reconciliation_result.get("reconciliation_verified") is True:
                st.success(
                    "CRM source reconciliation recorded as verified. "
                    f"Verification: {text(reconciliation_result.get('verification_id'))}"
                )
        except RuntimeError as exc:
            st.error(str(exc))

reconciliation_result = st.session_state.get("crm_migration_reconciliation_result")
if isinstance(reconciliation_result, dict) and reconciliation_result.get("reconciliation_verified") is True:
    st.success("Latest source reconciliation is verified. The launch-readiness auditor can now evaluate CRM cutover status.")

st.info(
    "Migration safety: staging and preview do not write CRM records. "
    "Applying requires a fresh signed preview, explicit confirmation, explicit overwrite permission when needed, "
    "and a verified private backup before the first write. Reconciliation is a separate aggregate verification step. "
    "This screen cannot delete CRM records or trigger external communications, payments, legal actions, or other outside execution."
)
