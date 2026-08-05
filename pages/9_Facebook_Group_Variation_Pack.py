from __future__ import annotations

import csv
import io

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.dwelyx import build_dwelyx_url, dwelyx_base_url
from cfh_disposition.facebook_group_variations import (
    build_facebook_group_variation,
    validate_facebook_group_variation,
    variation_index,
)
from cfh_disposition.facebook_groups import (
    FacebookGroupError,
    FacebookGroupStore,
    active_groups,
    facebook_group_post_status,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Facebook Group Variation Pack",
    page_icon="📝",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("Facebook Group Variation Pack")
    st.caption("Private internal access")
    with st.form("facebook_group_variation_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


def csv_bytes(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO()
    fieldnames = [
        "Facebook Group",
        "Ready",
        "Variation",
        "Facebook URL",
        "Tracked Dwelyx Link",
        "Group Notes",
        "Status",
        "Post Copy",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def text_pack(rows: list[dict[str, str]]) -> bytes:
    sections: list[str] = []
    for row in rows:
        sections.append(
            "\n".join(
                [
                    "=" * 72,
                    row["Facebook Group"],
                    row["Variation"],
                    row["Facebook URL"],
                    "-" * 72,
                    row["Post Copy"],
                ]
            )
        )
    return ("\n\n".join(sections) + "\n").encode("utf-8")


require_password()
st.title("Facebook Group Variation Pack")
st.caption(
    "Generate accurate, different Facebook Group versions for the same property without changing "
    "the property facts. Marketplace copy is not created on this page."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    group_store = FacebookGroupStore(st.secrets)
    ledger = group_store.load()
except (StorageError, FacebookGroupError) as exc:
    st.error(f"Variation Pack is safety-locked: {exc}")
    st.stop()

property_options = {
    item.display_address or str(item.property_id): item
    for item in properties
}
groups = active_groups(ledger)

if not property_options:
    st.info("Add a property before creating Facebook Group variations.")
    st.stop()
if not groups:
    st.info("Add Facebook Groups in the protected Group Directory or Bulk Import page first.")
    st.stop()

selected_name = st.selectbox("Choose property", list(property_options))
selected = property_options[selected_name]
campaign = st.text_input("Campaign name", value="owner_finance_homes")
dwelyx_url = dwelyx_base_url(st.secrets)

rows: list[dict[str, str]] = []
eligible_rows: list[dict[str, str]] = []
for group in groups:
    status = facebook_group_post_status(
        ledger,
        property_id=selected.property_id,
        group_id=group.group_id,
    )
    prior_count = sum(
        1
        for post in ledger.posts
        if post.property_id == str(selected.property_id)
        and post.group_id == group.group_id
    )
    index = variation_index(
        selected.property_id,
        group.group_id,
        prior_post_count=prior_count,
    )
    tracked_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="facebook_groups",
        campaign=f"{campaign}_{group.group_id[:8]}_v{index + 1}",
        property_id=selected.property_id,
    )
    variation = build_facebook_group_variation(
        selected,
        tracked_link,
        group_id=group.group_id,
        prior_post_count=prior_count,
    )
    errors = validate_facebook_group_variation(
        variation,
        selected,
        tracked_link,
    )
    ready = status.eligible and not errors and bool(group.group_url)
    status_text = status.message
    if errors:
        status_text = "Blocked by fact guard: " + "; ".join(errors)
    elif not group.group_url:
        status_text = "Blocked: no Facebook Group URL is saved."

    row = {
        "Facebook Group": group.name,
        "Ready": "Yes" if ready else "No",
        "Variation": variation.label,
        "Facebook URL": group.group_url or "—",
        "Tracked Dwelyx Link": tracked_link if ready else "—",
        "Group Notes": group.notes or "—",
        "Status": status_text,
        "Post Copy": variation.copy if ready else "",
    }
    rows.append(row)
    if ready:
        eligible_rows.append(row)

metrics = st.columns(4)
metrics[0].metric("Active Groups", len(groups))
metrics[1].metric("Ready Now", len(eligible_rows))
metrics[2].metric("Cooling or Blocked", len(rows) - len(eligible_rows))
metrics[3].metric("Copy Variations", 8)

st.write("### Variation assignment")
st.dataframe(
    pd.DataFrame(
        [
            {
                "Facebook Group": row["Facebook Group"],
                "Ready": row["Ready"],
                "Variation": row["Variation"],
                "Status": row["Status"],
            }
            for row in rows
        ]
    ),
    use_container_width=True,
    hide_index=True,
)

if eligible_rows:
    left, right = st.columns(2)
    left.download_button(
        "Download Ready Variation Pack (CSV)",
        data=csv_bytes(eligible_rows),
        file_name="facebook_group_variation_pack.csv",
        mime="text/csv",
        use_container_width=True,
    )
    right.download_button(
        "Download Ready Variation Pack (TXT)",
        data=text_pack(eligible_rows),
        file_name="facebook_group_variation_pack.txt",
        mime="text/plain",
        use_container_width=True,
    )

    st.write("### Review one group package")
    ready_by_name = {row["Facebook Group"]: row for row in eligible_rows}
    review_name = st.selectbox("Ready Facebook Group", list(ready_by_name))
    review = ready_by_name[review_name]
    if review["Group Notes"] != "—":
        st.info(f"Saved group rules or notes: {review['Group Notes']}")
    st.link_button(
        f"Open {review_name}",
        review["Facebook URL"],
        type="primary",
        use_container_width=True,
    )
    st.caption(review["Variation"])
    st.code(review["Post Copy"], language=None)
    st.info(
        "Every version keeps the exact address, down payment, monthly payment, condition, repairs, "
        "disclosures, approval language, and tracked Dwelyx destination. The total purchase price "
        "is intentionally omitted from public Facebook Group copy."
    )
else:
    st.warning(
        "No group package is ready right now. The table explains whether each group is cooling down, "
        "missing a URL, or blocked by the fact guard."
    )

st.page_link(
    "pages/7_Facebook_Group_Posting_Center.py",
    label="Open Fast Operator Mode",
    icon="👥",
)
