from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_conversion import (
    BuyerConversionError,
    BuyerConversionStore,
    ConversionStage,
    TERMINAL_STAGES,
)
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.showing_conversion import (
    CLOSED_SHOWING_STATUSES,
    ObjectionCategory,
    ReminderStatus,
    ReminderType,
    ShowingConversionError,
    ShowingConversionStore,
    ShowingDecision,
    ShowingStatus,
    build_property_objections,
    build_showing_funnel,
    build_showing_queue,
    cancel_appointment,
    confirm_appointment,
    contact_permissions,
    create_appointment,
    event_rows,
    find_appointment,
    objection_rows,
    queue_rows,
    record_attendance_outcome,
    record_no_show,
    reminder_rows,
    reschedule_appointment,
    sync_conversion_for_confirmation,
    sync_conversion_for_no_show,
    sync_conversion_for_outcome,
    sync_conversion_for_scheduled_showing,
    update_reminder,
)
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Showing-to-Contract Conversion Center",
    page_icon="🏠",
    layout="wide",
)

TIME_ZONES = {
    "Eastern Time": "America/New_York",
    "Central Time": "America/Chicago",
}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Showing-to-Contract Conversion Center")
    st.caption("Private internal access")
    with st.form("showing_conversion_login"):
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


def buyer_name(buyer: BuyerProfile | None, buyer_id: str) -> str:
    if buyer is None:
        return f"Buyer {buyer_id[:8]}"
    name = " ".join(part for part in (buyer.first_name, buyer.last_name) if part).strip()
    return name or f"Buyer {buyer_id[:8]}"


def property_name(property_record: OwnerFinanceProperty | None, property_id: str) -> str:
    if property_record is None:
        return f"Property {property_id[:8]}"
    return property_record.display_address or f"Property {property_id[:8]}"


def record_label(record, buyers_by_id, properties_by_id) -> str:
    return (
        f"{buyer_name(buyers_by_id.get(record.buyer_id), record.buyer_id)} — "
        f"{property_name(properties_by_id.get(record.property_id), record.property_id)} — "
        f"{record.stage.value}"
    )


def appointment_label(appointment, buyers_by_id, properties_by_id) -> str:
    return (
        f"{appointment.status.value} — "
        f"{appointment.scheduled_at.strftime('%Y-%m-%d %I:%M %p')} — "
        f"{buyer_name(buyers_by_id.get(appointment.buyer_id), appointment.buyer_id)} — "
        f"{property_name(properties_by_id.get(appointment.property_id), appointment.property_id)}"
    )


def local_reminder_message(
    reminder_type: ReminderType,
    appointment,
    property_record: OwnerFinanceProperty,
    zone_label: str,
) -> str:
    time_text = appointment.scheduled_at.strftime("%A, %B %d at %I:%M %p")
    instructions = (
        f" Approved showing instructions: {appointment.buyer_instructions.strip()}"
        if appointment.buyer_instructions.strip()
        else ""
    )
    if reminder_type == ReminderType.CONFIRMATION:
        return (
            f"Your showing for {property_record.display_address} is scheduled for "
            f"{time_text} {zone_label}.{instructions} Please confirm or contact the team "
            "if you need to reschedule."
        )
    if reminder_type == ReminderType.DAY_BEFORE:
        return (
            f"Reminder: your showing for {property_record.display_address} is tomorrow at "
            f"{time_text} {zone_label}.{instructions} Please confirm that the time still works."
        )
    if reminder_type == ReminderType.TWO_HOUR:
        return (
            f"Your showing for {property_record.display_address} is in about two hours at "
            f"{time_text} {zone_label}.{instructions} Contact the team now if your arrival time changed."
        )
    if reminder_type == ReminderType.NO_SHOW_RECOVERY:
        return (
            f"We missed you at the scheduled showing for {property_record.display_address}. "
            "Reply through your normal contact method if you still want to see the home, "
            "and the team will offer another available time."
        )
    return (
        f"Thank you for viewing {property_record.display_address}. Please share your decision, "
        "questions, or the main issue preventing you from moving forward."
    )


