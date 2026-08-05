from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from .facebook_assignments import (
    AssignmentStatus,
    FacebookAssignmentError,
    FacebookAssignmentStore,
    FacebookPostingAssignment,
    active_operators,
    assignment_rows,
    assignments_for_date,
    complete_assignment_and_record_group_post,
    daily_assignment_summary,
    deactivate_operator,
    generate_daily_assignments,
    update_assignment_status,
    upsert_operator,
)
from .facebook_groups import FacebookGroupError, FacebookGroupStore, business_now
from .models import OwnerFinanceProperty


def _property_options(
    properties: Sequence[OwnerFinanceProperty],
) -> dict[str, OwnerFinanceProperty]:
    return {
        property_record.display_address or str(property_record.property_id): property_record
        for property_record in properties
    }


def _assignment_option_label(assignment: FacebookPostingAssignment) -> str:
    return (
        f"{assignment.priority} — {assignment.assigned_to_name} — "
        f"{assignment.property_address} → {assignment.group_name} "
        f"[{assignment.status.value}]"
    )


def _render_assignment_photos(
    assignment: FacebookPostingAssignment,
    properties_by_id: Mapping[str, OwnerFinanceProperty],
) -> None:
    property_record = properties_by_id.get(assignment.property_id)
    st.write("### Property photos")
    if not property_record or not property_record.photo_urls:
        st.warning("No saved property photos are available for this assignment.")
        return
    columns = st.columns(min(4, len(property_record.photo_urls)))
    for index, photo_url in enumerate(property_record.photo_urls):
        url = str(photo_url)
        column = columns[index % len(columns)]
        column.image(url, use_container_width=True)
        column.link_button(f"Open Photo {index + 1}", url)


def _history_rows(assignments: Sequence[FacebookPostingAssignment]) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for assignment in sorted(
        assignments,
        key=lambda item: (item.assignment_date, item.priority),
        reverse=True,
    ):
        rows.append(
            {
                "Date": assignment.assignment_date.isoformat(),
                "Priority": assignment.priority,
                "Team Member": assignment.assigned_to_name,
                "Status": assignment.status.value,
                "Property": assignment.property_address,
                "Facebook Group": assignment.group_name,
                "Variation": assignment.variation_label,
                "Completed By": assignment.completed_by or "—",
                "Completed At": (
                    assignment.completed_at.astimezone().strftime("%Y-%m-%d %I:%M %p")
                    if assignment.completed_at
                    else "—"
                ),
                "Notes": assignment.notes or "—",
            }
        )
    return rows


