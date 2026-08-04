from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .ai_campaign import CampaignPackage, build_fallback_campaign
from .automatic_launch import channel_copy_with_link
from .dwelyx import build_dwelyx_url
from .facebook_groups import (
    DEFAULT_GROUP_COOLDOWN_DAYS,
    FacebookGroupError,
    FacebookGroupStore,
    active_groups,
    deactivate_group,
    facebook_group_post_status,
    group_directory_rows,
    group_post_rows,
    record_facebook_group_post,
    upsert_group,
)
from .models import OwnerFinanceProperty


def _property_options(
    properties: Sequence[OwnerFinanceProperty],
) -> dict[str, OwnerFinanceProperty]:
    return {
        item.display_address or str(item.property_id): item
        for item in properties
    }


def render_facebook_group_posting_center(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
    dwelyx_url: str,
) -> None:
    st.subheader("Facebook Group Posting Center")
    st.caption(
        "Build tracked Facebook Group posts, prevent accidental duplicate posting, and keep a "
        "per-group cooldown history. Final publication remains manual."
    )

    try:
        store = FacebookGroupStore(secrets)
        ledger = store.load()
    except FacebookGroupError as exc:
        st.error(f"Facebook Group Posting Center is safety-locked: {exc}")
        st.info(
            "This is not a broken post generator. Restore the Supabase connection before the "
            "team posts to Facebook Groups so the posting history remains accurate."
        )
        return

    post_tab, directory_tab, history_tab = st.tabs(
        ["Post a Property", "Group Directory", "Posting History"]
    )

    with directory_tab:
        st.write("### Add or update a Facebook Group")
        with st.form("facebook_group_directory_form", clear_on_submit=True):
            name = st.text_input("Facebook Group name*")
            group_url = st.text_input("Facebook Group URL — optional")
            cooldown_days = st.number_input(
                "Minimum days before reposting the same property to this group",
                min_value=1,
                max_value=90,
                value=DEFAULT_GROUP_COOLDOWN_DAYS,
            )
            notes = st.text_area(
                "Group rules, allowed posting days, admin requirements, or notes",
                height=100,
            )
            submitted = st.form_submit_button("Save Facebook Group", type="primary")

        if submitted:
            try:
                ledger = upsert_group(
                    ledger,
                    name=name,
                    group_url=group_url,
                    cooldown_days=int(cooldown_days),
                    notes=notes,
                )
                store.save(ledger)
                st.success(f"{name.strip()} is saved in the private Facebook Group directory.")
                st.rerun()
            except (FacebookGroupError, ValidationError, ValueError) as exc:
                st.error(f"Facebook Group could not be saved: {exc}")

        directory_rows = group_directory_rows(ledger)
        st.write("### Saved Facebook Groups")
        if directory_rows:
            st.dataframe(
                pd.DataFrame(directory_rows),
                use_container_width=True,
                hide_index=True,
            )
            active = active_groups(ledger)
            if active:
                group_options = {group.name: group for group in active}
                selected_group_name = st.selectbox(
                    "Deactivate a group that should no longer receive posts",
                    list(group_options),
                    key="facebook_group_deactivate",
                )
                if st.button("Deactivate Selected Group"):
                    try:
                        ledger = deactivate_group(
                            ledger,
                            group_id=group_options[selected_group_name].group_id,
                        )
                        store.save(ledger)
                        st.success(f"{selected_group_name} is now inactive.")
                        st.rerun()
                    except FacebookGroupError as exc:
                        st.error(str(exc))
        else:
            st.info("No Facebook Groups are saved yet. Add the first group above.")

    with post_tab:
        options = _property_options(properties)
        groups = active_groups(ledger)
        if not options:
            st.info("Add a property before preparing Facebook Group posts.")
        elif not groups:
            st.info(
                "Add at least one Facebook Group in the Group Directory tab before preparing a post."
            )
        else:
            selected_name = st.selectbox(
                "Choose property",
                list(options),
                key="facebook_group_property",
            )
            selected = options[selected_name]
            group_options = {group.name: group for group in groups}
            selected_group_name = st.selectbox(
                "Choose Facebook Group",
                list(group_options),
                key="facebook_group_target",
            )
            group = group_options[selected_group_name]
            campaign = st.text_input(
                "Campaign name",
                value="owner_finance_homes",
                key="facebook_group_campaign",
            )
            operator = st.text_input(
                "Posted by",
                value="Sabrina",
                key="facebook_group_operator",
            )

            status = facebook_group_post_status(
                ledger,
                property_id=selected.property_id,
                group_id=group.group_id,
            )
            if status.eligible:
                st.success(status.message)
            else:
                st.error(status.message)
                st.info(
                    "The post package is intentionally hidden until the group cooldown ends. "
                    "This prevents duplicate-looking posts and protects group relationships."
                )

            if status.eligible:
                tracked_link = build_dwelyx_url(
                    dwelyx_url,
                    source="credit_friendly_homes",
                    medium="facebook_groups",
                    campaign=campaign,
                    property_id=selected.property_id,
                )
                campaign_key = f"campaign_package_{selected.property_id}"
                package_data = st.session_state.get(campaign_key)
                package = (
                    CampaignPackage.model_validate(package_data)
                    if package_data
                    else build_fallback_campaign(selected, tracked_link)
                )
                copy_text = channel_copy_with_link(
                    package,
                    "facebook_groups",
                    tracked_link,
                )

                if group.group_url:
                    st.link_button("Open Selected Facebook Group", group.group_url)
                st.text_input(
                    "Tracked Dwelyx buyer-registration link for this group post",
                    value=tracked_link,
                    key="facebook_group_tracked_link",
                )
                st.text_area(
                    "Complete Facebook Group post",
                    value=copy_text,
                    height=360,
                    key="facebook_group_post_copy",
                )
                st.info(
                    "The tracked Dwelyx link is allowed in the Facebook Group package. Do not "
                    "copy this version into Facebook Marketplace."
                )

                notes = st.text_area(
                    "Optional post URL, admin approval note, or posting notes",
                    height=80,
                    key="facebook_group_post_notes",
                )
                confirmed = st.checkbox(
                    "I confirm this post was actually published in the selected Facebook Group.",
                    key="facebook_group_post_confirmed",
                )
                if st.button(
                    "Record Facebook Group Post",
                    type="primary",
                    disabled=not confirmed,
                    use_container_width=True,
                ):
                    try:
                        ledger = record_facebook_group_post(
                            ledger,
                            property_id=selected.property_id,
                            property_address=selected.display_address,
                            group_id=group.group_id,
                            posted_by=operator,
                            campaign=campaign,
                            tracked_link=tracked_link,
                            notes=notes,
                        )
                        store.save(ledger)
                        refreshed = facebook_group_post_status(
                            ledger,
                            property_id=selected.property_id,
                            group_id=group.group_id,
                        )
                        st.success(
                            "Facebook Group post recorded. "
                            f"{refreshed.message}"
                        )
                        st.rerun()
                    except FacebookGroupError as exc:
                        st.error(str(exc))

    with history_tab:
        rows = group_post_rows(ledger)
        st.write("### Recent Facebook Group posts")
        if rows:
            table = pd.DataFrame(rows)
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Facebook Group Posting History (CSV)",
                data=table.to_csv(index=False).encode("utf-8"),
                file_name="facebook_group_posting_history.csv",
                mime="text/csv",
            )
        else:
            st.info("No Facebook Group posts have been recorded yet.")
