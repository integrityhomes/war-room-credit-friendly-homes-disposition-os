from __future__ import annotations

import io
import json
from typing import Any
from urllib import error, request

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore CRM Migration", page_icon="📥", layout="wide")

STAGING_SERVICE = "commandcore-crm-import-staging"
COMMIT_SERVICE = "commandcore-crm-import-commit"


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


require_password()

if st.sidebar.button("Log out", key="commandcore_crm_migration_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore CRM Migration")
st.caption(
    "Upload a CRM export, let CommandCore stage and map it, review anything uncertain, preview the commit, then import only approved records."
)

source = st.text_input("Migration source", value="rei-blackbook", help="Used to preserve original source identity during migration.")
entity = st.selectbox("Export type", ["Auto detect", "Contacts", "Properties", "Deals"], index=0)
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
            st.session_state.crm_migration_stage = result
            st.session_state.crm_migration_approvals = default_approvals(result.get("staged", []))
            st.success(f"Staged {result.get('staged_rows', 0)} rows.")
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

st.divider()
st.subheader("Commit Preview")
st.write(f"Approved for import: **{approved_count}** of **{len(payload_rows)}** staged rows.")

preview_col, commit_col = st.columns(2)
with preview_col:
    if st.button("Preview Commit", use_container_width=True):
        try:
            preview = call_service(COMMIT_SERVICE, {"rows": payload_rows, "apply": False})
            st.session_state.crm_migration_preview = preview
            st.success(f"Preview ready: {preview.get('ready_to_commit', 0)} records can be committed.")
        except RuntimeError as exc:
            st.error(str(exc))

with commit_col:
    confirm = st.checkbox("I reviewed the staged records and approve this CRM import.")
    if st.button("Commit Approved Records", type="primary", disabled=not confirm, use_container_width=True):
        try:
            result = call_service(COMMIT_SERVICE, {"rows": payload_rows, "apply": True})
            st.session_state.crm_migration_commit_result = result
            if result.get("ok") is True:
                st.success(f"Imported {result.get('committed_count', 0)} records into CommandCore.")
            else:
                st.warning(
                    f"Imported {result.get('committed_count', 0)} records with {result.get('failed_count', 0)} failures."
                )
        except RuntimeError as exc:
            st.error(str(exc))

preview = st.session_state.get("crm_migration_preview")
if isinstance(preview, dict):
    with st.expander("Latest commit preview"):
        st.json(preview)

commit_result = st.session_state.get("crm_migration_commit_result")
if isinstance(commit_result, dict):
    with st.expander("Latest import result", expanded=True):
        st.json(commit_result)

st.info(
    "Migration safety: this screen cannot delete CRM records or trigger external communications, payments, legal actions, or other outside execution."
)
