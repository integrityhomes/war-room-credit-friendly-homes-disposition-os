from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .ai_campaign import CampaignPackage, build_fallback_campaign
from .automatic_launch import channel_copy_with_link
from .dwelyx import build_dwelyx_url
from .facebook_group_queue import (
    build_facebook_group_queue,
    eligible_queue_items,
    operator_current_item,
    operator_progress,
    queue_summary_rows,
)
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


def _campaign_package(
    selected: OwnerFinanceProperty,
    tracked_link: str,
) -> CampaignPackage:
    campaign_key = f"campaign_package_{selected.property_id}"
    package_data = st.session_state.get(campaign_key)
    if package_data:
        return CampaignPackage.model_validate(package_data)
    return build_fallback_campaign(selected, tracked_link)


def _tracked_group_link(
    dwelyx_url: str,
    selected: OwnerFinanceProperty,
    campaign: str,
    group_id: str,
) -> str:
    return build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="facebook_groups",
        campaign=f"{campaign}_{group_id[:8]}",
        property_id=selected.property_id,
    )


def _operator_cursor_key(selected: OwnerFinanceProperty) -> str:
    return f"facebook_group_operator_cursor_{selected.property_id}"


def _render_property_photos(selected: OwnerFinanceProperty) -> None:
    st.write("### 3. Add the property photos")
    if not selected.photo_urls:
        st.warning(
            "No property photos are saved. Add photos in Record Manager before posting."
        )
        return

    column_count = min(4, len(selected.photo_urls))
    columns = st.columns(column_count)
    for index, photo_url in enumerate(selected.photo_urls):
        column = columns[index % column_count]
        url = str(photo_url)
        column.image(url, use_container_width=True)
        column.link_button(f"Open Photo {index + 1}", url)


