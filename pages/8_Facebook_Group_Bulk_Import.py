from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.facebook_group_import import (
    FacebookGroupImportRow,
    apply_group_import,
    csv_template,
    import_preview_rows,
    parse_csv_groups,
    parse_pasted_groups,
)
from cfh_disposition.facebook_groups import (
    DEFAULT_GROUP_COOLDOWN_DAYS,
    FacebookGroupError,
    FacebookGroupStore,
    group_directory_rows,
)

st.set_page_config(
    page_title="Facebook Group Bulk Import",
    page_icon="📥",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("Facebook Group Bulk Import")
    st.caption("Private internal access")
    with st.form("facebook_group_bulk_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


def preview_key() -> str:
    return "facebook_group_bulk_import_preview"


def save_preview(rows: list[FacebookGroupImportRow]) -> None:
    st.session_state[preview_key()] = rows


def load_preview() -> list[FacebookGroupImportRow]:
    value = st.session_state.get(preview_key(), [])
    return value if isinstance(value, list) else []


require_password()
st.title("Facebook Group Bulk Import")
st.caption(
    "Add dozens or hundreds of Facebook Groups without entering them one at a time. "
    "Nothing posts to Facebook from this page."
)

try:
    store = FacebookGroupStore(st.secrets)
    ledger = store.load()
except FacebookGroupError as exc:
    st.error(f"Bulk import is safety-locked: {exc}")
    st.stop()

metrics = st.columns(3)
metrics[0].metric("Groups Saved", len(ledger.groups))
metrics[1].metric("Active Groups", sum(group.active for group in ledger.groups))
metrics[2].metric("Import Limit", "500 rows")

st.download_button(
    "Download CSV Template",
    data=csv_template(),
    file_name="facebook_group_import_template.csv",
    mime="text/csv",
)

paste_tab, csv_tab = st.tabs(["Paste a Group List", "Upload CSV"])

with paste_tab:
    st.write("### Paste one group per line")
    st.caption(
        "Fastest format: Group Name | Facebook URL | Cooldown Days | Notes. "
        "You may also paste Facebook Group URLs only; the system creates a temporary name from the group ID."
    )
    default_cooldown = st.number_input(
        "Default cooldown days",
        min_value=1,
        max_value=90,
        value=DEFAULT_GROUP_COOLDOWN_DAYS,
        key="bulk_paste_default_cooldown",
    )
    pasted = st.text_area(
        "Facebook Groups",
        height=260,
        placeholder=(
            "Owner Financing Homes for Sale | https://www.facebook.com/groups/1305510733671893 | 7 | Owner-finance posts allowed\n"
            "Illinois Owner Finance Buyers | https://www.facebook.com/groups/123456789 | 5"
        ),
        key="facebook_group_bulk_text",
    )
    if st.button("Preview Pasted Groups", type="primary", use_container_width=True):
        rows = parse_pasted_groups(
            pasted,
            ledger,
            default_cooldown_days=int(default_cooldown),
        )
        save_preview(rows)
        if rows:
            st.success(f"Prepared {len(rows)} row(s) for review below.")
        else:
            st.error("No usable group rows were found.")

with csv_tab:
    st.write("### Upload a CSV file")
    st.caption(
        "Accepted columns: group_name, group_url, cooldown_days, notes. "
        "The shorter names name, url, cooldown, and rules also work."
    )
    csv_default_cooldown = st.number_input(
        "CSV default cooldown days",
        min_value=1,
        max_value=90,
        value=DEFAULT_GROUP_COOLDOWN_DAYS,
        key="bulk_csv_default_cooldown",
    )
    uploaded = st.file_uploader(
        "Choose CSV",
        type=["csv"],
        key="facebook_group_bulk_csv",
    )
    if st.button("Preview CSV Groups", type="primary", use_container_width=True):
        if uploaded is None:
            st.error("Choose a CSV file first.")
        else:
            rows = parse_csv_groups(
                uploaded.getvalue(),
                ledger,
                default_cooldown_days=int(csv_default_cooldown),
            )
            save_preview(rows)
            if rows:
                st.success(f"Prepared {len(rows)} row(s) for review below.")
            else:
                st.error("The CSV did not contain usable group rows.")

rows = load_preview()
st.write("## Import Preview")
if not rows:
    st.info("Preview a pasted list or CSV before importing.")
else:
    table = pd.DataFrame(import_preview_rows(rows))
    st.dataframe(table, use_container_width=True, hide_index=True)

    add_count = sum(row.action == "Add" for row in rows)
    update_count = sum(row.action == "Update" for row in rows)
    skip_count = sum(row.action == "Skip" for row in rows)
    counts = st.columns(3)
    counts[0].metric("Will Add", add_count)
    counts[1].metric("Will Update", update_count)
    counts[2].metric("Will Skip", skip_count)

    confirmed = st.checkbox(
        "I reviewed the preview and confirm these Facebook Groups should be saved to the private directory.",
        key="facebook_group_bulk_confirm",
    )
    if st.button(
        "Import Reviewed Groups",
        type="primary",
        use_container_width=True,
        disabled=not confirmed or add_count + update_count == 0,
    ):
        try:
            result = apply_group_import(ledger, rows)
            store.save(result.ledger)
            st.session_state.pop(preview_key(), None)
            st.session_state.pop("facebook_group_bulk_confirm", None)
            st.success(
                f"Import complete: {result.added} added, {result.updated} updated, "
                f"and {result.skipped} skipped."
            )
            st.rerun()
        except FacebookGroupError as exc:
            st.error(f"The group directory could not be saved: {exc}")

st.write("## Current Facebook Group Directory")
directory_rows = group_directory_rows(ledger)
if directory_rows:
    st.dataframe(
        pd.DataFrame(directory_rows),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No Facebook Groups are saved yet.")
