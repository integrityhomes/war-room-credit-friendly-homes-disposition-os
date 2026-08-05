from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.creative_testing import (
    PRIMARY_METRICS,
    SUPPORTED_CREATIVE_CHANNELS,
    CreativeTestingError,
    CreativeTestingStore,
    ExperimentStatus,
    allocation_rows,
    approve_winner,
    assigned_variant,
    build_creative_experiment,
    create_experiment,
    find_experiment,
    mark_winner_ready,
    metric_rows,
    update_experiment_status,
    upsert_outcome,
    winner_recommendation,
)
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.models import BuyerProfile
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Creative Winner Rotation",
    page_icon="🧪",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("AI Creative Winner Rotation")
    st.caption("Private internal access")
    with st.form("creative_testing_login"):
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
        f"{experiment.status.value} — {experiment.channel_name} — "
        f"{experiment.property_address}"
    )


def consent_ready_buyers(buyers: list[BuyerProfile], channel_key: str) -> list[BuyerProfile]:
    eligible: list[BuyerProfile] = []
    for buyer in buyers:
        if buyer.do_not_contact:
            continue
        if channel_key == "email" and not (buyer.email_consent and buyer.email):
            continue
        if channel_key == "sms" and not (buyer.sms_consent and buyer.phone):
            continue
        eligible.append(buyer)
    return eligible


def experiment_history_rows(ledger) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for experiment in sorted(
        ledger.experiments,
        key=lambda item: item.created_at,
        reverse=True,
    ):
        rows.append(
            {
                "Created": experiment.created_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Status": experiment.status.value,
                "Test": experiment.name,
                "Property": experiment.property_address,
                "Channel": experiment.channel_name,
                "Metric": experiment.primary_metric,
                "Winner": next(
                    (
                        variant.key
                        for variant in experiment.variants
                        if variant.variant_id == experiment.winner_variant_id
                    ),
                    "—",
                ),
                "Approved By": experiment.winner_approved_by or "—",
            }
        )
    return rows


