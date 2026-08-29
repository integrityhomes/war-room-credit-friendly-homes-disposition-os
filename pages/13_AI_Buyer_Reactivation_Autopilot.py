from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_intent import (
    BuyerIntentError,
    BuyerIntentStore,
    OutreachChannel,
    build_match,
    build_match_queue,
    record_outreach,
    record_signal,
)
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES
from cfh_disposition.reactivation_autopilot import (
    ReactivationAutopilotError,
    ReactivationAutopilotStore,
    ReactivationDispatchSettings,
    ReactivationJob,
    ReactivationJobStatus,
    approve_job,
    build_reactivation_jobs,
    cancel_job,
    dispatch_job,
    due_jobs,
    engagement_stop_reason,
    job_rows,
    record_dispatch_failure,
    record_dispatch_success,
    stop_job_for_engagement,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Buyer Reactivation Autopilot",
    page_icon="🚀",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("AI Buyer Reactivation Autopilot")
    st.caption("Private internal access")
    with st.form("reactivation_autopilot_login"):
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


def job_label(job: ReactivationJob) -> str:
    return (
        f"{job.score} — {job.buyer_name} → {job.property_address} — "
        f"{job.channel.value} [{job.status.value}]"
    )


def fresh_match_for_job(job: ReactivationJob, buyers_by_id, properties_by_id, intent_ledger, dwelyx_url):
    buyer = buyers_by_id.get(job.buyer_id)
    property_record = properties_by_id.get(job.property_id)
    if not buyer or not property_record:
        raise ReactivationAutopilotError("The buyer or property record for this job no longer exists.")
    return build_match(buyer, property_record, intent_ledger, dwelyx_url)


def dispatch_one(job, autopilot_ledger, intent_ledger, settings, buyers_by_id, properties_by_id, dwelyx_url):
    stop_reason = engagement_stop_reason(intent_ledger, job)
    if stop_reason:
        updated = stop_job_for_engagement(autopilot_ledger, job_id=job.job_id, reason=stop_reason)
        return updated, intent_ledger, "stopped", stop_reason

    property_record = properties_by_id.get(job.property_id)
    if not property_record or property_record.status not in MARKETABLE_PROPERTY_STATUSES:
        reason = "The property is no longer Ready to Launch or Marketing Live, so this outreach was cancelled."
        updated = cancel_job(autopilot_ledger, job_id=job.job_id, notes=reason)
        return updated, intent_ledger, "cancelled", reason

    current_match = fresh_match_for_job(
        job,
        buyers_by_id,
        properties_by_id,
        intent_ledger,
        dwelyx_url,
    )
    allowed = current_match.email_allowed if job.channel == OutreachChannel.EMAIL else current_match.sms_allowed
    if not allowed:
        reason = "Current consent, contact information, Do Not Contact status, or channel cooldown blocks this outreach."
        updated = cancel_job(autopilot_ledger, job_id=job.job_id, notes=reason)
        return updated, intent_ledger, "cancelled", reason

    try:
        receipt = dispatch_job(job, settings)
    except ReactivationAutopilotError as exc:
        updated = record_dispatch_failure(autopilot_ledger, job_id=job.job_id, error=str(exc))
        return updated, intent_ledger, "failed", str(exc)

    updated_autopilot = record_dispatch_success(
        autopilot_ledger,
        job_id=job.job_id,
        receipt=receipt,
    )
    updated_intent = record_outreach(
        intent_ledger,
        current_match,
        channel=job.channel,
        sent_by=job.approved_by or "Approved operator",
        outcome="Dispatched via automation webhook",
        notes=f"Autopilot job {job.job_id}. {receipt.response_text}".strip(),
        sent_at=receipt.dispatched_at,
    )
    return updated_autopilot, updated_intent, "dispatched", receipt.response_text


require_password()
st.title("AI Buyer Reactivation Autopilot")
st.caption(
    "One buyer-reactivation workspace for intent scoring, engagement signals, consent-checked sequences, "
    "approval, dispatch, cooldowns, and history."
)

try:
    storage = get_storage()
    buyers = storage.list_buyers()
    properties = storage.list_properties()
    intent_store = BuyerIntentStore(st.secrets)
    intent_ledger = intent_store.load()
    autopilot_store = ReactivationAutopilotStore(st.secrets)
    autopilot_ledger = autopilot_store.load()
except (StorageError, BuyerIntentError, ReactivationAutopilotError) as exc:
    st.error(f"Reactivation Autopilot is safety-locked: {exc}")
    st.stop()

settings = ReactivationDispatchSettings.from_mapping(st.secrets)
dwelyx_url = dwelyx_base_url(st.secrets)
buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
properties_by_id = {str(item.property_id): item for item in properties}
marketable_properties = [item for item in properties if item.status in MARKETABLE_PROPERTY_STATUSES]

if settings.configured:
    st.success("Buyer outreach webhook is connected. Approved due jobs can be dispatched.")
else:
    st.warning(
        "The queue, matching, engagement tracking, and approvals work now, but dispatch is not connected. Add "
        "BUYER_OUTREACH_WEBHOOK_URL or AUTOMATION_WEBHOOK_URL in Streamlit Secrets later."
    )

queue_tab, build_tab, signal_tab, history_tab = st.tabs(
    ["Due Queue", "Build Sequences", "Record Engagement", "Automation History"]
)

with build_tab:
    if not buyers:
        st.info("Add buyer profiles before building reactivation sequences.")
    elif not marketable_properties:
        st.info("No Ready to Launch or Marketing Live property is available for reactivation sequences.")
    else:
        property_options = {
            item.display_address or str(item.property_id): item for item in marketable_properties
        }
        selected_properties = st.multiselect(
            "Properties to include",
            options=list(property_options),
            default=list(property_options),
            key="autopilot_properties",
        )
        minimum_score = st.slider(
            "Minimum buyer-intent score",
            min_value=0,
            max_value=100,
            value=50,
            step=5,
            key="autopilot_minimum_score",
        )
        matches = build_match_queue(
            buyers,
            [property_options[name] for name in selected_properties],
            intent_ledger,
            dwelyx_url,
            minimum_score=minimum_score,
        )
        st.write(f"**Consent-ready buyer/property matches:** {len(matches)}")
        st.info(
            "Sequence logic: Hot buyers receive SMS first and email 24 hours later when both are "
            "consented. Warm buyers receive email first and SMS 48 hours later. Nurture buyers receive one consented message."
        )
        if st.button(
            "Build AI Reactivation Sequences",
            type="primary",
            use_container_width=True,
            disabled=not matches,
        ):
            updated, created, skipped = build_reactivation_jobs(
                autopilot_ledger,
                matches,
            )
            autopilot_store.save(updated)
            st.success(f"Created {created} new outreach job(s). Skipped {skipped} duplicate or capacity-limited step(s).")
            st.rerun()

with queue_tab:
    current_due = due_jobs(autopilot_ledger)
    approved_due = [job for job in current_due if job.status == ReactivationJobStatus.APPROVED]
    queued_due = [job for job in current_due if job.status in {ReactivationJobStatus.QUEUED, ReactivationJobStatus.FAILED}]
    future_count = sum(
        job.status in {ReactivationJobStatus.QUEUED, ReactivationJobStatus.APPROVED, ReactivationJobStatus.FAILED}
        for job in autopilot_ledger.jobs
    ) - len(current_due)

    metrics = st.columns(5)
    metrics[0].metric("Due Now", len(current_due))
    metrics[1].metric("Awaiting Approval", len(queued_due))
    metrics[2].metric("Approved to Send", len(approved_due))
    metrics[3].metric("Future Steps", max(future_count, 0))
    metrics[4].metric(
        "Dispatched",
        sum(job.status == ReactivationJobStatus.DISPATCHED for job in autopilot_ledger.jobs),
    )

    if current_due:
        st.dataframe(
            pd.DataFrame(job_rows(autopilot_ledger)),
            use_container_width=True,
            hide_index=True,
        )
        options = {job_label(job): job for job in current_due}
        selected_label = st.selectbox("Work one due job", list(options))
        selected = options[selected_label]

        details = st.columns(5)
        details[0].metric("Intent", selected.tier.value)
        details[1].metric("Score", selected.score)
        details[2].metric("Channel", selected.channel.value)
        details[3].metric("Step", selected.sequence_step)
        details[4].metric("Status", selected.status.value)
        st.write(f"**Buyer:** {selected.buyer_name}")
        st.write(f"**Property:** {selected.property_address}")
        st.write(f"**Sequence:** {selected.sequence_label}")
        st.text_input("Recipient", value=selected.recipient, key=f"recipient_{selected.job_id}", disabled=True)
        if selected.subject:
            st.text_input("Subject", value=selected.subject, key=f"subject_{selected.job_id}", disabled=True)
        st.text_area("Approved message", value=selected.message, height=300, key=f"message_{selected.job_id}", disabled=True)
        st.text_input("Tracked Dwelyx link", value=selected.tracked_link, key=f"link_{selected.job_id}", disabled=True)

        operator = st.text_input("Approved by", value="Sabrina", key=f"operator_{selected.job_id}")
        notes = st.text_area("Approval, delivery, or cancellation notes", height=80, key=f"notes_{selected.job_id}")
        approve_column, cancel_column = st.columns(2)
        if approve_column.button(
            "Approve Selected Job",
            type="primary",
            use_container_width=True,
            disabled=selected.status not in {ReactivationJobStatus.QUEUED, ReactivationJobStatus.FAILED},
        ):
            updated = approve_job(
                autopilot_ledger,
                job_id=selected.job_id,
                approved_by=operator,
                notes=notes,
            )
            autopilot_store.save(updated)
            st.success("Job approved. It is ready for webhook dispatch.")
            st.rerun()
        if cancel_column.button(
            "Cancel Selected Job",
            use_container_width=True,
            disabled=selected.status == ReactivationJobStatus.DISPATCHED,
        ):
            updated = cancel_job(
                autopilot_ledger,
                job_id=selected.job_id,
                notes=notes or "Cancelled by operator.",
            )
            autopilot_store.save(updated)
            st.success("Job cancelled.")
            st.rerun()

        dispatch_confirmed = st.checkbox(
            "I confirm this approved message may be sent through the connected consent-based system.",
            key=f"dispatch_confirm_{selected.job_id}",
        )
        if st.button(
            "Dispatch Selected Approved Job",
            type="primary",
            use_container_width=True,
            disabled=(
                selected.status != ReactivationJobStatus.APPROVED
                or not dispatch_confirmed
                or not settings.configured
            ),
        ):
            updated_autopilot, updated_intent, result, detail = dispatch_one(
                selected,
                autopilot_ledger,
                intent_ledger,
                settings,
                buyers_by_id,
                properties_by_id,
                dwelyx_url,
            )
            autopilot_store.save(updated_autopilot)
            intent_store.save(updated_intent)
            if result == "dispatched":
                st.success("Outreach dispatched and the buyer/property/channel cooldown is now active.")
            elif result == "stopped":
                st.warning(detail)
            elif result == "cancelled":
                st.warning(detail)
            else:
                st.error(detail)
            st.rerun()

        st.write("### Bulk manager actions")
        bulk_operator = st.text_input("Bulk approval by", value="Sabrina", key="bulk_approval_operator")
        bulk_approve_confirm = st.checkbox(
            "I reviewed the due queue and approve all currently queued or failed jobs.",
            key="bulk_approve_confirm",
        )
        if st.button(
            "Approve All Due Jobs",
            use_container_width=True,
            disabled=not queued_due or not bulk_approve_confirm,
        ):
            updated = autopilot_ledger
            approved_count = 0
            for job in queued_due:
                stop_reason = engagement_stop_reason(intent_ledger, job)
                if stop_reason:
                    updated = stop_job_for_engagement(updated, job_id=job.job_id, reason=stop_reason)
                    continue
                property_record = properties_by_id.get(job.property_id)
                if not property_record or property_record.status not in MARKETABLE_PROPERTY_STATUSES:
                    updated = cancel_job(
                        updated,
                        job_id=job.job_id,
                        notes="Property is no longer Ready to Launch or Marketing Live.",
                    )
                    continue
                updated = approve_job(
                    updated,
                    job_id=job.job_id,
                    approved_by=bulk_operator,
                    notes="Bulk manager approval.",
                )
                approved_count += 1
            autopilot_store.save(updated)
            st.success(f"Approved {approved_count} due job(s).")
            st.rerun()

        bulk_dispatch_confirm = st.checkbox(
            "I confirm all approved due jobs may be sent now through the connected consent-based system.",
            key="bulk_dispatch_confirm",
        )
        if st.button(
            "Dispatch All Approved Due Jobs",
            type="primary",
            use_container_width=True,
            disabled=not approved_due or not bulk_dispatch_confirm or not settings.configured,
        ):
            updated_autopilot = autopilot_ledger
            updated_intent = intent_ledger
            dispatched = 0
            stopped = 0
            failed = 0
            cancelled = 0
            for approved_job in approved_due:
                updated_autopilot, updated_intent, result, _detail = dispatch_one(
                    approved_job,
                    updated_autopilot,
                    updated_intent,
                    settings,
                    buyers_by_id,
                    properties_by_id,
                    dwelyx_url,
                )
                if result == "dispatched":
                    dispatched += 1
                elif result == "stopped":
                    stopped += 1
                elif result == "cancelled":
                    cancelled += 1
                else:
                    failed += 1
            autopilot_store.save(updated_autopilot)
            intent_store.save(updated_intent)
            st.success(
                f"Dispatched {dispatched}. Stopped by engagement {stopped}. "
                f"Cancelled by current compliance check {cancelled}. Failed {failed}."
            )
            st.rerun()
    else:
        st.info("No reactivation jobs are due right now. Build sequences or wait for the next scheduled step.")

with signal_tab:
    st.subheader("Record Buyer Engagement")
    st.caption("Save engagement signals here so intent scores update and later sequence steps can stop automatically.")
    if not buyers:
        st.info("Add buyer profiles before recording engagement.")
    else:
        buyer_options = {
            f"{buyer.first_name} {buyer.last_name}".strip() or str(buyer.buyer_id): buyer
            for buyer in buyers
        }
        property_options = {
            item.display_address or str(item.property_id): item for item in properties
        }
        with st.form("buyer_signal_form", clear_on_submit=True):
            buyer_name = st.selectbox("Buyer", list(buyer_options))
            property_name = st.selectbox(
                "Property — optional",
                ["No specific property", *property_options],
            )
            signal_type = st.selectbox(
                "Engagement signal",
                [
                    "dwelyx_click",
                    "property_view",
                    "email_open",
                    "sms_click",
                    "reply",
                    "call_connected",
                    "application_started",
                    "showing_requested",
                ],
            )
            signal_notes = st.text_area("Notes", height=80)
            save_signal = st.form_submit_button("Save Engagement Signal", type="primary")
        if save_signal:
            buyer = buyer_options[buyer_name]
            property_id = (
                property_options[property_name].property_id
                if property_name != "No specific property"
                else ""
            )
            updated = record_signal(
                intent_ledger,
                buyer_id=buyer.buyer_id,
                signal_type=signal_type,
                property_id=property_id,
                notes=signal_notes,
            )
            intent_store.save(updated)
            st.success("Engagement signal saved. Buyer-intent scores and stop rules will use it immediately.")
            st.rerun()

with history_tab:
    rows = job_rows(autopilot_ledger)
    if rows:
        table = pd.DataFrame(rows)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Reactivation Autopilot History (CSV)",
            data=table.to_csv(index=False).encode(),
            file_name="buyer_reactivation_autopilot_history.csv",
            mime="text/csv",
        )
    else:
        st.info("No buyer-reactivation automation jobs have been created yet.")

    if intent_ledger.outreach:
        st.write("### Buyer outreach history")
        outreach_rows = [
            {
                "Sent": row.sent_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Buyer ID": row.buyer_id,
                "Property ID": row.property_id,
                "Channel": row.channel.value,
                "Prepared/Sent By": row.sent_by or "—",
                "Outcome": row.outcome,
                "Notes": row.notes or "—",
            }
            for row in sorted(intent_ledger.outreach, key=lambda item: item.sent_at, reverse=True)
        ]
        st.dataframe(pd.DataFrame(outreach_rows), use_container_width=True, hide_index=True)

st.info(
    "Every dispatch is rechecked against current property marketability, buyer consent, Do Not Contact status, "
    "contact information, and outreach cooldown. Replies, connected calls, applications, and showing requests stop later sequence steps."
)