def render_facebook_assignment_dashboard(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
    dwelyx_url: str,
) -> None:
    st.subheader("Daily Facebook Posting Assignment Dashboard")
    st.caption(
        "Assign eligible Facebook Groups across the team without overlap. The final Facebook "
        "publish click remains manual; completed assignments activate the saved group cooldown."
    )

    try:
        assignment_store = FacebookAssignmentStore(secrets)
        assignment_ledger = assignment_store.load()
        group_store = FacebookGroupStore(secrets)
        group_ledger = group_store.load()
    except (FacebookAssignmentError, FacebookGroupError) as exc:
        st.error(f"The assignment dashboard is safety-locked: {exc}")
        st.info(
            "Restore the Supabase connection before assigning or recording Facebook Group work."
        )
        return

    today: date = business_now().date()
    properties_by_name = _property_options(properties)
    properties_by_id = {
        str(property_record.property_id): property_record
        for property_record in properties
    }

    board_tab, generate_tab, team_tab, history_tab = st.tabs(
        ["Daily Board", "Generate Assignments", "Team Setup", "History"]
    )

    with team_tab:
        st.write("### Add or update a Facebook posting team member")
        with st.form("facebook_assignment_operator_form", clear_on_submit=True):
            name = st.text_input("Team member name*")
            daily_goal = st.number_input(
                "Daily Facebook Group posting goal",
                min_value=1,
                max_value=200,
                value=20,
            )
            operator_notes = st.text_area(
                "Role, work hours, account restrictions, or manager notes",
                height=90,
            )
            save_operator = st.form_submit_button("Save Team Member", type="primary")
        if save_operator:
            try:
                assignment_ledger = upsert_operator(
                    assignment_ledger,
                    name=name,
                    daily_goal=int(daily_goal),
                    notes=operator_notes,
                )
                assignment_store.save(assignment_ledger)
                st.success(f"{name.strip()} is saved on the Facebook posting team.")
                st.rerun()
            except (FacebookAssignmentError, ValidationError, ValueError) as exc:
                st.error(f"Team member could not be saved: {exc}")

        operators = active_operators(assignment_ledger)
        st.write("### Active posting team")
        if operators:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Team Member": operator.name,
                            "Daily Goal": operator.daily_goal,
                            "Notes": operator.notes or "—",
                        }
                        for operator in operators
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            operator_options = {operator.name: operator for operator in operators}
            deactivate_name = st.selectbox(
                "Deactivate a team member",
                list(operator_options),
                key="facebook_assignment_deactivate_operator",
            )
            if st.button("Deactivate Selected Team Member"):
                try:
                    assignment_ledger = deactivate_operator(
                        assignment_ledger,
                        operator_id=operator_options[deactivate_name].operator_id,
                    )
                    assignment_store.save(assignment_ledger)
                    st.success(f"{deactivate_name} is inactive for new assignments.")
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))
        else:
            st.info("Add the first team member above before generating assignments.")

    with generate_tab:
        st.write("### Build a balanced daily posting plan")
        operators = active_operators(assignment_ledger)
        if not properties_by_name:
            st.info("Add properties before generating Facebook assignments.")
        elif not operators:
            st.info("Add active team members in Team Setup first.")
        elif not group_ledger.groups:
            st.info("Add or bulk-import Facebook Groups before generating assignments.")
        else:
            assignment_date = st.date_input(
                "Assignment date",
                value=today,
                key="facebook_assignment_generation_date",
            )
            selected_property_names = st.multiselect(
                "Properties to rotate across eligible groups",
                options=list(properties_by_name),
                default=list(properties_by_name),
                key="facebook_assignment_generation_properties",
            )
            operator_options = {operator.name: operator for operator in operators}
            selected_operator_names = st.multiselect(
                "Team members receiving assignments",
                options=list(operator_options),
                default=list(operator_options),
                key="facebook_assignment_generation_operators",
            )
            campaign = st.text_input(
                "Campaign name",
                value="owner_finance_homes",
                key="facebook_assignment_campaign",
            )
            st.info(
                "Safety rule: each Facebook Group receives no more than one property assignment "
                "per day. Existing assignments and property-specific cooldowns are respected."
            )
            if st.button(
                "Generate Balanced Daily Assignments",
                type="primary",
                use_container_width=True,
            ):
                try:
                    result = generate_daily_assignments(
                        assignment_ledger,
                        group_ledger,
                        [
                            properties_by_name[property_name]
                            for property_name in selected_property_names
                        ],
                        operator_ids=[
                            operator_options[operator_name].operator_id
                            for operator_name in selected_operator_names
                        ],
                        assignment_date=assignment_date,
                        dwelyx_url=dwelyx_url,
                        campaign=campaign,
                    )
                    assignment_store.save(result.ledger)
                    st.success(
                        f"Created {result.created} balanced assignment(s) for "
                        f"{assignment_date.isoformat()}."
                    )
                    st.caption(
                        f"Skipped: {result.duplicate_skipped} existing/day duplicates, "
                        f"{result.cooldown_skipped} cooldown conflicts, "
                        f"{result.validation_skipped} fact-safety failures, and "
                        f"{result.capacity_skipped} assignments beyond team capacity."
                    )
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))

    with board_tab:
        board_date = st.date_input(
            "Board date",
            value=today,
            key="facebook_assignment_board_date",
        )
        day_assignments = assignments_for_date(assignment_ledger, board_date)
        summary = daily_assignment_summary(assignment_ledger, board_date)
        metrics = st.columns(6)
        metrics[0].metric("Assigned", summary.total)
        metrics[1].metric("Posted", summary.posted)
        metrics[2].metric("In Progress", summary.in_progress)
        metrics[3].metric("Remaining", summary.remaining)
        metrics[4].metric("Needs Review", summary.needs_review)
        metrics[5].metric("Completion", f"{summary.completion_percent}%")

        operators_on_board = sorted(
            {assignment.assigned_to_name for assignment in day_assignments},
            key=str.casefold,
        )
        operator_filter = st.selectbox(
            "Show assignments for",
            ["All Team Members", *operators_on_board],
            key="facebook_assignment_operator_filter",
        )
        filtered_assignments = [
            assignment
            for assignment in day_assignments
            if operator_filter == "All Team Members"
            or assignment.assigned_to_name == operator_filter
        ]

        rows = assignment_rows(assignment_ledger, board_date)
        if operator_filter != "All Team Members":
            rows = [row for row in rows if row["Team Member"] == operator_filter]
        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No Facebook posting assignments are saved for this date.")

        if filtered_assignments:
            st.write("### Work the selected assignment")
            assignment_options = {
                _assignment_option_label(assignment): assignment
                for assignment in filtered_assignments
            }
            selected_label = st.selectbox(
                "Assignment",
                list(assignment_options),
                key="facebook_assignment_selected_assignment",
            )
            selected = assignment_options[selected_label]

            detail_columns = st.columns(4)
            detail_columns[0].metric("Team Member", selected.assigned_to_name)
            detail_columns[1].metric("Status", selected.status.value)
            detail_columns[2].metric("Variation", selected.variation_label)
            detail_columns[3].metric("Priority", selected.priority)
            st.write(f"**Property:** {selected.property_address}")
            st.write(f"**Facebook Group:** {selected.group_name}")
            if selected.group_url:
                st.link_button(
                    f"Open {selected.group_name}",
                    selected.group_url,
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.error("This assignment has no saved Facebook Group URL.")

            st.write("### Copy-ready Facebook Group post")
            st.code(selected.post_copy, language=None)
            st.text_input(
                "Tracked Dwelyx buyer-registration link",
                value=selected.tracked_link,
                key=f"assignment_link_{selected.assignment_id}",
            )
            _render_assignment_photos(selected, properties_by_id)

            action_notes = st.text_area(
                "Post URL, approval status, skip reason, or manager notes",
                value=selected.notes,
                height=80,
                key=f"assignment_notes_{selected.assignment_id}",
            )
            actor = st.text_input(
                "Action completed by",
                value=selected.assigned_to_name,
                key=f"assignment_actor_{selected.assignment_id}",
            )

            start_column, review_column, skip_column = st.columns(3)
            if start_column.button("Start Assignment", use_container_width=True):
                try:
                    updated = update_assignment_status(
                        assignment_ledger,
                        assignment_id=selected.assignment_id,
                        status=AssignmentStatus.IN_PROGRESS,
                        actor=actor,
                        notes=action_notes,
                    )
                    assignment_store.save(updated)
                    st.success("Assignment marked In Progress.")
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))
            if review_column.button("Needs Manager Review", use_container_width=True):
                try:
                    updated = update_assignment_status(
                        assignment_ledger,
                        assignment_id=selected.assignment_id,
                        status=AssignmentStatus.NEEDS_REVIEW,
                        actor=actor,
                        notes=action_notes,
                    )
                    assignment_store.save(updated)
                    st.success("Assignment sent to manager review.")
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))
            if skip_column.button("Skip Assignment", use_container_width=True):
                try:
                    updated = update_assignment_status(
                        assignment_ledger,
                        assignment_id=selected.assignment_id,
                        status=AssignmentStatus.SKIPPED,
                        actor=actor,
                        notes=action_notes,
                    )
                    assignment_store.save(updated)
                    st.success("Assignment skipped and removed from the active daily workload.")
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))

            posted_confirmed = st.checkbox(
                "I confirm the property post is already live in this exact Facebook Group.",
                key=f"assignment_posted_confirmed_{selected.assignment_id}",
            )
            if st.button(
                "Record Posted and Activate Cooldown",
                type="primary",
                use_container_width=True,
                disabled=not posted_confirmed or not selected.group_url,
            ):
                try:
                    updated_assignments, updated_groups = (
                        complete_assignment_and_record_group_post(
                            assignment_ledger,
                            group_ledger,
                            assignment_id=selected.assignment_id,
                            actor=actor,
                            notes=action_notes,
                        )
                    )
                    group_store.save(updated_groups)
                    assignment_store.save(updated_assignments)
                    st.success(
                        "Post recorded. The assignment is complete and this property/group "
                        "cooldown is now active."
                    )
                    st.rerun()
                except FacebookAssignmentError as exc:
                    st.error(str(exc))

    with history_tab:
        st.write("### Assignment history")
        history = _history_rows(assignment_ledger.assignments)
        if history:
            history_table = pd.DataFrame(history)
            st.dataframe(history_table, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Facebook Assignment History (CSV)",
                data=history_table.to_csv(index=False).encode(),
                file_name="facebook_posting_assignment_history.csv",
                mime="text/csv",
            )
        else:
            st.info("No Facebook posting assignments have been generated yet.")