def render_facebook_group_posting_center(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
    dwelyx_url: str,
) -> None:
    st.subheader("Facebook Group Posting Center")
    st.caption(
        "Prepare tracked Facebook Group posts, move through groups quickly, prevent duplicate "
        "posting, and keep a per-group cooldown history. Final publication remains manual."
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

    operator_tab, post_tab, queue_tab, directory_tab, history_tab = st.tabs(
        [
            "Fast Operator Mode",
            "Post to One Group",
            "Multi-Group Queue",
            "Group Directory",
            "Posting History",
        ]
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
                st.success(
                    f"{name.strip()} is saved in the private Facebook Group directory."
                )
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

    with operator_tab:
        options = _property_options(properties)
        groups = active_groups(ledger)
        if not options:
            st.info("Add a property before starting Fast Operator Mode.")
        elif not groups:
            st.info(
                "Add Facebook Groups in the Group Directory before starting Fast Operator Mode."
            )
        else:
            selected_name = st.selectbox(
                "Choose property to post",
                list(options),
                key="facebook_group_operator_property",
            )
            selected = options[selected_name]
            left, right = st.columns(2)
            campaign = left.text_input(
                "Operator campaign name",
                value="owner_finance_homes",
                key="facebook_group_operator_campaign",
            )
            operator = right.text_input(
                "Operator name",
                value="Sabrina",
                key="facebook_group_operator_name",
            )

            queue = build_facebook_group_queue(
                ledger,
                property_id=selected.property_id,
            )
            eligible = eligible_queue_items(queue)
            cooling_down = len(queue) - len(eligible)
            cursor_key = _operator_cursor_key(selected)
            cursor = int(st.session_state.get(cursor_key, 0))
            current = operator_current_item(queue, cursor)
            position, total = operator_progress(queue, cursor)

            metrics = st.columns(3)
            metrics[0].metric("Ready Groups", len(eligible))
            metrics[1].metric(
                "Current Position",
                f"{position} of {total}" if total else "Complete",
            )
            metrics[2].metric("Cooling Down", cooling_down)

            if current is None:
                st.success(
                    "There are no eligible Facebook Groups left for this property right now. "
                    "The cooldown table shows when each group opens again."
                )
                st.dataframe(
                    pd.DataFrame(queue_summary_rows(queue)),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write(f"## Current Group: {current.group_name}")
                if current.notes:
                    st.info(f"Group rules or notes: {current.notes}")
                else:
                    st.caption(
                        "No special group rules are saved. Add them in Group Directory when known."
                    )

                tracked_link = _tracked_group_link(
                    dwelyx_url,
                    selected,
                    campaign,
                    current.group_id,
                )
                package = _campaign_package(selected, tracked_link)
                copy_text = channel_copy_with_link(
                    package,
                    "facebook_groups",
                    tracked_link,
                )

                st.write("### 1. Open the current Facebook Group")
                if current.group_url:
                    st.link_button(
                        f"Open {current.group_name}",
                        current.group_url,
                        type="primary",
                        use_container_width=True,
                    )
                else:
                    st.error(
                        "This group has no saved Facebook URL. Add it in Group Directory before posting."
                    )

                st.write("### 2. Copy the prepared post")
                st.code(copy_text, language=None)
                st.caption(
                    "Use the copy control in the post box. This Facebook Group version includes "
                    "the tracked Dwelyx buyer-registration link."
                )

                _render_property_photos(selected)

                st.write("### 4. Confirm the post and load the next group")
                notes_key = (
                    f"facebook_group_operator_notes_{selected.property_id}_{current.group_id}"
                )
                confirm_key = (
                    f"facebook_group_operator_confirm_{selected.property_id}_{current.group_id}"
                )
                post_notes = st.text_area(
                    "Optional Facebook post URL, approval note, or posting notes",
                    height=80,
                    key=notes_key,
                )
                confirmed = st.checkbox(
                    "I confirm this post is already live in the current Facebook Group.",
                    key=confirm_key,
                )

                skip_column, reset_column, posted_column = st.columns([1, 1, 2])
                if skip_column.button(
                    "Skip & Load Next",
                    use_container_width=True,
                ):
                    st.session_state[cursor_key] = cursor + 1
                    st.rerun()
                if reset_column.button(
                    "Return to First",
                    use_container_width=True,
                ):
                    st.session_state[cursor_key] = 0
                    st.rerun()
                if posted_column.button(
                    "Record Posted & Load Next",
                    type="primary",
                    use_container_width=True,
                    disabled=not confirmed or not current.group_url,
                ):
                    try:
                        ledger = record_facebook_group_post(
                            ledger,
                            property_id=selected.property_id,
                            property_address=selected.display_address,
                            group_id=current.group_id,
                            posted_by=operator,
                            campaign=campaign,
                            tracked_link=tracked_link,
                            notes=post_notes,
                        )
                        store.save(ledger)
                        st.session_state[cursor_key] = 0
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop(notes_key, None)
                        st.success(
                            f"{current.group_name} was recorded. Loading the next eligible group."
                        )
                        st.rerun()
                    except FacebookGroupError as exc:
                        st.error(str(exc))

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
                tracked_link = _tracked_group_link(
                    dwelyx_url,
                    selected,
                    campaign,
                    group.group_id,
                )
                package = _campaign_package(selected, tracked_link)
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

    with queue_tab:
        options = _property_options(properties)
        groups = active_groups(ledger)
        if not options:
            st.info("Add a property before building a multi-group posting queue.")
        elif not groups:
            st.info(
                "Add Facebook Groups in the Group Directory before building a posting queue."
            )
        else:
            selected_name = st.selectbox(
                "Choose property for the queue",
                list(options),
                key="facebook_group_queue_property",
            )
            selected = options[selected_name]
            left, right = st.columns(2)
            campaign = left.text_input(
                "Queue campaign name",
                value="owner_finance_homes",
                key="facebook_group_queue_campaign",
            )
            operator = right.text_input(
                "Queue posted by",
                value="Sabrina",
                key="facebook_group_queue_operator",
            )

            queue = build_facebook_group_queue(
                ledger,
                property_id=selected.property_id,
            )
            eligible = eligible_queue_items(queue)
            blocked_count = len(queue) - len(eligible)
            metrics = st.columns(3)
            metrics[0].metric("Active Groups", len(queue))
            metrics[1].metric("Ready Now", len(eligible))
            metrics[2].metric("Cooling Down", blocked_count)

            st.dataframe(
                pd.DataFrame(queue_summary_rows(queue)),
                use_container_width=True,
                hide_index=True,
            )

            if not eligible:
                st.warning(
                    "This property is still inside the repost cooldown for every active group. "
                    "The table above shows the next eligible dates."
                )
            else:
                eligible_by_name = {item.group_name: item for item in eligible}
                selected_group_names = st.multiselect(
                    "Groups to work through now",
                    options=list(eligible_by_name),
                    default=list(eligible_by_name),
                    key="facebook_group_queue_selection",
                )
                st.info(
                    "Open each selected group, paste its prepared post, publish manually, then "
                    "check only the groups where the post actually went live."
                )

                confirmation_keys: dict[str, str] = {}
                notes_keys: dict[str, str] = {}
                tracked_links: dict[str, str] = {}

                for group_name in selected_group_names:
                    item = eligible_by_name[group_name]
                    tracked_link = _tracked_group_link(
                        dwelyx_url,
                        selected,
                        campaign,
                        item.group_id,
                    )
                    package = _campaign_package(selected, tracked_link)
                    copy_text = channel_copy_with_link(
                        package,
                        "facebook_groups",
                        tracked_link,
                    )
                    tracked_links[item.group_id] = tracked_link
                    confirm_key = (
                        f"queue_confirm_{selected.property_id}_{item.group_id}"
                    )
                    notes_key = f"queue_notes_{selected.property_id}_{item.group_id}"
                    confirmation_keys[item.group_id] = confirm_key
                    notes_keys[item.group_id] = notes_key

                    with st.expander(f"{item.group_name} — ready to post"):
                        if item.notes:
                            st.info(f"Group rules or notes: {item.notes}")
                        if item.group_url:
                            st.link_button(
                                f"Open {item.group_name}",
                                item.group_url,
                            )
                        else:
                            st.warning(
                                "No Facebook URL is saved for this group. Add it in Group Directory."
                            )
                        st.text_input(
                            "Tracked Dwelyx link",
                            value=tracked_link,
                            key=f"queue_link_{selected.property_id}_{item.group_id}",
                        )
                        st.text_area(
                            "Prepared group post",
                            value=copy_text,
                            height=330,
                            key=f"queue_copy_{selected.property_id}_{item.group_id}",
                        )
                        st.text_area(
                            "Optional post URL or notes",
                            height=70,
                            key=notes_key,
                        )
                        st.checkbox(
                            "I confirm this post was actually published in this group.",
                            key=confirm_key,
                        )

                confirmed_ids = [
                    group_id
                    for group_id, key in confirmation_keys.items()
                    if st.session_state.get(key, False)
                ]
                if st.button(
                    "Record All Confirmed Group Posts",
                    type="primary",
                    use_container_width=True,
                    disabled=not selected_group_names,
                ):
                    if not confirmed_ids:
                        st.error(
                            "No posts were recorded. Check the confirmation box only for groups "
                            "where the property post is already live."
                        )
                    else:
                        try:
                            updated_ledger = ledger
                            for group_id in confirmed_ids:
                                updated_ledger = record_facebook_group_post(
                                    updated_ledger,
                                    property_id=selected.property_id,
                                    property_address=selected.display_address,
                                    group_id=group_id,
                                    posted_by=operator,
                                    campaign=campaign,
                                    tracked_link=tracked_links[group_id],
                                    notes=str(
                                        st.session_state.get(notes_keys[group_id], "")
                                    ),
                                )
                            store.save(updated_ledger)
                            st.success(
                                f"Recorded {len(confirmed_ids)} confirmed Facebook Group "
                                "post(s). Their cooldown clocks are now active."
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
