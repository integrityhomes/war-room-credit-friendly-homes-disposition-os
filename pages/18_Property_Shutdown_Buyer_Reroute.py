from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.automatic_launch import AutomationDispatchSettings
from cfh_disposition.buyer_conversion import (
    BuyerConversionError,
    BuyerConversionStore,
    TERMINAL_STAGES,
)
from cfh_disposition.campaign_launch import (
    CampaignLaunchStore,
    LaunchStatus,
    LaunchStoreError,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.property_shutdown import (
    ControlDispatchStatus,
    ControlOperation,
    ControlTaskStatus,
    MarketingControlAction,
    PropertyControlError,
    PropertyControlStore,
    append_control_event,
    build_buyer_reroute_tasks,
    build_channel_control_tasks,
    build_property_control_event,
    buyer_task_rows,
    campaign_state_after_control,
    channel_task_rows,
    dispatch_property_control,
    event_history_rows,
    find_control_event,
    mark_control_dispatch,
    update_buyer_task,
    update_channel_task,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Property Shutdown & Buyer Reroute Center",
    page_icon="🛑",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Property Shutdown & Buyer Reroute Center")
    st.caption("Private internal access")
    with st.form("property_control_login"):
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


def active_records_for_property(conversion_ledger, property_id: str):
    return [record for record in conversion_ledger.records if record.property_id == property_id and record.stage not in TERMINAL_STAGES]


def buyer_label(record, buyers_by_id) -> str:
    buyer = buyers_by_id.get(record.buyer_id)
    if buyer:
        name = " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()
    else:
        name = ""
    return f"{name or 'Buyer ' + record.buyer_id[:8]} — {record.stage.value} — owner: {record.owner or 'Unassigned'}"


def sync_campaign_state(event, dispatch_status) -> None:
    try:
        campaign_store = CampaignLaunchStore(st.secrets)
        state = campaign_store.load(event.property_id, event.campaign)
        state = state or new_launch_state(event.property_id, event.campaign)
        state = campaign_state_after_control(
            state,
            event,
            dispatch_status=dispatch_status,
        )
        campaign_store.save(state)
    except LaunchStoreError:
        return


def sync_one_channel(event, channel_key: str, task_status: ControlTaskStatus) -> None:
    try:
        campaign_store = CampaignLaunchStore(st.secrets)
        state = campaign_store.load(event.property_id, event.campaign)
        if state is None:
            return
        if task_status == ControlTaskStatus.CONFIRMED:
            launch_status = LaunchStatus.POSTED if event.operation == ControlOperation.RESUME else LaunchStatus.PAUSED
        elif task_status == ControlTaskStatus.DISPATCHED:
            launch_status = LaunchStatus.SCHEDULED if event.operation == ControlOperation.RESUME else LaunchStatus.PAUSED
        elif task_status == ControlTaskStatus.FAILED:
            launch_status = LaunchStatus.FAILED
        else:
            launch_status = LaunchStatus.READY
        state = set_channel_status(
            state,
            channel_key,
            launch_status,
            updated_by="Property Control Center",
            notes="Updated from the property shutdown and buyer reroute task board.",
        )
        campaign_store.save(state)
    except LaunchStoreError:
        return


require_password()
st.title("Property Shutdown & Buyer Reroute Center")
st.caption("Stops or restores one property across all 15 marketing channels, protects public availability, and creates buyer reassignment work.")
st.warning(
    "Saving Pending, Filled, Sold, or Paused immediately removes the property "
    "from the Credit Friendly Homes public portal. External platforms are not "
    "treated as stopped until their task or publishing-workflow result is confirmed."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    buyers = storage.list_buyers()
    control_store = PropertyControlStore(st.secrets)
    control_ledger = control_store.load()
    conversion_store = BuyerConversionStore(st.secrets)
    conversion_ledger = conversion_store.load()
except (StorageError, PropertyControlError, BuyerConversionError) as exc:
    st.error(f"Property Control Center is safety-locked: {exc}")
    st.stop()

if not properties:
    st.info("No saved properties are available.")
    st.stop()

buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
property_options = {f"{item.display_address} — {item.status.value}": item for item in properties}

control_tab, channel_tab, buyer_tab, history_tab = st.tabs(
    [
        "Control Property",
        "15-Channel Task Board",
        "Buyer Reroute Queue",
        "Audit History",
    ]
)

with control_tab:
    st.write("### Shut down, pause, or resume a property")
    selected_label = st.selectbox("Property", list(property_options))
    selected = property_options[selected_label]
    action = st.selectbox(
        "Action",
        list(MarketingControlAction),
        format_func=lambda value: value.value,
    )
    active_records = active_records_for_property(
        conversion_ledger,
        str(selected.property_id),
    )

    metrics = st.columns(5)
    metrics[0].metric("Current Status", selected.status.value)
    metrics[1].metric("New Status", action.value)
    metrics[2].metric("Marketing Channels", 15)
    metrics[3].metric("Active Buyer Records", len(active_records))
    metrics[4].metric(
        "Public Page",
        "Restores" if action == MarketingControlAction.RESUME else "Hides Immediately",
    )

    winning_record_id = ""
    if active_records and action in {
        MarketingControlAction.PENDING,
        MarketingControlAction.FILLED,
        MarketingControlAction.SOLD,
    }:
        winner_options = {"No buyer selected — reroute every active buyer": ""}
        winner_options.update({buyer_label(record, buyers_by_id): record.record_id for record in active_records})
        winner_label = st.selectbox(
            "Buyer staying with this property — optional",
            list(winner_options),
            help=("The selected buyer remains attached to the pending contract or filled home. Every other active buyer receives a reroute task."),
        )
        winning_record_id = winner_options[winner_label]

    preview_channels = build_channel_control_tasks(action)
    preview_buyers = build_buyer_reroute_tasks(
        conversion_ledger,
        buyers,
        property_id=str(selected.property_id),
        action=action,
        winning_conversion_record_id=winning_record_id,
    )
    with st.expander("Preview all 15 channel actions", expanded=False):
        preview_frame = pd.DataFrame(
            [
                {
                    "Channel": task.channel_name,
                    "Operation": task.operation.value,
                    "Manual Confirmation": ("Yes" if task.requires_manual_confirmation else "No"),
                    "Instruction": task.instruction,
                }
                for task in preview_channels
            ]
        )
        st.dataframe(
            preview_frame,
            use_container_width=True,
            hide_index=True,
            height=570,
        )
    if preview_buyers:
        with st.expander("Preview buyer reroute work", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Buyer": task.buyer_name,
                            "Stage": task.current_stage,
                            "Owner": task.owner,
                            "Action": task.action,
                        }
                        for task in preview_buyers
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    with st.form("property_control_form"):
        campaign = st.text_input("Campaign name", value="owner_finance_homes")
        requested_by = st.text_input("Authorized by", value="Sabrina")
        reason = st.text_area(
            "Reason*",
            placeholder=("Examples: contract signed, buyer moved in, property sold, repairs in progress, or pending contract fell through."),
            height=100,
        )
        notes = st.text_area("Internal notes — optional", height=90)
        confirmed = st.checkbox("I confirm this status is accurate and understand that public visibility changes immediately.")
        submit = st.form_submit_button(
            "Apply Property Control Action",
            type="primary",
            disabled=not confirmed,
        )

    if submit:
        try:
            updated_property, event = build_property_control_event(
                selected,
                action,
                reason=reason,
                requested_by=requested_by,
                campaign=campaign,
                notes=notes,
                conversion_ledger=conversion_ledger,
                buyers=buyers,
                winning_conversion_record_id=winning_record_id,
            )
            storage.save_property(updated_property)
            updated_ledger = append_control_event(control_ledger, event)
            control_store.save(updated_ledger)

            settings = AutomationDispatchSettings.from_mapping(st.secrets)
            if settings.configured:
                try:
                    receipt = dispatch_property_control(event, settings)
                    dispatch_status = ControlDispatchStatus.SUCCEEDED
                    dispatch_detail = f"Publishing workflow accepted the request with HTTP {receipt.status_code}."
                except PropertyControlError as exc:
                    dispatch_status = ControlDispatchStatus.FAILED
                    dispatch_detail = str(exc)
            else:
                dispatch_status = ControlDispatchStatus.NOT_CONFIGURED
                dispatch_detail = "No publishing webhook is configured. Complete the saved external-channel tasks manually."

            updated_ledger = mark_control_dispatch(
                updated_ledger,
                event_id=event.event_id,
                status=dispatch_status,
                detail=dispatch_detail,
            )
            control_store.save(updated_ledger)
            updated_event = find_control_event(updated_ledger, event.event_id)
            if updated_event:
                sync_campaign_state(updated_event, dispatch_status)

            st.session_state.property_control_message = f"{selected.display_address} changed from {selected.status.value} to {updated_property.status.value}. {dispatch_detail}"
            st.rerun()
        except (PropertyControlError, StorageError) as exc:
            st.error(str(exc))

    message = st.session_state.pop("property_control_message", "")
    if message:
        st.success(message)

with channel_tab:
    st.write("### Channel removal, pause, and resume tasks")
    if not control_ledger.events:
        st.info("No property control event has been created yet.")
    else:
        event_options = {
            (f"{event.requested_at.astimezone().strftime('%Y-%m-%d %I:%M %p')} — {event.property_address} — {event.action.value}"): event
            for event in sorted(
                control_ledger.events,
                key=lambda item: item.requested_at,
                reverse=True,
            )
        }
        event_label = st.selectbox(
            "Property control event",
            list(event_options),
            key="channel_control_event",
        )
        selected_event = event_options[event_label]
        channel_frame = pd.DataFrame(channel_task_rows(selected_event))
        st.dataframe(
            channel_frame,
            use_container_width=True,
            hide_index=True,
            height=570,
        )
        st.download_button(
            "Download 15-Channel Control Tasks",
            channel_frame.to_csv(index=False).encode("utf-8"),
            "property-control-channel-tasks.csv",
            "text/csv",
        )

        task_options = {f"{task.channel_name} — {task.status.value}": task for task in selected_event.channel_tasks}
        task_label = st.selectbox(
            "Update one channel",
            list(task_options),
            key="channel_control_task",
        )
        selected_task = task_options[task_label]
        with st.form("update_channel_control_task"):
            statuses = list(ControlTaskStatus)
            task_status = st.selectbox(
                "Task status",
                statuses,
                index=statuses.index(selected_task.status),
                format_func=lambda value: value.value,
            )
            task_operator = st.text_input("Updated by", value="Sabrina")
            task_notes = st.text_area(
                "Confirmation, listing URL, post location, ad ID, or failure notes",
                value=selected_task.notes,
                height=100,
            )
            save_task = st.form_submit_button("Save Channel Task", type="primary")
        if save_task:
            try:
                updated_ledger = update_channel_task(
                    control_ledger,
                    event_id=selected_event.event_id,
                    channel_key=selected_task.channel_key,
                    status=task_status,
                    updated_by=task_operator,
                    notes=task_notes,
                )
                control_store.save(updated_ledger)
                updated_event = find_control_event(
                    updated_ledger,
                    selected_event.event_id,
                )
                if updated_event:
                    sync_one_channel(
                        updated_event,
                        selected_task.channel_key,
                        task_status,
                    )
                st.success(f"{selected_task.channel_name} saved as {task_status.value}.")
                st.rerun()
            except PropertyControlError as exc:
                st.error(str(exc))

with buyer_tab:
    st.write("### Buyers who need another available home")
    events_with_buyers = [event for event in control_ledger.events if event.buyer_tasks]
    if not events_with_buyers:
        st.info("No buyer reroute tasks exist yet. They will populate from the Buyer Conversion Command Center after Dwelyx is connected and active buyer records exist.")
    else:
        event_options = {
            (f"{event.property_address} — {event.action.value} — {event.requested_at.astimezone().strftime('%Y-%m-%d %I:%M %p')}"): event
            for event in sorted(
                events_with_buyers,
                key=lambda item: item.requested_at,
                reverse=True,
            )
        }
        event_label = st.selectbox(
            "Property event",
            list(event_options),
            key="buyer_control_event",
        )
        selected_event = event_options[event_label]
        buyer_frame = pd.DataFrame(buyer_task_rows(selected_event))
        st.dataframe(
            buyer_frame,
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            "Download Buyer Reroute Queue",
            buyer_frame.to_csv(index=False).encode("utf-8"),
            "buyer-reroute-queue.csv",
            "text/csv",
        )

        task_options = {f"{task.buyer_name} — {task.current_stage} — {task.status.value}": task for task in selected_event.buyer_tasks}
        task_label = st.selectbox(
            "Update one buyer",
            list(task_options),
            key="buyer_control_task",
        )
        selected_task = task_options[task_label]
        with st.form("update_buyer_reroute_task"):
            statuses = list(ControlTaskStatus)
            task_status = st.selectbox(
                "Reroute status",
                statuses,
                index=statuses.index(selected_task.status),
                format_func=lambda value: value.value,
            )
            task_operator = st.text_input(
                "Updated by",
                value=selected_task.owner or "Sabrina",
            )
            task_notes = st.text_area(
                "New property, buyer response, or follow-up notes",
                value=selected_task.notes,
                height=100,
            )
            save_task = st.form_submit_button("Save Buyer Task", type="primary")
        if save_task:
            try:
                updated_ledger = update_buyer_task(
                    control_ledger,
                    event_id=selected_event.event_id,
                    conversion_record_id=selected_task.conversion_record_id,
                    status=task_status,
                    updated_by=task_operator,
                    notes=task_notes,
                )
                control_store.save(updated_ledger)
                st.success(f"{selected_task.buyer_name} saved as {task_status.value}.")
                st.rerun()
            except PropertyControlError as exc:
                st.error(str(exc))

with history_tab:
    st.write("### Permanent property control audit history")
    history = event_history_rows(control_ledger)
    if not history:
        st.info("No property shutdown, pause, sold, filled, or resume event has been recorded.")
    else:
        history_frame = pd.DataFrame(history)
        st.dataframe(history_frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Property Control History",
            history_frame.to_csv(index=False).encode("utf-8"),
            "property-control-history.csv",
            "text/csv",
        )