require_password()
st.title("AI Creative Testing & Winner Rotation Engine")
st.caption(
    "Tests one opening angle at a time, measures tracked Dwelyx activity and buyer outcomes, "
    "and recommends a winner without changing property facts or publishing automatically."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    buyers = storage.list_buyers()
    testing_store = CreativeTestingStore(st.secrets)
    ledger = testing_store.load()
    try:
        click_events = ClickAnalyticsStore(st.secrets).list_recent(90)
        click_warning = ""
    except AnalyticsError as exc:
        click_events = []
        click_warning = str(exc)
except (StorageError, CreativeTestingError) as exc:
    st.error(f"Creative Testing Engine is safety-locked: {exc}")
    st.stop()

if click_warning:
    st.warning(
        "Tracked clicks could not be loaded, so winner scoring will use manually reported clicks "
        f"until analytics is restored: {click_warning}"
    )

create_tab, run_tab, winner_tab, rotation_tab, history_tab = st.tabs(
    [
        "Create Test",
        "Run & Measure",
        "Winner Review",
        "Rotation Preview",
        "History",
    ]
)

with create_tab:
    st.write("### Create a controlled four-variant test")
    if not properties:
        st.info("Add a property before creating a creative test.")
    else:
        property_options = {
            item.display_address or str(item.property_id): item for item in properties
        }
        selected_property_name = st.selectbox(
            "Property",
            list(property_options),
            key="creative_create_property",
        )
        selected_property = property_options[selected_property_name]
        channel_key = st.selectbox(
            "Marketing channel",
            SUPPORTED_CREATIVE_CHANNELS,
            format_func=lambda key: key.replace("_", " ").title(),
            key="creative_create_channel",
        )
        primary_metric = st.selectbox(
            "Primary winner metric",
            PRIMARY_METRICS,
            key="creative_create_metric",
        )
        left, middle, right = st.columns(3)
        minimum_impressions = left.number_input(
            "Minimum impressions per variant",
            min_value=10,
            max_value=100000,
            value=100,
            step=10,
        )
        minimum_clicks = middle.number_input(
            "Minimum clicks per variant",
            min_value=1,
            max_value=10000,
            value=10,
        )
        lift_percent = right.number_input(
            "Required winner lift (%)",
            min_value=0,
            max_value=500,
            value=20,
            step=5,
        )
        test_name = st.text_input(
            "Test name — optional",
            value="",
            placeholder="Example: Packard email payment-angle test",
        )
        st.info(
            "This test changes only the opening angle: address first, monthly payment first, "
            "down payment first, or condition transparency first. All other facts remain locked."
        )
        if st.button(
            "Create Fact-Safe Creative Test",
            type="primary",
            use_container_width=True,
        ):
            try:
                experiment = build_creative_experiment(
                    selected_property,
                    dwelyx_base_url(st.secrets),
                    channel_key=channel_key,
                    primary_metric=primary_metric,
                    minimum_impressions_per_variant=int(minimum_impressions),
                    minimum_clicks_per_variant=int(minimum_clicks),
                    winner_lift_threshold=Decimal(str(lift_percent)) / Decimal("100"),
                    name=test_name,
                )
                updated = create_experiment(ledger, experiment)
                testing_store.save(updated)
                st.success(
                    "Creative test created with four equal 25% variants. Open Run & Measure to review and start it."
                )
                st.rerun()
            except CreativeTestingError as exc:
                st.error(str(exc))

with run_tab:
    if not ledger.experiments:
        st.info("Create the first creative test before recording results.")
    else:
        experiment_options = {
            experiment_label(experiment): experiment for experiment in ledger.experiments
        }
        selected_label = st.selectbox(
            "Creative test",
            list(experiment_options),
            key="creative_run_experiment",
        )
        experiment = experiment_options[selected_label]
        st.write(f"### {experiment.name}")
        status_columns = st.columns(4)
        status_columns[0].metric("Status", experiment.status.value)
        status_columns[1].metric("Channel", experiment.channel_name)
        status_columns[2].metric("Primary Metric", experiment.primary_metric)
        status_columns[3].metric("Variants", len(experiment.variants))

        if experiment.status == ExperimentStatus.DRAFT:
            if st.button("Start Test", type="primary"):
                updated = update_experiment_status(
                    ledger,
                    experiment_id=experiment.experiment_id,
                    status=ExperimentStatus.RUNNING,
                )
                testing_store.save(updated)
                st.success("Creative test is now Running.")
                st.rerun()
        elif experiment.status in {ExperimentStatus.RUNNING, ExperimentStatus.WINNER_READY}:
            if st.button("Pause Test"):
                updated = update_experiment_status(
                    ledger,
                    experiment_id=experiment.experiment_id,
                    status=ExperimentStatus.PAUSED,
                )
                testing_store.save(updated)
                st.success("Creative test paused.")
                st.rerun()
        elif experiment.status == ExperimentStatus.PAUSED:
            if st.button("Resume Test", type="primary"):
                updated = update_experiment_status(
                    ledger,
                    experiment_id=experiment.experiment_id,
                    status=ExperimentStatus.RUNNING,
                )
                testing_store.save(updated)
                st.success("Creative test resumed.")
                st.rerun()

        st.write("### Current traffic allocation")
        st.dataframe(
            pd.DataFrame(allocation_rows(experiment)),
            use_container_width=True,
            hide_index=True,
        )

        variant_options = {
            f"Variant {variant.key} — {variant.angle}": variant
            for variant in experiment.variants
        }
        selected_variant_label = st.selectbox(
            "Review or record one variant",
            list(variant_options),
            key="creative_run_variant",
        )
        variant = variant_options[selected_variant_label]
        st.code(variant.copy, language=None)
        st.text_input(
            "Tracked Dwelyx link",
            value=variant.tracked_link,
            key=f"creative_link_{variant.variant_id}",
        )

        st.write("### Record platform and conversion results")
        today = date.today()
        with st.form(f"creative_outcome_{experiment.experiment_id}_{variant.variant_id}"):
            period_columns = st.columns(2)
            period_start = period_columns[0].date_input(
                "Period start",
                value=today - timedelta(days=7),
            )
            period_end = period_columns[1].date_input("Period end", value=today)
            metric_columns = st.columns(3)
            impressions = metric_columns[0].number_input(
                "Impressions",
                min_value=0,
                value=0,
            )
            reported_clicks = metric_columns[1].number_input(
                "Platform-reported clicks",
                min_value=0,
                value=0,
            )
            inquiries = metric_columns[2].number_input(
                "Inquiries",
                min_value=0,
                value=0,
            )
            result_columns = st.columns(3)
            applications = result_columns[0].number_input(
                "Applications",
                min_value=0,
                value=0,
            )
            contracts = result_columns[1].number_input(
                "Filled homes / contracts",
                min_value=0,
                value=0,
            )
            spend = result_columns[2].number_input(
                "Spend",
                min_value=0.0,
                value=0.0,
                step=1.0,
            )
            outcome_notes = st.text_area("Notes", height=80)
            save_outcome = st.form_submit_button("Save Variant Results", type="primary")
        if save_outcome:
            try:
                updated = upsert_outcome(
                    ledger,
                    experiment_id=experiment.experiment_id,
                    variant_id=variant.variant_id,
                    period_start=period_start,
                    period_end=period_end,
                    impressions=int(impressions),
                    reported_clicks=int(reported_clicks),
                    inquiries=int(inquiries),
                    applications=int(applications),
                    contracts=int(contracts),
                    spend=Decimal(str(spend)),
                    notes=outcome_notes,
                )
                testing_store.save(updated)
                st.success("Variant results saved. Matching period records are updated, not duplicated.")
                st.rerun()
            except CreativeTestingError as exc:
                st.error(str(exc))

        recommendation = winner_recommendation(ledger, experiment, click_events)
        st.write("### Live test score")
        st.dataframe(
            pd.DataFrame(metric_rows(recommendation)),
            use_container_width=True,
            hide_index=True,
        )
        if recommendation.ready:
            st.success(recommendation.reason)
        else:
            st.info(recommendation.reason)

with winner_tab:
    reviewable = [
        experiment
        for experiment in ledger.experiments
        if experiment.status
        in {
            ExperimentStatus.RUNNING,
            ExperimentStatus.WINNER_READY,
            ExperimentStatus.WINNER_APPROVED,
        }
    ]
    if not reviewable:
        st.info("No running creative test is ready for winner review.")
    else:
        review_options = {
            experiment_label(experiment): experiment for experiment in reviewable
        }
        review_label = st.selectbox(
            "Test to review",
            list(review_options),
            key="creative_winner_experiment",
        )
        experiment = review_options[review_label]
        recommendation = winner_recommendation(ledger, experiment, click_events)
        st.dataframe(
            pd.DataFrame(metric_rows(recommendation)),
            use_container_width=True,
            hide_index=True,
        )
        summary_columns = st.columns(4)
        summary_columns[0].metric("Ready", "Yes" if recommendation.ready else "No")
        summary_columns[1].metric(
            "Recommended Winner",
            recommendation.winner_key or "Keep Testing",
        )
        summary_columns[2].metric("Measured Lift", f"{recommendation.lift_percent:.1f}%")
        summary_columns[3].metric("Confidence", recommendation.confidence)
        st.info(recommendation.reason)

        if recommendation.ready and experiment.status == ExperimentStatus.RUNNING:
            if st.button("Mark Winner Ready for Manager Approval", type="primary"):
                try:
                    updated = mark_winner_ready(
                        ledger,
                        experiment_id=experiment.experiment_id,
                        click_events=click_events,
                    )
                    testing_store.save(updated)
                    st.success("Winner marked Ready. No traffic allocation changed yet.")
                    st.rerun()
                except CreativeTestingError as exc:
                    st.error(str(exc))

        if experiment.status == ExperimentStatus.WINNER_READY:
            manager = st.text_input(
                "Manager approving the winner",
                value="Sabrina",
                key="creative_winner_manager",
            )
            st.warning(
                "Approval changes future rotation to approximately 70% winner and 30% challengers. "
                "It does not publish, send, or change existing campaigns automatically."
            )
            if st.button(
                "Approve Winner and Update Rotation",
                type="primary",
                use_container_width=True,
            ):
                try:
                    updated = approve_winner(
                        ledger,
                        experiment_id=experiment.experiment_id,
                        approved_by=manager,
                        click_events=click_events,
                    )
                    testing_store.save(updated)
                    st.success("Winner approved. Future assignment rotation now favors the winner.")
                    st.rerun()
                except CreativeTestingError as exc:
                    st.error(str(exc))

        if experiment.status == ExperimentStatus.WINNER_APPROVED:
            st.success(
                f"Winner approved by {experiment.winner_approved_by}. Current allocation is shown below."
            )
            st.dataframe(
                pd.DataFrame(allocation_rows(experiment)),
                use_container_width=True,
                hide_index=True,
            )
            if st.button("Complete and Archive Test"):
                updated = update_experiment_status(
                    ledger,
                    experiment_id=experiment.experiment_id,
                    status=ExperimentStatus.COMPLETED,
                )
                testing_store.save(updated)
                st.success("Creative test completed and archived.")
                st.rerun()

with rotation_tab:
    rotatable = [
        experiment
        for experiment in ledger.experiments
        if experiment.status
        in {
            ExperimentStatus.RUNNING,
            ExperimentStatus.WINNER_READY,
            ExperimentStatus.WINNER_APPROVED,
        }
    ]
    if not rotatable:
        st.info("Start a creative test before previewing traffic rotation.")
    else:
        rotation_options = {
            experiment_label(experiment): experiment for experiment in rotatable
        }
        rotation_label = st.selectbox(
            "Test",
            list(rotation_options),
            key="creative_rotation_experiment",
        )
        experiment = rotation_options[rotation_label]
        st.dataframe(
            pd.DataFrame(allocation_rows(experiment)),
            use_container_width=True,
            hide_index=True,
        )
        assignment_key = st.text_input(
            "Recipient, lead, session, or campaign assignment key",
            value="example-buyer-001",
        )
        if assignment_key.strip():
            selected_variant = assigned_variant(experiment, assignment_key.strip())
            st.success(
                f"This key is assigned to Variant {selected_variant.key}: {selected_variant.angle}"
            )
            st.code(selected_variant.copy, language=None)

        eligible_buyers = consent_ready_buyers(buyers, experiment.channel_key)
        if experiment.channel_key in {"email", "sms"}:
            st.write("### Consent-safe buyer assignment export")
            assignment_rows = []
            for buyer in eligible_buyers:
                variant = assigned_variant(experiment, buyer.buyer_id)
                assignment_rows.append(
                    {
                        "Buyer ID": str(buyer.buyer_id),
                        "Buyer": f"{buyer.first_name} {buyer.last_name}".strip(),
                        "Channel": experiment.channel_name,
                        "Recipient": buyer.email if experiment.channel_key == "email" else buyer.phone,
                        "Variant": variant.key,
                        "Angle": variant.angle,
                        "Campaign": variant.campaign,
                        "Tracked Link": variant.tracked_link,
                        "Copy": variant.copy,
                    }
                )
            if assignment_rows:
                assignment_table = pd.DataFrame(assignment_rows)
                st.dataframe(
                    assignment_table.drop(columns=["Copy"]),
                    use_container_width=True,
                    hide_index=True,
                )
                st.download_button(
                    "Download Consent-Safe Rotation Assignments (CSV)",
                    data=assignment_table.to_csv(index=False).encode(),
                    file_name="creative_rotation_assignments.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.info(
                    "No buyers currently have the saved consent and contact information required for this channel."
                )
        else:
            st.info(
                "Use a stable lead, session, ad-set, or posting key to keep the same audience assigned "
                "to the same variant throughout the test."
            )

with history_tab:
    history = experiment_history_rows(ledger)
    if history:
        history_table = pd.DataFrame(history)
        st.dataframe(history_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Creative Test History (CSV)",
            data=history_table.to_csv(index=False).encode(),
            file_name="creative_test_history.csv",
            mime="text/csv",
        )
    else:
        st.info("No creative tests have been created yet.")

st.info(
    "Safety rules: Facebook Marketplace is excluded; total purchase price stays out of public test copy; "
    "approval guarantees, discriminatory housing language, safety claims, and spam tactics are blocked. "
    "The engine recommends and rotates creative packages but never publishes or sends without the connected workflow's approval rules."
)