def localize_new_reminders(ledger, appointment, property_record, zone_label: str):
    reminders = [
        reminder.model_copy(
            update={
                "message": local_reminder_message(
                    reminder.reminder_type,
                    appointment,
                    property_record,
                    zone_label,
                )
            }
        )
        if reminder.appointment_id == appointment.appointment_id
        else reminder
        for reminder in ledger.reminders
    ]
    return ledger.model_copy(update={"reminders": reminders})


def save_ledgers(
    showing_store: ShowingConversionStore,
    conversion_store: BuyerConversionStore,
    original_showing,
    updated_showing,
    updated_conversion,
) -> None:
    showing_store.save(updated_showing)
    try:
        conversion_store.save(updated_conversion)
    except Exception:
        showing_store.save(original_showing)
        raise


require_password()
st.title("Showing-to-Contract Conversion Center")
st.caption(
    "Gets scheduled buyers to the property, recovers no-shows quickly, captures the real objection, "
    "and moves qualified buyers toward contract."
)
st.warning(
    "This center prepares reminders and follow-up work but does not send messages automatically. "
    "Only use a channel with saved buyer consent. Do not place lockbox, alarm, or access codes in buyer-facing reminder text."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    buyers = storage.list_buyers()
    showing_store = ShowingConversionStore(st.secrets)
    showing_ledger = showing_store.load()
    conversion_store = BuyerConversionStore(st.secrets)
    conversion_ledger = conversion_store.load()
except (StorageError, ShowingConversionError, BuyerConversionError) as exc:
    st.error(f"Showing-to-Contract Center is safety-locked: {exc}")
    st.stop()

buyers_by_id = {str(item.buyer_id): item for item in buyers}
properties_by_id = {str(item.property_id): item for item in properties}
records_by_id = {item.record_id: item for item in conversion_ledger.records}
appointments_by_id = {item.appointment_id: item for item in showing_ledger.appointments}

queue_tab, schedule_tab, manage_tab, reminder_tab, feedback_tab, history_tab = st.tabs(
    [
        "Daily Showing Queue",
        "Schedule Showing",
        "Record Outcome",
        "Reminder Queue",
        "Property Objections",
        "Audit History",
    ]
)

with queue_tab:
    st.write("### Today's showing and contract priorities")
    funnel = build_showing_funnel(showing_ledger)
    metrics = st.columns(6)
    metrics[0].metric("Appointments", funnel.total)
    metrics[1].metric("Confirmed", funnel.confirmed)
    metrics[2].metric("Attended", funnel.attended)
    metrics[3].metric("No Shows", funnel.no_shows)
    metrics[4].metric("Contract Handoffs", funnel.contract_handoffs)
    metrics[5].metric("Showing → Contract", f"{funnel.showing_to_contract_rate:.1%}")

    owners = sorted({item.owner for item in showing_ledger.appointments if item.owner})
    owner_filter = st.selectbox("Owner filter", ["All", *owners])
    queue = build_showing_queue(
        showing_ledger,
        buyers,
        properties,
        owner="" if owner_filter == "All" else owner_filter,
    )
    if not queue:
        st.info("No active showing work is in the queue.")
    else:
        queue_frame = pd.DataFrame(queue_rows(queue))
        st.dataframe(queue_frame, use_container_width=True, hide_index=True, height=560)
        st.download_button(
            "Download Daily Showing Queue",
            queue_frame.to_csv(index=False).encode("utf-8"),
            "daily-showing-queue.csv",
            "text/csv",
        )

with schedule_tab:
    st.write("### Schedule a buyer showing")
    active_records = [
        record
        for record in conversion_ledger.records
        if record.stage not in TERMINAL_STAGES
        and record.buyer_id in buyers_by_id
        and record.property_id in properties_by_id
    ]
    if not active_records:
        st.info("No active buyer/property conversion record is available.")
    else:
        record_options = {
            record_label(record, buyers_by_id, properties_by_id): record
            for record in active_records
        }
        selected_record_label = st.selectbox(
            "Buyer and property",
            list(record_options),
            key="showing_schedule_record",
        )
        selected_record = record_options[selected_record_label]
        selected_buyer = buyers_by_id[selected_record.buyer_id]
        selected_property = properties_by_id[selected_record.property_id]
        channels, contact_block = contact_permissions(selected_buyer)
        if contact_block:
            st.error(f"Reminder compliance hold: {contact_block}")
        else:
            st.success(f"Permitted reminder channels: {', '.join(channels)}")

        with st.form("schedule_showing_form"):
            date_column, time_column, zone_column = st.columns(3)
            showing_date = date_column.date_input(
                "Showing date",
                value=date.today() + timedelta(days=1),
            )
            showing_time = time_column.time_input(
                "Showing time",
                value=time(hour=12, minute=0),
            )
            zone_label = zone_column.selectbox("Showing time zone", list(TIME_ZONES))
            owner = st.text_input("Showing owner", value=selected_record.owner or "Sabrina")
            duration = st.number_input(
                "Expected duration in minutes",
                min_value=10,
                max_value=240,
                value=30,
                step=5,
            )
            access_method = st.text_input(
                "Access method",
                value="Team-coordinated access",
                help="Examples: team member meets buyer, agent access, or approved self-showing process.",
            )
            buyer_instructions = st.text_area(
                "Buyer-facing instructions",
                value=selected_property.showing_instructions,
                help="Do not include lockbox, alarm, or permanent access codes.",
                height=100,
            )
            internal_access_notes = st.text_area(
                "Private access notes",
                help="Private team notes only. Do not copy these into buyer reminders.",
                height=100,
            )
            confirmed = st.checkbox(
                "I verified the property is available and the showing time is correct."
            )
            submit = st.form_submit_button(
                "Schedule Showing",
                type="primary",
                disabled=not confirmed,
            )
        if submit:
            try:
                zone = ZoneInfo(TIME_ZONES[zone_label])
                scheduled_local = datetime.combine(showing_date, showing_time, tzinfo=zone)
                original_showing = showing_ledger
                updated_showing, appointment = create_appointment(
                    showing_ledger,
                    conversion_ledger,
                    selected_buyer,
                    selected_property,
                    conversion_record_id=selected_record.record_id,
                    scheduled_at=scheduled_local,
                    owner=owner,
                    duration_minutes=int(duration),
                    access_method=access_method,
                    buyer_instructions=buyer_instructions,
                    internal_access_notes=internal_access_notes,
                )
                updated_showing = localize_new_reminders(
                    updated_showing,
                    appointment,
                    selected_property,
                    zone_label,
                )
                updated_conversion = sync_conversion_for_scheduled_showing(
                    conversion_ledger,
                    appointment,
                    actor=owner,
                )
                save_ledgers(
                    showing_store,
                    conversion_store,
                    original_showing,
                    updated_showing,
                    updated_conversion,
                )
                st.success("Showing scheduled and the buyer conversion record was updated.")
                st.rerun()
            except (ShowingConversionError, BuyerConversionError, StorageError, ValueError) as exc:
                st.error(str(exc))

with manage_tab:
    st.write("### Confirm, reschedule, or record the showing outcome")
    manageable = [
        item
        for item in showing_ledger.appointments
        if item.status not in CLOSED_SHOWING_STATUSES
    ]
    if not manageable:
        st.info("No active showing is available to manage.")
    else:
        appointment_options = {
            appointment_label(item, buyers_by_id, properties_by_id): item
            for item in manageable
        }
        selected_label = st.selectbox(
            "Showing",
            list(appointment_options),
            key="showing_manage_appointment",
        )
        selected = appointment_options[selected_label]
        selected_buyer = buyers_by_id.get(selected.buyer_id)
        selected_property = properties_by_id.get(selected.property_id)
        selected_record = records_by_id.get(selected.conversion_record_id)

        summary = st.columns(5)
        summary[0].metric("Status", selected.status.value)
        summary[1].metric("Buyer", buyer_name(selected_buyer, selected.buyer_id))
        summary[2].metric("Property", property_name(selected_property, selected.property_id))
        summary[3].metric("Reschedules", selected.reschedule_count)
        summary[4].metric("Conversion Stage", selected_record.stage.value if selected_record else "Missing")
        st.caption(f"Private access method: {selected.access_method}")
        if selected.internal_access_notes:
            with st.expander("Private access notes"):
                st.write(selected.internal_access_notes)

        action = st.selectbox(
            "Action",
            [
                "Confirm Showing",
                "Reschedule Showing",
                "Record No Show",
                "Record Attended Outcome",
                "Cancel Showing",
            ],
        )

        if action == "Confirm Showing":
            with st.form("confirm_showing_form"):
                actor = st.text_input("Confirmed by", value=selected.owner or "Sabrina")
                notes = st.text_area("Confirmation notes", height=90)
                submit = st.form_submit_button("Confirm Showing", type="primary")
            if submit:
                try:
                    original_showing = showing_ledger
                    updated_showing = confirm_appointment(
                        showing_ledger,
                        appointment_id=selected.appointment_id,
                        actor=actor,
                        notes=notes,
                    )
                    updated_appointment = find_appointment(updated_showing, selected.appointment_id)
                    updated_conversion = sync_conversion_for_confirmation(
                        conversion_ledger,
                        updated_appointment,
                        actor=actor,
                    )
                    save_ledgers(
                        showing_store,
                        conversion_store,
                        original_showing,
                        updated_showing,
                        updated_conversion,
                    )
                    st.success("Showing confirmed and conversion follow-up updated.")
                    st.rerun()
                except (ShowingConversionError, BuyerConversionError, StorageError) as exc:
                    st.error(str(exc))

        elif action == "Reschedule Showing":
            with st.form("reschedule_showing_form"):
                date_column, time_column, zone_column = st.columns(3)
                new_date = date_column.date_input(
                    "New date",
                    value=max(date.today() + timedelta(days=1), selected.scheduled_at.date()),
                    key="reschedule_date",
                )
                new_time = time_column.time_input(
                    "New time",
                    value=selected.scheduled_at.time().replace(tzinfo=None),
                    key="reschedule_time",
                )
                zone_label = zone_column.selectbox(
                    "Time zone",
                    list(TIME_ZONES),
                    key="reschedule_zone",
                )
                actor = st.text_input("Rescheduled by", value=selected.owner or "Sabrina")
                reason = st.text_area("Reason for reschedule", height=90)
                submit = st.form_submit_button("Save New Showing Time", type="primary")
            if submit:
                if selected_property is None:
                    st.error("The property record is missing.")
                else:
                    try:
                        zone = ZoneInfo(TIME_ZONES[zone_label])
                        new_local = datetime.combine(new_date, new_time, tzinfo=zone)
                        original_showing = showing_ledger
                        updated_showing = reschedule_appointment(
                            showing_ledger,
                            selected_buyer,
                            selected_property,
                            appointment_id=selected.appointment_id,
                            new_scheduled_at=new_local,
                            actor=actor,
                            reason=reason,
                        )
                        updated_appointment = find_appointment(updated_showing, selected.appointment_id)
                        updated_showing = localize_new_reminders(
                            updated_showing,
                            updated_appointment,
                            selected_property,
                            zone_label,
                        )
                        updated_conversion = sync_conversion_for_scheduled_showing(
                            conversion_ledger,
                            updated_appointment,
                            actor=actor,
                        )
                        save_ledgers(
                            showing_store,
                            conversion_store,
                            original_showing,
                            updated_showing,
                            updated_conversion,
                        )
                        st.success("Showing rescheduled and new reminders prepared.")
                        st.rerun()
                    except (ShowingConversionError, BuyerConversionError, StorageError, ValueError) as exc:
                        st.error(str(exc))

        elif action == "Record No Show":
            with st.form("record_no_show_form"):
                actor = st.text_input("Recorded by", value=selected.owner or "Sabrina")
                notes = st.text_area("No-show notes", height=90)
                submit = st.form_submit_button("Record No Show", type="primary")
            if submit:
                if selected_property is None:
                    st.error("The property record is missing.")
                else:
                    try:
                        original_showing = showing_ledger
                        updated_showing = record_no_show(
                            showing_ledger,
                            selected_buyer,
                            selected_property,
                            appointment_id=selected.appointment_id,
                            actor=actor,
                            notes=notes,
                        )
                        updated_appointment = find_appointment(updated_showing, selected.appointment_id)
                        updated_conversion = sync_conversion_for_no_show(
                            conversion_ledger,
                            updated_appointment,
                            actor=actor,
                        )
                        save_ledgers(
                            showing_store,
                            conversion_store,
                            original_showing,
                            updated_showing,
                            updated_conversion,
                        )
                        st.success("No show recorded. Recovery follow-up is now urgent.")
                        st.rerun()
                    except (ShowingConversionError, BuyerConversionError, StorageError) as exc:
                        st.error(str(exc))

        elif action == "Record Attended Outcome":
            with st.form("record_showing_outcome_form"):
                actor = st.text_input("Recorded by", value=selected.owner or "Sabrina")
                decision = st.selectbox(
                    "Buyer decision",
                    [
                        ShowingDecision.INTERESTED,
                        ShowingDecision.NEEDS_FOLLOW_UP,
                        ShowingDecision.REQUESTED_TERMS_REVIEW,
                        ShowingDecision.READY_FOR_CONTRACT,
                        ShowingDecision.NOT_INTERESTED,
                    ],
                    format_func=lambda value: value.value,
                )
                objection = st.selectbox(
                    "Primary objection",
                    list(ObjectionCategory),
                    format_func=lambda value: value.value,
                )
                objection_notes = st.text_area(
                    "Exact objection notes",
                    placeholder="Record what the buyer actually said. Do not guess or rewrite it.",
                    height=100,
                )
                feedback = st.text_area(
                    "Showing feedback and decision notes",
                    height=110,
                )
                target_options = [
                    ConversionStage.SHOWING_COMPLETED,
                    ConversionStage.APPROVED,
                    ConversionStage.CONTRACT_PENDING,
                    ConversionStage.LOST,
                ]
                default_target = (
                    ConversionStage.CONTRACT_PENDING
                    if decision == ShowingDecision.READY_FOR_CONTRACT
                    else ConversionStage.LOST
                    if decision == ShowingDecision.NOT_INTERESTED
                    else ConversionStage.SHOWING_COMPLETED
                )
                target_stage = st.selectbox(
                    "Buyer conversion stage after this outcome",
                    target_options,
                    index=target_options.index(default_target),
                    format_func=lambda value: value.value,
                )
                lost_reason = st.text_input(
                    "Lost reason — required only when moving to Lost",
                    value="Buyer declined after showing" if target_stage == ConversionStage.LOST else "",
                )
                submit = st.form_submit_button("Save Showing Outcome", type="primary")
            if submit:
                if selected_property is None:
                    st.error("The property record is missing.")
                else:
                    try:
                        original_showing = showing_ledger
                        updated_showing = record_attendance_outcome(
                            showing_ledger,
                            selected_buyer,
                            selected_property,
                            appointment_id=selected.appointment_id,
                            actor=actor,
                            decision=decision,
                            objection_category=objection,
                            objection_notes=objection_notes,
                            feedback_summary=feedback,
                        )
                        updated_appointment = find_appointment(updated_showing, selected.appointment_id)
                        updated_conversion = sync_conversion_for_outcome(
                            conversion_ledger,
                            updated_appointment,
                            actor=actor,
                            target_stage=target_stage,
                            lost_reason=lost_reason,
                        )
                        save_ledgers(
                            showing_store,
                            conversion_store,
                            original_showing,
                            updated_showing,
                            updated_conversion,
                        )
                        st.success("Showing outcome and buyer conversion stage saved.")
                        st.rerun()
                    except (ShowingConversionError, BuyerConversionError, StorageError) as exc:
                        st.error(str(exc))

        else:
            with st.form("cancel_showing_form"):
                actor = st.text_input("Cancelled by", value=selected.owner or "Sabrina")
                reason = st.text_area("Cancellation reason", height=100)
                submit = st.form_submit_button("Cancel Showing", type="primary")
            if submit:
                try:
                    updated_showing = cancel_appointment(
                        showing_ledger,
                        appointment_id=selected.appointment_id,
                        actor=actor,
                        reason=reason,
                    )
                    showing_store.save(updated_showing)
                    st.success("Showing cancelled and remaining reminders skipped.")
                    st.rerun()
                except (ShowingConversionError, StorageError) as exc:
                    st.error(str(exc))

with reminder_tab:
    st.write("### Consent-safe reminder and no-show message queue")
    pending_reminders = [
        reminder
        for reminder in showing_ledger.reminders
        if reminder.status in {ReminderStatus.READY, ReminderStatus.APPROVED, ReminderStatus.FAILED}
    ]
    if not pending_reminders:
        st.info("No reminder is waiting for review or manual sending.")
    else:
        reminder_frame = pd.DataFrame(reminder_rows(pending_reminders))
        st.dataframe(reminder_frame, use_container_width=True, hide_index=True, height=500)
        reminder_options = {
            (
                f"{item.status.value} — {item.reminder_type.value} — {item.channel} — "
                f"{item.scheduled_for.strftime('%Y-%m-%d %I:%M %p')}"
            ): item
            for item in pending_reminders
        }
        selected_label = st.selectbox(
            "Reminder",
            list(reminder_options),
            key="showing_reminder_selection",
        )
        selected_reminder = reminder_options[selected_label]
        appointment = appointments_by_id.get(selected_reminder.appointment_id)
        buyer = buyers_by_id.get(appointment.buyer_id) if appointment else None
        channels, contact_block = contact_permissions(buyer)
        st.text_area(
            "Copy-ready message",
            value=selected_reminder.message,
            height=150,
            disabled=True,
        )
        if contact_block:
            st.error(f"Do not send: {contact_block}")
        else:
            st.success(f"Currently permitted contact channels: {', '.join(channels)}")
        with st.form("update_showing_reminder_form"):
            status_options = [
                ReminderStatus.APPROVED,
                ReminderStatus.SENT_MANUALLY,
                ReminderStatus.SKIPPED,
                ReminderStatus.FAILED,
            ]
            new_status = st.selectbox(
                "Reminder status",
                status_options,
                format_func=lambda value: value.value,
            )
            actor = st.text_input("Updated by", value=appointment.owner if appointment else "Sabrina")
            notes = st.text_area("Notes", height=90)
            submit = st.form_submit_button("Save Reminder Status", type="primary")
        if submit:
            if contact_block and new_status in {ReminderStatus.APPROVED, ReminderStatus.SENT_MANUALLY}:
                st.error("The reminder cannot be approved or marked sent while contact permission is blocked.")
            elif new_status == ReminderStatus.SENT_MANUALLY and selected_reminder.channel not in channels:
                st.error("The saved reminder channel is not currently permitted for this buyer.")
            else:
                try:
                    updated_showing = update_reminder(
                        showing_ledger,
                        reminder_id=selected_reminder.reminder_id,
                        status=new_status,
                        actor=actor,
                        notes=notes,
                    )
                    showing_store.save(updated_showing)
                    st.success(f"Reminder saved as {new_status.value}.")
                    st.rerun()
                except (ShowingConversionError, StorageError) as exc:
                    st.error(str(exc))

with feedback_tab:
    st.write("### Property showing objections and conversion patterns")
    summaries = build_property_objections(showing_ledger, properties)
    if not summaries:
        st.info("Record attended showing outcomes before objection patterns appear.")
    else:
        objection_frame = pd.DataFrame(objection_rows(summaries))
        st.dataframe(objection_frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Property Objection Report",
            objection_frame.to_csv(index=False).encode("utf-8"),
            "property-showing-objections.csv",
            "text/csv",
        )
        st.info(
            "Repeated price, down-payment, monthly-payment, interest, or term objections should be reviewed in the Property Terms Test & Relaunch Center. "
            "Repeated condition objections should be verified against the actual property record before changing marketing language."
        )
        st.page_link(
            "pages/21_Property_Terms_Test_Relaunch.py",
            label="Open Property Terms Test & Relaunch Center",
            icon="⚖️",
        )

with history_tab:
    st.write("### Permanent showing audit history")
    history = event_rows(showing_ledger)
    if not history:
        st.info("No showing event has been recorded.")
    else:
        history_frame = pd.DataFrame(history)
        st.dataframe(history_frame, use_container_width=True, hide_index=True, height=560)
        st.download_button(
            "Download Showing Audit History",
            history_frame.to_csv(index=False).encode("utf-8"),
            "showing-audit-history.csv",
            "text/csv",
        )
