from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.campaign_launch import CampaignLaunchStore, LaunchStoreError
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionStore,
)
from cfh_disposition.inventory_velocity import (
    EscalationLevel,
    EscalationTaskStatus,
    InventoryVelocityError,
    InventoryVelocityStore,
    PropertyVelocityProfile,
    add_escalation_task,
    build_velocity_queue,
    profile_for_property,
    queue_rows,
    suggested_task,
    task_rows,
    update_escalation_task,
    upsert_profile,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Vacant Home Disposition Escalation Center",
    page_icon="🚨",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Vacant Home Disposition Escalation Center")
    st.caption("Private internal access")
    with st.form("inventory_velocity_login"):
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


def money(value: Decimal) -> str:
    return f"${value:,.0f}"


require_password()
st.title("Vacant Home Disposition Escalation Center")
st.caption(
    "Ranks vacant homes by disposition pressure, identifies the actual funnel bottleneck, "
    "and assigns the next action required to get each home filled faster."
)
st.warning(
    "This center never changes a property's price, down payment, monthly payment, ad budget, "
    "or status automatically. Management approval is required for any term or pricing decision."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    velocity_store = InventoryVelocityStore(st.secrets)
    velocity_ledger = velocity_store.load()
except (StorageError, InventoryVelocityError) as exc:
    st.error(f"Inventory Escalation Center is safety-locked: {exc}")
    st.stop()

try:
    click_events = ClickAnalyticsStore(st.secrets).list_recent(90)
except AnalyticsError:
    click_events = []

try:
    attribution_events = DwelyxAttributionStore(st.secrets).list_events(5000)
except DwelyxAttributionError:
    attribution_events = []

real_attribution_events = [event for event in attribution_events if not event.test_mode]
attribution_connected = bool(real_attribution_events)

launch_states = {}
try:
    launch_store = CampaignLaunchStore(st.secrets)
    for property_record in properties:
        property_id = str(property_record.property_id)
        launch_states[property_id] = launch_store.load(
            property_id,
            "owner_finance_homes",
        )
except LaunchStoreError:
    launch_states = {}

assessments = build_velocity_queue(
    properties,
    ledger=velocity_ledger,
    click_events=click_events,
    attribution_events=attribution_events,
    launch_states=launch_states,
    attribution_connected=attribution_connected,
)
active_assessments = [
    item for item in assessments if item.level != EscalationLevel.CLOSED
]
property_labels = {
    str(item.property_id): item.display_address for item in properties
}

critical_count = sum(
    item.level == EscalationLevel.CRITICAL for item in active_assessments
)
high_count = sum(item.level == EscalationLevel.HIGH for item in active_assessments)
open_tasks = sum(
    task.status in {EscalationTaskStatus.OPEN, EscalationTaskStatus.IN_PROGRESS}
    for task in velocity_ledger.tasks
)
holding_exposure = sum(
    (item.signals.estimated_holding_cost for item in active_assessments),
    Decimal("0"),
)

metrics = st.columns(5)
metrics[0].metric("Active Vacant Homes", len(active_assessments))
metrics[1].metric("Critical", critical_count)
metrics[2].metric("High Priority", high_count)
metrics[3].metric("Open Action Tasks", open_tasks)
metrics[4].metric(
    "Saved Holding Exposure",
    money(holding_exposure) if holding_exposure > 0 else "Not entered",
)

if attribution_connected:
    st.success(
        f"Dwelyx results are connected: {len(real_attribution_events)} live result events are available."
    )
else:
    st.info(
        "No live Dwelyx result events are available yet. Traffic can still be measured, "
        "but registration-to-contract diagnosis will remain limited until Sabrina connects Dwelyx."
    )

queue_tab, diagnosis_tab, task_tab, settings_tab = st.tabs(
    [
        "Daily Escalation Queue",
        "Property Diagnosis",
        "Action Tasks",
        "Timing & Cost Settings",
    ]
)

with queue_tab:
    st.write("### Vacant homes requiring attention")
    rows = queue_rows(active_assessments)
    if not rows:
        st.info("No active vacant homes are currently in the escalation queue.")
    else:
        queue_frame = pd.DataFrame(rows)
        st.dataframe(
            queue_frame,
            use_container_width=True,
            hide_index=True,
            height=min(700, max(250, len(rows) * 36 + 45)),
        )
        st.download_button(
            "Download Daily Escalation Queue",
            queue_frame.to_csv(index=False).encode("utf-8"),
            "vacant-home-disposition-escalation.csv",
            "text/csv",
        )
        st.caption(
            "Critical and High properties should be reviewed before the team spends time refreshing Normal properties."
        )

with diagnosis_tab:
    st.write("### Diagnose one property's conversion bottleneck")
    if not active_assessments:
        st.info("No active vacant home is available for diagnosis.")
    else:
        assessment_options = {
            f"{item.signals.address} — {item.level.value} ({item.score})": item
            for item in active_assessments
        }
        selected_label = st.selectbox(
            "Property",
            list(assessment_options),
            key="velocity_diagnosis_property",
        )
        selected = assessment_options[selected_label]
        signals = selected.signals

        summary = st.columns(6)
        summary[0].metric("Priority", selected.level.value)
        summary[1].metric("Pressure Score", selected.score)
        summary[2].metric("Days Marketed", signals.days_marketed)
        summary[3].metric("Active Channels", signals.active_channels)
        summary[4].metric("Clicks — 30 Days", signals.clicks_30)
        summary[5].metric("Contracts", signals.contracts)

        st.write(f"### Bottleneck: {selected.bottleneck.value}")
        st.error(selected.diagnosis) if selected.level == EscalationLevel.CRITICAL else st.warning(selected.diagnosis)
        st.write("**Required next action**")
        st.write(selected.primary_action)

        funnel = st.columns(5)
        funnel[0].metric("Registrations", signals.registrations)
        funnel[1].metric("Applications", signals.applications)
        funnel[2].metric("Showings", signals.showings)
        funnel[3].metric("Contracts", signals.contracts)
        funnel[4].metric("Filled", signals.filled)

        st.caption(
            f"Marketing age uses: {signals.marketing_age_source}. "
            f"Start date: {signals.marketing_started_at.astimezone().strftime('%Y-%m-%d')}."
        )
        if signals.daily_holding_cost > 0:
            st.write(
                f"Saved daily holding cost: **{money(signals.daily_holding_cost)}** · "
                f"Estimated exposure: **{money(signals.estimated_holding_cost)}**"
            )
        if selected.supporting_actions:
            st.write("**Supporting findings**")
            for action in selected.supporting_actions:
                st.write(f"- {action}")

        if selected.manager_approval_required:
            st.warning(
                "Manager approval is required. This recommendation does not authorize a price, down-payment, monthly-payment, or budget change."
            )

        profile = profile_for_property(
            velocity_ledger,
            selected.signals.property_id,
        )
        task_owner = st.text_input(
            "Assign action to",
            value=(profile.assigned_owner if profile else "Sabrina"),
            key="velocity_task_owner",
        )
        if st.button(
            "Create Recommended Action Task",
            type="primary",
            use_container_width=True,
        ):
            try:
                task = suggested_task(selected, owner=task_owner)
                velocity_ledger = add_escalation_task(velocity_ledger, task)
                velocity_store.save(velocity_ledger)
                st.session_state.velocity_message = (
                    f"Created {task.intervention_type.value} for {selected.signals.address}."
                )
                st.rerun()
            except InventoryVelocityError as exc:
                st.error(str(exc))

with task_tab:
    st.write("### Assigned disposition actions")
    rows = task_rows(velocity_ledger, property_labels)
    if not rows:
        st.info("No escalation action task has been created yet.")
    else:
        task_frame = pd.DataFrame(rows)
        st.dataframe(task_frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Action Tasks",
            task_frame.to_csv(index=False).encode("utf-8"),
            "vacant-home-action-tasks.csv",
            "text/csv",
        )

        task_options = {
            (
                f"{property_labels.get(task.property_id, task.property_id)} — "
                f"{task.intervention_type.value} — {task.status.value}"
            ): task
            for task in velocity_ledger.tasks
        }
        selected_task_label = st.selectbox(
            "Update task",
            list(task_options),
            key="velocity_task_update",
        )
        selected_task = task_options[selected_task_label]
        with st.form("update_velocity_task"):
            statuses = list(EscalationTaskStatus)
            status = st.selectbox(
                "Status",
                statuses,
                index=statuses.index(selected_task.status),
                format_func=lambda value: value.value,
            )
            owner = st.text_input("Owner", value=selected_task.owner)
            notes = st.text_area(
                "Action taken, buyer feedback, manager decision, or next step",
                value=selected_task.notes,
                height=120,
            )
            save_task = st.form_submit_button("Save Task", type="primary")
        if save_task:
            try:
                velocity_ledger = update_escalation_task(
                    velocity_ledger,
                    task_id=selected_task.task_id,
                    status=status,
                    owner=owner,
                    notes=notes,
                )
                velocity_store.save(velocity_ledger)
                st.session_state.velocity_message = (
                    f"Saved {selected_task.intervention_type.value} as {status.value}."
                )
                st.rerun()
            except InventoryVelocityError as exc:
                st.error(str(exc))

with settings_tab:
    st.write("### Set the numbers used for inventory pressure")
    st.caption(
        "Enter the real marketing start date, target fill window, and daily holding cost. "
        "The system will not invent these values."
    )
    property_options = {
        item.display_address or str(item.property_id): item for item in properties
    }
    if not property_options:
        st.info("No saved properties are available.")
    else:
        selected_property_label = st.selectbox(
            "Property",
            list(property_options),
            key="velocity_settings_property",
        )
        property_record = property_options[selected_property_label]
        property_id = str(property_record.property_id)
        profile = profile_for_property(velocity_ledger, property_id)
        default_date = (
            profile.marketing_started_at.date()
            if profile and profile.marketing_started_at
            else property_record.created_at.date()
        )
        with st.form("inventory_velocity_profile"):
            use_override = st.checkbox(
                "Use a confirmed marketing start date",
                value=bool(profile and profile.marketing_started_at),
            )
            marketing_date = st.date_input(
                "Marketing start date",
                value=default_date,
            )
            target_days = st.number_input(
                "Target days to fill",
                min_value=1,
                max_value=365,
                value=(profile.target_fill_days if profile else 21),
                step=1,
            )
            daily_cost = st.number_input(
                "Daily holding cost — enter 0 if unknown",
                min_value=0.0,
                value=float(profile.daily_holding_cost if profile else 0),
                step=1.0,
            )
            assigned_owner = st.text_input(
                "Default action owner",
                value=(profile.assigned_owner if profile else "Sabrina"),
            )
            profile_notes = st.text_area(
                "Internal notes",
                value=(profile.notes if profile else ""),
                height=100,
            )
            save_profile = st.form_submit_button(
                "Save Property Settings",
                type="primary",
            )
        if save_profile:
            marketing_started_at = (
                datetime.combine(marketing_date, time.min, tzinfo=UTC)
                if use_override
                else None
            )
            saved_profile = PropertyVelocityProfile(
                property_id=property_id,
                marketing_started_at=marketing_started_at,
                target_fill_days=int(target_days),
                daily_holding_cost=Decimal(str(daily_cost)),
                assigned_owner=assigned_owner,
                notes=profile_notes,
            )
            velocity_ledger = upsert_profile(
                velocity_ledger,
                saved_profile,
            )
            try:
                velocity_store.save(velocity_ledger)
                st.session_state.velocity_message = (
                    f"Saved escalation settings for {property_record.display_address}."
                )
                st.rerun()
            except InventoryVelocityError as exc:
                st.error(str(exc))

message = st.session_state.pop("velocity_message", "")
if message:
    st.success(message)
