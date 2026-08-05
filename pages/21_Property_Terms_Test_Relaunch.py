from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionStore,
)
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage
from cfh_disposition.terms_testing import (
    PRIMARY_METRICS,
    RelaunchTaskStatus,
    TermsExperimentStatus,
    TermsField,
    TermsRecommendation,
    TermsTestingError,
    TermsTestingStore,
    TestPhase,
    apply_challenger,
    approve_decision,
    approve_experiment,
    build_terms_experiment,
    cancel_experiment,
    create_experiment,
    experiment_history_rows,
    find_experiment,
    mark_review_ready,
    phase_metric_rows,
    recommendation_for_experiment,
    relaunch_task_rows,
    rollback_to_control,
    snapshot_rows,
    update_relaunch_task,
    upsert_outcome,
)

st.set_page_config(
    page_title="Property Terms Test & Relaunch Center",
    page_icon="⚖️",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Property Terms Test & Relaunch Center")
    st.caption("Private internal access")
    with st.form("terms_testing_login"):
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


def experiment_label(experiment) -> str:
    return (
        f"{experiment.status.value} — {experiment.tested_field.value} — "
        f"{experiment.property_address}"
    )


def property_label(item: OwnerFinanceProperty) -> str:
    return f"{item.display_address} — {item.status.value}"


def field_value(item: OwnerFinanceProperty, field: TermsField):
    mapping = {
        TermsField.TOTAL_PRICE: item.total_price,
        TermsField.DOWN_PAYMENT: item.down_payment,
        TermsField.MONTHLY_PAYMENT: item.monthly_payment,
        TermsField.INTEREST_RATE: item.interest_rate,
        TermsField.TERM_MONTHS: item.term_months,
    }
    return mapping[field]


def formatted_field_value(item: OwnerFinanceProperty, field: TermsField) -> str:
    value = field_value(item, field)
    if value is None:
        return "Not saved"
    if field in {
        TermsField.TOTAL_PRICE,
        TermsField.DOWN_PAYMENT,
        TermsField.MONTHLY_PAYMENT,
    }:
        return f"${Decimal(str(value)):,.0f}"
    if field == TermsField.INTEREST_RATE:
        return f"{value}%"
    return f"{value} months"


def save_ledger(store: TermsTestingStore, ledger) -> None:
    store.save(ledger)
    st.session_state.terms_testing_refresh = True


require_password()
st.title("Property Terms Test & Relaunch Center")
st.caption(
    "Tests one management-approved offer variable at a time, measures the result, "
    "and protects the original terms for rollback."
)
st.warning(
    "This center never changes a price, down payment, monthly payment, interest rate, "
    "term, ad, or property record automatically. Every apply, keep, and revert action "
    "requires an authenticated team member and an explicit confirmation."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    terms_store = TermsTestingStore(st.secrets)
    ledger = terms_store.load()
except (StorageError, TermsTestingError) as exc:
    st.error(f"Terms Testing Center is safety-locked: {exc}")
    st.stop()

click_events = []
try:
    click_events = ClickAnalyticsStore(st.secrets).list_recent(days=365)
except AnalyticsError as exc:
    st.warning(f"Tracked-click history is unavailable: {exc}")

attribution_events = []
try:
    attribution_events = DwelyxAttributionStore(st.secrets).list_events(limit=10000)
except DwelyxAttributionError as exc:
    st.warning(f"Dwelyx result events are unavailable: {exc}")

if not properties:
    st.info("Add and save a property before creating a terms test.")
    st.stop()

properties_by_id = {str(item.property_id): item for item in properties}
property_options = {property_label(item): item for item in properties}
dwelyx_url = dwelyx_base_url(st.secrets)

create_tab, approval_tab, results_tab, relaunch_tab, history_tab = st.tabs(
    [
        "Create Test",
        "Approval & Apply",
        "Results & Decision",
        "15-Channel Relaunch",
        "Audit History",
    ]
)

with create_tab:
    st.write("### Create a one-variable terms test")
    selected_property_label = st.selectbox(
        "Property",
        list(property_options),
        key="terms_create_property",
    )
    selected_property = property_options[selected_property_label]
    tested_field = st.selectbox(
        "Offer variable to test",
        list(TermsField),
        format_func=lambda value: value.value,
    )
    current_value = field_value(selected_property, tested_field)
    st.metric("Current Saved Value", formatted_field_value(selected_property, tested_field))

    if tested_field == TermsField.TERM_MONTHS:
        challenger_value = st.number_input(
            "Challenger term in months",
            min_value=1,
            max_value=600,
            value=int(current_value or 360),
            step=1,
        )
    elif tested_field == TermsField.INTEREST_RATE:
        challenger_value = st.number_input(
            "Challenger interest rate",
            min_value=0.0,
            max_value=100.0,
            value=float(current_value or 0),
            step=0.25,
        )
    else:
        challenger_value = st.number_input(
            f"Challenger {tested_field.value.lower()}",
            min_value=0.0,
            value=float(current_value or 0),
            step=100.0,
        )

    today = date.today()
    default_end = today - timedelta(days=1)
    default_start = default_end - timedelta(days=13)
    baseline_columns = st.columns(2)
    baseline_start = baseline_columns[0].date_input(
        "Baseline start",
        value=default_start,
    )
    baseline_end = baseline_columns[1].date_input(
        "Baseline end",
        value=default_end,
    )

    settings = st.columns(4)
    primary_metric = settings[0].selectbox("Primary result", PRIMARY_METRICS, index=1)
    minimum_test_days = settings[1].number_input(
        "Minimum test days",
        min_value=1,
        max_value=90,
        value=7,
        step=1,
    )
    minimum_clicks = settings[2].number_input(
        "Minimum usable clicks",
        min_value=1,
        max_value=100000,
        value=10,
        step=1,
    )
    minimum_registrations = settings[3].number_input(
        "Minimum registrations",
        min_value=1,
        max_value=100000,
        value=3,
        step=1,
    )
    minimum_lift_percent = st.number_input(
        "Required improvement before recommending Keep",
        min_value=0,
        max_value=500,
        value=20,
        step=5,
        help="Twenty means the challenger must improve the selected result rate by at least 20 percent.",
    )
    name = st.text_input(
        "Test name — optional",
        placeholder=f"{tested_field.value} test — {selected_property.display_address}",
    )
    objective = st.text_area(
        "Business objective",
        value="Fill the property faster without weakening the deal unnecessarily.",
        height=90,
    )
    create_confirmed = st.checkbox(
        "I understand this creates a draft only. It does not change the property.",
        key="terms_create_confirmed",
    )
    if st.button(
        "Create Draft Terms Test",
        type="primary",
        disabled=not create_confirmed,
    ):
        try:
            experiment = build_terms_experiment(
                selected_property,
                dwelyx_url,
                tested_field=tested_field,
                challenger_value=challenger_value,
                baseline_start=baseline_start,
                baseline_end=baseline_end,
                primary_metric=primary_metric,
                minimum_test_days=int(minimum_test_days),
                minimum_clicks=int(minimum_clicks),
                minimum_registrations=int(minimum_registrations),
                minimum_lift=Decimal(minimum_lift_percent) / Decimal("100"),
                objective=objective,
                name=name,
            )
            ledger = create_experiment(ledger, experiment)
            save_ledger(terms_store, ledger)
            st.success("Draft terms test created. Management approval is required before application.")
            st.rerun()
        except TermsTestingError as exc:
            st.error(str(exc))

with approval_tab:
    st.write("### Approve and explicitly apply a challenger")
    approval_experiments = [
        item
        for item in ledger.experiments
        if item.status
        in {
            TermsExperimentStatus.DRAFT,
            TermsExperimentStatus.APPROVED,
        }
    ]
    if not approval_experiments:
        st.info("No draft or approved unapplied terms tests are waiting.")
    else:
        experiment_options = {
            experiment_label(item): item for item in approval_experiments
        }
        selected_label = st.selectbox(
            "Terms test",
            list(experiment_options),
            key="terms_approval_experiment",
        )
        selected_experiment = experiment_options[selected_label]
        st.dataframe(
            pd.DataFrame(snapshot_rows(selected_experiment)),
            use_container_width=True,
            hide_index=True,
        )
        st.code(selected_experiment.tracked_link)
        if selected_experiment.tested_field == TermsField.TOTAL_PRICE:
            st.info(
                "The total price remains excluded from public ad copy under the current marketing rules. "
                "This challenger affects Dwelyx and other approved places where total price is displayed."
            )

        if selected_experiment.status == TermsExperimentStatus.DRAFT:
            with st.form("approve_terms_experiment"):
                approved_by = st.text_input("Approved by", value="Sabrina")
                approval_reason = st.text_area(
                    "Business reason for approval",
                    placeholder="Example: registrations are strong but applications are weak, so management approved a lower down-payment test.",
                    height=100,
                )
                approve = st.form_submit_button("Approve Challenger", type="primary")
            if approve:
                try:
                    ledger = approve_experiment(
                        ledger,
                        experiment_id=selected_experiment.experiment_id,
                        approved_by=approved_by,
                        approval_reason=approval_reason,
                    )
                    save_ledger(terms_store, ledger)
                    st.success("Challenger approved. It still has not changed the property.")
                    st.rerun()
                except TermsTestingError as exc:
                    st.error(str(exc))
        else:
            property_record = properties_by_id.get(selected_experiment.property_id)
            if property_record is None:
                st.error("The property record connected to this test could not be found.")
            else:
                st.error(
                    "Applying the challenger changes the saved property terms immediately. "
                    "The original terms remain stored in this experiment for rollback."
                )
                with st.form("apply_terms_experiment"):
                    applied_by = st.text_input("Applied by", value="Sabrina")
                    apply_phrase = st.text_input('Type "APPLY" to confirm')
                    apply_confirmed = st.checkbox(
                        "I reviewed the original and challenger values and approve updating the saved property."
                    )
                    apply_now = st.form_submit_button(
                        "Apply Approved Challenger",
                        type="primary",
                        disabled=not apply_confirmed,
                    )
                if apply_now:
                    if apply_phrase.strip().upper() != "APPLY":
                        st.error('Type "APPLY" exactly before changing the property record.')
                    else:
                        try:
                            ledger, updated_property = apply_challenger(
                                ledger,
                                property_record,
                                experiment_id=selected_experiment.experiment_id,
                                applied_by=applied_by,
                            )
                            storage.save_property(updated_property)
                            save_ledger(terms_store, ledger)
                            st.success(
                                "The challenger is active. The 15-channel relaunch checklist is ready."
                            )
                            st.rerun()
                        except (TermsTestingError, StorageError) as exc:
                            st.error(str(exc))

        if st.button(
            "Cancel Unapplied Test",
            key=f"cancel_terms_{selected_experiment.experiment_id}",
        ):
            try:
                ledger = cancel_experiment(
                    ledger,
                    experiment_id=selected_experiment.experiment_id,
                )
                save_ledger(terms_store, ledger)
                st.success("Unapplied terms test cancelled.")
                st.rerun()
            except TermsTestingError as exc:
                st.error(str(exc))

with results_tab:
    st.write("### Compare the original terms against the challenger")
    result_experiments = [
        item
        for item in ledger.experiments
        if item.status
        in {
            TermsExperimentStatus.ACTIVE,
            TermsExperimentStatus.REVIEW_READY,
            TermsExperimentStatus.KEEP_APPROVED,
            TermsExperimentStatus.REVERT_APPROVED,
            TermsExperimentStatus.COMPLETED,
        }
    ]
    if not result_experiments:
        st.info("Apply an approved challenger before measuring results.")
    else:
        result_options = {experiment_label(item): item for item in result_experiments}
        result_label = st.selectbox(
            "Active or completed test",
            list(result_options),
            key="terms_results_experiment",
        )
        selected_experiment = result_options[result_label]
        result = recommendation_for_experiment(
            ledger,
            selected_experiment,
            click_events=click_events,
            attribution_events=attribution_events,
        )
        metrics = st.columns(5)
        metrics[0].metric("Recommendation", result.recommendation.value)
        metrics[1].metric("Confidence", result.confidence)
        metrics[2].metric("Control Outcomes", result.control.primary_total)
        metrics[3].metric("Challenger Outcomes", result.challenger.primary_total)
        metrics[4].metric("Measured Lift", f"{result.lift_percent:.1%}")
        st.info(result.reason)
        st.dataframe(
            pd.DataFrame(phase_metric_rows(result)),
            use_container_width=True,
            hide_index=True,
        )
        st.write("**Unique challenger Dwelyx link**")
        st.code(selected_experiment.tracked_link)

        with st.expander("Add or update manual result totals", expanded=False):
            with st.form("terms_outcome_form"):
                phase = st.selectbox(
                    "Phase",
                    list(TestPhase),
                    format_func=lambda value: value.value,
                )
                period_columns = st.columns(2)
                period_start = period_columns[0].date_input(
                    "Period start",
                    value=date.today() - timedelta(days=6),
                    key="terms_outcome_start",
                )
                period_end = period_columns[1].date_input(
                    "Period end",
                    value=date.today(),
                    key="terms_outcome_end",
                )
                first_row = st.columns(5)
                impressions = first_row[0].number_input("Impressions", min_value=0, value=0)
                reported_clicks = first_row[1].number_input("Reported clicks", min_value=0, value=0)
                inquiries = first_row[2].number_input("Inquiries", min_value=0, value=0)
                registrations = first_row[3].number_input("Registrations", min_value=0, value=0)
                applications = first_row[4].number_input("Applications", min_value=0, value=0)
                second_row = st.columns(4)
                showings = second_row[0].number_input("Showings", min_value=0, value=0)
                contracts = second_row[1].number_input("Contracts", min_value=0, value=0)
                filled = second_row[2].number_input("Filled", min_value=0, value=0)
                spend = second_row[3].number_input("Spend", min_value=0.0, value=0.0)
                outcome_notes = st.text_area("Notes", height=80)
                save_outcome = st.form_submit_button("Save Result Period", type="primary")
            if save_outcome:
                try:
                    ledger = upsert_outcome(
                        ledger,
                        experiment_id=selected_experiment.experiment_id,
                        phase=phase,
                        period_start=period_start,
                        period_end=period_end,
                        impressions=int(impressions),
                        reported_clicks=int(reported_clicks),
                        inquiries=int(inquiries),
                        registrations=int(registrations),
                        applications=int(applications),
                        showings=int(showings),
                        contracts=int(contracts),
                        filled=int(filled),
                        spend=spend,
                        notes=outcome_notes,
                    )
                    save_ledger(terms_store, ledger)
                    st.success("Result period saved.")
                    st.rerun()
                except (TermsTestingError, ValueError) as exc:
                    st.error(str(exc))

        if selected_experiment.status == TermsExperimentStatus.ACTIVE:
            if st.button(
                "Mark Test Ready for Management Review",
                key=f"review_terms_{selected_experiment.experiment_id}",
            ):
                try:
                    ledger = mark_review_ready(
                        ledger,
                        experiment_id=selected_experiment.experiment_id,
                    )
                    save_ledger(terms_store, ledger)
                    st.success("Test marked ready for management review.")
                    st.rerun()
                except TermsTestingError as exc:
                    st.error(str(exc))

        if selected_experiment.status in {
            TermsExperimentStatus.ACTIVE,
            TermsExperimentStatus.REVIEW_READY,
        }:
            st.write("### Management decision")
            with st.form("terms_decision_form"):
                decision = st.selectbox(
                    "Decision",
                    [TermsRecommendation.KEEP, TermsRecommendation.REVERT],
                    format_func=lambda value: value.value,
                )
                decided_by = st.text_input("Decided by", value="Sabrina")
                decision_reason = st.text_area(
                    "Decision reason",
                    value=result.reason,
                    height=100,
                )
                decision_confirmed = st.checkbox(
                    "I reviewed the measured results and approve this management decision."
                )
                save_decision = st.form_submit_button(
                    "Approve Final Decision",
                    type="primary",
                    disabled=not decision_confirmed,
                )
            if save_decision:
                try:
                    ledger = approve_decision(
                        ledger,
                        experiment_id=selected_experiment.experiment_id,
                        decision=decision,
                        decided_by=decided_by,
                        decision_reason=decision_reason,
                    )
                    save_ledger(terms_store, ledger)
                    message = (
                        "Challenger retained and test completed."
                        if decision == TermsRecommendation.KEEP
                        else "Revert approved. The original terms have not been restored yet."
                    )
                    st.success(message)
                    st.rerun()
                except TermsTestingError as exc:
                    st.error(str(exc))

        if selected_experiment.status == TermsExperimentStatus.REVERT_APPROVED:
            property_record = properties_by_id.get(selected_experiment.property_id)
            st.error(
                "Management approved a revert. Restoring the original terms changes the saved property "
                "and creates a new 15-channel cleanup checklist."
            )
            if property_record is None:
                st.error("The connected property record could not be found.")
            else:
                with st.form("terms_rollback_form"):
                    rollback_by = st.text_input("Restored by", value="Sabrina")
                    restore_phrase = st.text_input('Type "RESTORE" to confirm')
                    restore_confirmed = st.checkbox(
                        "I approve restoring the original terms shown in this experiment."
                    )
                    restore_now = st.form_submit_button(
                        "Restore Original Terms",
                        type="primary",
                        disabled=not restore_confirmed,
                    )
                if restore_now:
                    if restore_phrase.strip().upper() != "RESTORE":
                        st.error('Type "RESTORE" exactly before changing the property record.')
                    else:
                        try:
                            ledger, restored_property = rollback_to_control(
                                ledger,
                                property_record,
                                experiment_id=selected_experiment.experiment_id,
                                rollback_by=rollback_by,
                            )
                            storage.save_property(restored_property)
                            save_ledger(terms_store, ledger)
                            st.success(
                                "Original terms restored. Complete the new 15-channel cleanup checklist."
                            )
                            st.rerun()
                        except (TermsTestingError, StorageError) as exc:
                            st.error(str(exc))

with relaunch_tab:
    st.write("### Confirm the approved terms everywhere buyers can see them")
    relaunch_experiments = [item for item in ledger.experiments if item.applied_at]
    if not relaunch_experiments:
        st.info("Apply a challenger before a relaunch checklist is created.")
    else:
        relaunch_options = {
            experiment_label(item): item for item in relaunch_experiments
        }
        relaunch_label = st.selectbox(
            "Terms test",
            list(relaunch_options),
            key="terms_relaunch_experiment",
        )
        selected_experiment = relaunch_options[relaunch_label]
        task_frame = pd.DataFrame(relaunch_task_rows(selected_experiment))
        st.dataframe(
            task_frame,
            use_container_width=True,
            hide_index=True,
            height=570,
        )
        st.download_button(
            "Download 15-Channel Relaunch Checklist",
            task_frame.to_csv(index=False).encode("utf-8"),
            "property-terms-relaunch-checklist.csv",
            "text/csv",
        )
        task_options = {
            f"{task.channel_name} — {task.status.value}": task
            for task in selected_experiment.relaunch_tasks
        }
        task_label = st.selectbox(
            "Update one channel",
            list(task_options),
            key="terms_relaunch_task",
        )
        selected_task = task_options[task_label]
        with st.form("terms_relaunch_task_form"):
            statuses = list(RelaunchTaskStatus)
            task_status = st.selectbox(
                "Task status",
                statuses,
                index=statuses.index(selected_task.status),
                format_func=lambda value: value.value,
            )
            task_updated_by = st.text_input("Updated by", value="Sabrina")
            task_notes = st.text_area(
                "Listing URL, ad ID, confirmation, or failure notes",
                value=selected_task.notes,
                height=100,
            )
            save_task = st.form_submit_button("Save Channel Confirmation", type="primary")
        if save_task:
            try:
                ledger = update_relaunch_task(
                    ledger,
                    experiment_id=selected_experiment.experiment_id,
                    channel_key=selected_task.channel_key,
                    status=task_status,
                    updated_by=task_updated_by,
                    notes=task_notes,
                )
                save_ledger(terms_store, ledger)
                st.success(f"{selected_task.channel_name} saved as {task_status.value}.")
                st.rerun()
            except TermsTestingError as exc:
                st.error(str(exc))

with history_tab:
    st.write("### Permanent property-terms audit history")
    history = experiment_history_rows(ledger)
    if not history:
        st.info("No property terms test has been created yet.")
    else:
        history_frame = pd.DataFrame(history)
        st.dataframe(history_frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Terms Test History",
            history_frame.to_csv(index=False).encode("utf-8"),
            "property-terms-test-history.csv",
            "text/csv",
        )
