from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_conversion import (
    CONTACT_ACTIVITIES,
    ActivityType,
    BuyerConversionError,
    BuyerConversionStore,
    ConversionPriority,
    ConversionStage,
    build_conversion_queue,
    build_funnel_snapshot,
    build_property_pipeline,
    contact_permissions,
    create_conversion_record,
    event_rows,
    property_pipeline_rows,
    queue_rows,
    record_activity,
    schedule_follow_up,
    transition_record,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Buyer Conversion Command Center",
    page_icon="🎯",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("AI Buyer Conversion & Follow-Up Command Center")
    st.caption("Private internal access")
    with st.form("buyer_conversion_login"):
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


def buyer_name(buyer) -> str:
    return " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip() or str(buyer.buyer_id)


def record_label(record, buyers_by_id, properties_by_id) -> str:
    buyer = buyers_by_id.get(record.buyer_id)
    property_record = properties_by_id.get(record.property_id)
    selected_buyer = buyer_name(buyer) if buyer else f"Missing buyer {record.buyer_id[:8]}"
    address = property_record.display_address if property_record else f"Missing property {record.property_id[:8]}"
    return f"{record.stage.value} — {selected_buyer} — {address}"


def combine_due(due_date: date, due_time: time) -> datetime:
    return datetime.combine(due_date, due_time, tzinfo=UTC)


def save_ledger(store, ledger, message: str) -> None:
    store.save(ledger)
    st.success(message)
    st.rerun()


require_password()
st.title("AI Buyer Conversion & Follow-Up Command Center")
st.caption(
    "Moves saved buyers from new lead to application, showing, approval, and contract while surfacing stalled files and overdue follow-up."
)
st.info(
    "This command center coordinates the team and records work completed in approved systems. It does not send email, SMS, place calls, approve buyers, or promise financing automatically."
)

try:
    storage = get_storage()
    buyers = storage.list_buyers()
    properties = storage.list_properties()
    conversion_store = BuyerConversionStore(st.secrets)
    ledger = conversion_store.load()
except (StorageError, BuyerConversionError) as exc:
    st.error(f"Buyer Conversion Command Center is safety-locked: {exc}")
    st.stop()

buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
properties_by_id = {str(item.property_id): item for item in properties}
active_records = [
    record
    for record in ledger.records
    if record.stage not in {ConversionStage.FILLED, ConversionStage.LOST}
]

pipeline_tab, add_tab, queue_tab, update_tab, property_tab, history_tab = st.tabs(
    [
        "Pipeline Board",
        "Add Buyer to Property",
        "Daily Work Queue",
        "Update Buyer Stage",
        "Property Scoreboard",
        "Audit History",
    ]
)

with pipeline_tab:
    snapshot = build_funnel_snapshot(ledger, buyers, properties)
    top_metrics = st.columns(6)
    top_metrics[0].metric("Active Buyers", snapshot.active_records)
    top_metrics[1].metric("Overdue", snapshot.overdue_records)
    top_metrics[2].metric("Compliance Holds", snapshot.compliance_holds)
    top_metrics[3].metric("Applications", snapshot.applications)
    top_metrics[4].metric("Showings", snapshot.showings)
    top_metrics[5].metric("Filled / Contracted", snapshot.filled)

    rate_metrics = st.columns(4)
    rate_metrics[0].metric("New Leads", snapshot.new_leads)
    rate_metrics[1].metric("Qualified", snapshot.qualified)
    rate_metrics[2].metric("Application Rate", f"{snapshot.application_rate:.0%}")
    rate_metrics[3].metric("Fill Rate", f"{snapshot.fill_rate:.0%}")

    st.write("### Stage distribution")
    stage_rows = [
        {
            "Stage": stage.value,
            "Buyers": sum(record.stage == stage for record in ledger.records),
        }
        for stage in ConversionStage
    ]
    st.dataframe(pd.DataFrame(stage_rows), use_container_width=True, hide_index=True)

    st.write("### Needs attention now")
    attention = [
        item
        for item in build_conversion_queue(ledger, buyers, properties)
        if item.priority in {ConversionPriority.COMPLIANCE_HOLD, ConversionPriority.URGENT, ConversionPriority.HIGH}
    ]
    if attention:
        st.dataframe(pd.DataFrame(queue_rows(attention)), use_container_width=True, hide_index=True)
    else:
        st.success("No active conversion record is overdue or on compliance hold.")

with add_tab:
    st.write("### Create a buyer/property conversion record")
    if not buyers:
        st.warning("No saved buyers are available. Add or import buyers before creating conversion records.")
    elif not properties:
        st.warning("No saved properties are available. Add a property before creating conversion records.")
    else:
        buyer_options = {f"{buyer_name(buyer)} — {buyer.email or buyer.phone or buyer.buyer_id}": buyer for buyer in buyers}
        property_options = {item.display_address or str(item.property_id): item for item in properties}
        selected_buyer_label = st.selectbox("Buyer", list(buyer_options), key="conversion_new_buyer")
        selected_property_label = st.selectbox("Property", list(property_options), key="conversion_new_property")
        selected_buyer = buyer_options[selected_buyer_label]
        selected_property = property_options[selected_property_label]
        channels, contact_block = contact_permissions(selected_buyer)

        fact_columns = st.columns(4)
        fact_columns[0].metric("Property Status", selected_property.status.value)
        fact_columns[1].metric("Permitted Contact", ", ".join(channels) or "None")
        fact_columns[2].metric(
            "Monthly Payment",
            f"${selected_property.monthly_payment:,.0f}" if selected_property.monthly_payment is not None else "Not entered",
        )
        fact_columns[3].metric(
            "Down Payment",
            f"${selected_property.down_payment:,.0f}" if selected_property.down_payment is not None else "Not entered",
        )
        if contact_block:
            st.warning(contact_block)

        with st.form("create_conversion_record"):
            owner = st.text_input("Assigned owner", value="Sabrina")
            source = st.text_input("Lead source", value=selected_buyer.source or "Dwelyx")
            campaign = st.text_input("Campaign or tracking code — optional")
            notes = st.text_area("Starting notes", height=100)
            create_record = st.form_submit_button("Create Conversion Record", type="primary")
        if create_record:
            try:
                updated = create_conversion_record(
                    ledger,
                    selected_buyer,
                    selected_property,
                    owner=owner,
                    source=source,
                    campaign=campaign,
                    notes=notes,
                )
                save_ledger(conversion_store, updated, "Buyer/property conversion record created and added to the daily queue.")
            except BuyerConversionError as exc:
                st.error(str(exc))

with queue_tab:
    st.write("### Daily follow-up queue")
    owners = sorted({record.owner for record in active_records if record.owner})
    owner_filter = st.selectbox("Assigned owner", ["All", *owners]) if owners else "All"
    queue = build_conversion_queue(
        ledger,
        buyers,
        properties,
        owner="" if owner_filter == "All" else owner_filter,
    )
    if not queue:
        st.info("No active buyer conversion records are in the queue.")
    else:
        queue_table = pd.DataFrame(queue_rows(queue))
        st.dataframe(queue_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Daily Queue CSV",
            queue_table.to_csv(index=False).encode(),
            "buyer-conversion-daily-queue.csv",
            "text/csv",
            use_container_width=True,
        )

        queue_options = {
            f"{item.priority.value} — {item.buyer_name} — {item.property_address}": item for item in queue
        }
        selected_queue_label = st.selectbox("Work one buyer", list(queue_options), key="conversion_queue_record")
        selected_item = queue_options[selected_queue_label]
        selected_record = next(record for record in ledger.records if record.record_id == selected_item.record_id)

        detail_columns = st.columns(5)
        detail_columns[0].metric("Priority", selected_item.priority.value)
        detail_columns[1].metric("Stage", selected_item.stage.value)
        detail_columns[2].metric("Owner", selected_item.owner)
        detail_columns[3].metric("Days Idle", selected_item.days_idle)
        detail_columns[4].metric("Contact Attempts", selected_item.contact_attempts)
        st.write(f"**Next action:** {selected_item.next_action or selected_item.recommended_action}")
        st.write(f"**Why it is ranked here:** {selected_item.reason}")
        st.write(f"**Permitted contact:** {', '.join(selected_item.contact_channels) or 'None'}")
        if selected_item.contact_block:
            st.error(selected_item.contact_block)

        st.write("#### Record completed activity")
        with st.form("record_conversion_activity"):
            activity_type = st.selectbox("Activity", list(ActivityType), format_func=lambda value: value.value)
            activity_actor = st.text_input("Completed by", value=selected_record.owner, key="conversion_activity_actor")
            activity_notes = st.text_area("Activity notes", height=90)
            update_next_action = st.text_input("Updated next action — optional")
            activity_due_date = st.date_input("Next-action date", value=date.today() + timedelta(days=1))
            activity_due_time = st.time_input("Next-action time", value=time(9, 0))
            save_activity = st.form_submit_button("Save Activity", type="primary")
        if save_activity:
            if activity_type in CONTACT_ACTIVITIES and selected_item.contact_block:
                st.error("This contact activity is blocked because the buyer does not have usable saved consent or is marked Do Not Contact.")
            else:
                try:
                    updated = record_activity(
                        ledger,
                        record_id=selected_item.record_id,
                        activity_type=activity_type,
                        actor=activity_actor,
                        notes=activity_notes,
                        next_action=update_next_action,
                        next_action_at=combine_due(activity_due_date, activity_due_time) if update_next_action else None,
                    )
                    save_ledger(conversion_store, updated, "Activity saved to the buyer conversion history.")
                except BuyerConversionError as exc:
                    st.error(str(exc))

        st.write("#### Reschedule follow-up")
        with st.form("schedule_conversion_follow_up"):
            scheduled_action = st.text_input("Next action", value=selected_record.next_action)
            scheduled_date = st.date_input("Due date", value=date.today() + timedelta(days=1), key="conversion_schedule_date")
            scheduled_time = st.time_input("Due time", value=time(9, 0), key="conversion_schedule_time")
            scheduled_actor = st.text_input("Scheduled by", value=selected_record.owner)
            scheduled_notes = st.text_area("Schedule notes", height=70)
            save_schedule = st.form_submit_button("Save Follow-Up Schedule")
        if save_schedule:
            try:
                updated = schedule_follow_up(
                    ledger,
                    record_id=selected_item.record_id,
                    next_action=scheduled_action,
                    next_action_at=combine_due(scheduled_date, scheduled_time),
                    actor=scheduled_actor,
                    notes=scheduled_notes,
                )
                save_ledger(conversion_store, updated, "Follow-up schedule updated.")
            except BuyerConversionError as exc:
                st.error(str(exc))

with update_tab:
    st.write("### Move a buyer to the next stage")
    if not active_records:
        st.info("No active conversion records are available to update.")
    else:
        record_options = {
            record_label(record, buyers_by_id, properties_by_id): record for record in active_records
        }
        selected_record_label = st.selectbox("Buyer/property record", list(record_options), key="conversion_stage_record")
        selected_record = record_options[selected_record_label]
        stage_options = [stage for stage in ConversionStage if stage != selected_record.stage]
        new_stage = st.selectbox("New stage", stage_options, format_func=lambda stage: stage.value)
        actor = st.text_input("Updated by", value=selected_record.owner, key="conversion_stage_actor")
        notes = st.text_area("Stage-change notes", height=100)
        lost_reason = ""
        paused_reason = ""
        if new_stage == ConversionStage.LOST:
            lost_reason = st.text_area("Lost reason*", placeholder="Example: payment did not fit, buyer chose another property, or no longer moving.")
        if new_stage == ConversionStage.PAUSED:
            paused_reason = st.text_area("Pause reason*", placeholder="Example: waiting for buyer documents or a later move date.")
        next_action = st.text_input("Next action — optional; the engine supplies a stage default when blank")
        due_columns = st.columns(2)
        due_date = due_columns[0].date_input("Next-action date", value=date.today() + timedelta(days=1), key="conversion_stage_due_date")
        due_time = due_columns[1].time_input("Next-action time", value=time(9, 0), key="conversion_stage_due_time")
        if st.button("Save Stage Change", type="primary", use_container_width=True):
            try:
                updated = transition_record(
                    ledger,
                    record_id=selected_record.record_id,
                    new_stage=new_stage,
                    actor=actor,
                    notes=notes,
                    lost_reason=lost_reason,
                    paused_reason=paused_reason,
                    next_action=next_action,
                    next_action_at=None
                    if new_stage in {ConversionStage.FILLED, ConversionStage.LOST}
                    else combine_due(due_date, due_time),
                )
                save_ledger(conversion_store, updated, f"Buyer moved to {new_stage.value}.")
            except BuyerConversionError as exc:
                st.error(str(exc))

with property_tab:
    st.write("### Buyer conversion by property")
    summaries = build_property_pipeline(ledger, buyers, properties)
    if not summaries:
        st.info("Create buyer/property conversion records to start the property scoreboard.")
    else:
        property_table = pd.DataFrame(property_pipeline_rows(summaries))
        st.dataframe(property_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Property Pipeline CSV",
            property_table.to_csv(index=False).encode(),
            "buyer-conversion-property-pipeline.csv",
            "text/csv",
            use_container_width=True,
        )
        st.warning(
            "When a property is marked Sold, every remaining active buyer for that property is elevated for immediate reassignment. The system does not contact or reassign buyers automatically."
        )

with history_tab:
    st.write("### Complete conversion audit history")
    history = event_rows(ledger, buyers, properties)
    if not history:
        st.info("Conversion activity will appear here after the first buyer/property record is created.")
    else:
        history_table = pd.DataFrame(history)
        st.dataframe(history_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Audit History CSV",
            history_table.to_csv(index=False).encode(),
            "buyer-conversion-audit-history.csv",
            "text/csv",
            use_container_width=True,
        )
