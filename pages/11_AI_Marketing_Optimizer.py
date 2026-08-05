from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channels import CHANNELS, CHANNELS_BY_KEY
from cfh_disposition.marketing_optimizer import (
    AIMarketingPlan,
    MarketingOptimizerError,
    MarketingOptimizerSettings,
    MarketingOptimizerStore,
    build_channel_performance,
    build_fallback_marketing_plan,
    channel_performance_rows,
    clicks_in_period,
    generate_ai_marketing_plan,
    history_rows,
    records_in_period,
    upsert_performance_record,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Marketing Optimizer",
    page_icon="🧠",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error(
            "This app is locked until APP_PASSWORD is added in Streamlit Secrets."
        )
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("AI Marketing Optimizer")
    st.caption("Private internal access")
    with st.form("ai_marketing_optimizer_login"):
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


def _plan_key(
    period_start: date,
    period_end: date,
    property_ids: list[str],
) -> str:
    property_token = "_".join(sorted(property_ids))
    return (
        f"ai_marketing_plan_{period_start.isoformat()}_"
        f"{period_end.isoformat()}_{property_token}"
    )


def _display_plan(plan: AIMarketingPlan) -> None:
    st.write("## AI seven-day marketing plan")
    st.write(plan.executive_summary)

    st.write("### Immediate actions")
    for number, action in enumerate(plan.immediate_actions, start=1):
        st.write(f"**{number}.** {action}")

    st.write("### Channel decisions")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Channel": CHANNELS_BY_KEY[item.channel_key].name,
                    "Decision": item.action,
                    "Why": item.reason,
                    "Seven-Day Test": item.seven_day_test,
                }
                for item in plan.channel_decisions
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    if plan.property_priorities:
        st.write("### Property priorities")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Property": item.property_address,
                        "Priority": item.priority,
                        "Why": item.reason,
                        "Primary Channel": CHANNELS_BY_KEY[
                            item.primary_channel
                        ].name,
                        "Secondary Channel": CHANNELS_BY_KEY[
                            item.secondary_channel
                        ].name,
                    }
                    for item in plan.property_priorities
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.write("### Creative tests")
    for test in plan.creative_tests:
        with st.expander(
            f"{CHANNELS_BY_KEY[test.channel_key].name} — {test.test_name}"
        ):
            st.write(f"**Control:** {test.control_angle}")
            st.write(f"**Challenger:** {test.challenger_angle}")
            st.write(f"**Primary metric:** {test.primary_metric}")
            st.write(f"**Stop rule:** {test.stop_rule}")

    if plan.measurement_gaps:
        st.write("### Measurement gaps to fix")
        for gap in plan.measurement_gaps:
            st.warning(gap)


require_password()
st.title("AI Marketing Optimizer")
st.caption(
    "Use tracked Dwelyx clicks plus the team's inquiry, application, contract, and spend results "
    "to decide what to scale, repair, pause, or test next."
)
st.info(
    "This optimizer never targets protected classes and never recommends hidden Facebook automation. "
    "Facebook Marketplace and member-only Facebook Group publication remain manual."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    optimizer_store = MarketingOptimizerStore(st.secrets)
    optimizer_ledger = optimizer_store.load()
    click_store = ClickAnalyticsStore(st.secrets)
except (StorageError, MarketingOptimizerError, AnalyticsError) as exc:
    st.error(f"AI Marketing Optimizer is safety-locked: {exc}")
    st.stop()

if not properties:
    st.info("Add a property before using the AI Marketing Optimizer.")
    st.stop()

property_options = {
    item.display_address or str(item.property_id): item for item in properties
}

control_left, control_middle, control_right = st.columns([1, 2, 2])
analysis_days = control_left.selectbox(
    "Analysis window",
    [7, 14, 30, 60, 90],
    index=2,
    format_func=lambda value: f"Last {value} days",
)
period_end = control_middle.date_input(
    "Analysis end date",
    value=date.today(),
    key="ai_optimizer_period_end",
)
period_start = period_end - timedelta(days=int(analysis_days) - 1)
selected_property_names = control_right.multiselect(
    "Properties to analyze",
    options=list(property_options),
    default=list(property_options),
    key="ai_optimizer_properties",
)

selected_properties = [
    property_options[name] for name in selected_property_names
]
selected_property_ids = {
    str(item.property_id) for item in selected_properties
}

try:
    all_click_events = click_store.list_recent(days=max(int(analysis_days), 1))
except AnalyticsError as exc:
    st.warning(
        f"Tracked click data could not be loaded: {exc}. Manual outcome data remains available."
    )
    all_click_events = []

period_records = records_in_period(
    optimizer_ledger,
    period_start,
    period_end,
    selected_property_ids,
)
period_clicks = clicks_in_period(
    all_click_events,
    period_start,
    period_end,
    selected_property_ids,
)
performance = build_channel_performance(period_records, period_clicks)

tracked_click_total = sum(row.tracked_clicks for row in performance)
inquiry_total = sum(row.inquiries for row in performance)
application_total = sum(row.applications for row in performance)
contract_total = sum(row.contracts for row in performance)
spend_total = sum((row.spend for row in performance), Decimal("0"))

metrics = st.columns(5)
metrics[0].metric("Tracked Dwelyx Clicks", tracked_click_total)
metrics[1].metric("Inquiries", inquiry_total)
metrics[2].metric("Applications", application_total)
metrics[3].metric("Contracts", contract_total)
metrics[4].metric("Recorded Spend", f"${spend_total:,.2f}")
st.caption(
    f"Analysis period: {period_start.isoformat()} through {period_end.isoformat()}"
)

plan_tab, results_tab, scoreboard_tab, history_tab = st.tabs(
    [
        "AI Action Plan",
        "Enter Marketing Results",
        "Channel Scoreboard",
        "Performance History",
    ]
)

with plan_tab:
    if not selected_properties:
        st.info("Select at least one property above to generate a marketing plan.")
    else:
        st.write("### Current measured decisions")
        st.dataframe(
            pd.DataFrame(channel_performance_rows(performance[:6])),
            use_container_width=True,
            hide_index=True,
        )
        settings = MarketingOptimizerSettings.from_mapping(st.secrets)
        plan_key = _plan_key(
            period_start,
            period_end,
            sorted(selected_property_ids),
        )
        button_label = (
            "Generate AI Seven-Day Marketing Plan"
            if settings.configured
            else "Build Measured Seven-Day Marketing Plan"
        )
        if st.button(
            button_label,
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Analyzing channels, properties, and campaign outcomes..."):
                try:
                    if settings.configured:
                        plan = generate_ai_marketing_plan(
                            selected_properties,
                            performance,
                            period_records,
                            period_clicks,
                            period_start=period_start,
                            period_end=period_end,
                            settings=settings,
                        )
                        st.success(
                            "AI marketing plan generated from the selected performance data."
                        )
                    else:
                        plan = build_fallback_marketing_plan(
                            selected_properties,
                            performance,
                            period_clicks,
                        )
                        st.info(
                            "OPENAI_API_KEY is not configured, so the measured fallback plan was generated."
                        )
                except MarketingOptimizerError as exc:
                    st.warning(
                        f"AI plan was unavailable: {exc} The measured fallback plan is shown instead."
                    )
                    plan = build_fallback_marketing_plan(
                        selected_properties,
                        performance,
                        period_clicks,
                    )
                st.session_state[plan_key] = plan.model_dump(mode="json")

        saved_plan = st.session_state.get(plan_key)
        if saved_plan:
            _display_plan(AIMarketingPlan.model_validate(saved_plan))
        else:
            st.info(
                "Generate the plan after the team enters the latest inquiry, application, contract, "
                "and spend results. Tracked Dwelyx clicks are already included automatically."
            )

with results_tab:
    st.write("### Enter one property's channel results")
    st.caption(
        "Tracked Dwelyx clicks are loaded automatically. Use Reported Clicks for platform clicks "
        "that are not captured by the tracked buyer link. Saving the same property, channel, and "
        "date range updates the existing record instead of duplicating it."
    )
    with st.form("marketing_optimizer_results_form", clear_on_submit=True):
        result_property_name = st.selectbox(
            "Property*",
            list(property_options),
        )
        result_channel_key = st.selectbox(
            "Marketing channel*",
            [channel.key for channel in CHANNELS],
            format_func=lambda key: CHANNELS_BY_KEY[key].name,
        )
        date_left, date_right = st.columns(2)
        result_start = date_left.date_input(
            "Results period start*",
            value=period_start,
        )
        result_end = date_right.date_input(
            "Results period end*",
            value=period_end,
        )
        number_columns = st.columns(3)
        impressions = number_columns[0].number_input(
            "Impressions",
            min_value=0,
            value=0,
            step=1,
        )
        reported_clicks = number_columns[1].number_input(
            "Reported Clicks",
            min_value=0,
            value=0,
            step=1,
        )
        inquiries = number_columns[2].number_input(
            "Inquiries",
            min_value=0,
            value=0,
            step=1,
        )
        outcome_columns = st.columns(3)
        applications = outcome_columns[0].number_input(
            "Applications",
            min_value=0,
            value=0,
            step=1,
        )
        contracts = outcome_columns[1].number_input(
            "Contracts / Filled Homes",
            min_value=0,
            value=0,
            step=1,
        )
        spend = outcome_columns[2].number_input(
            "Marketing Spend",
            min_value=0.0,
            value=0.0,
            step=10.0,
            format="%.2f",
        )
        notes = st.text_area(
            "Campaign name, creative used, lead quality, objections, or notes",
            height=100,
        )
        save_results = st.form_submit_button(
            "Save Marketing Results",
            type="primary",
        )

    if save_results:
        selected_result_property = property_options[result_property_name]
        try:
            updated_ledger = upsert_performance_record(
                optimizer_ledger,
                period_start=result_start,
                period_end=result_end,
                property_id=str(selected_result_property.property_id),
                property_address=selected_result_property.display_address,
                channel_key=result_channel_key,
                impressions=int(impressions),
                reported_clicks=int(reported_clicks),
                inquiries=int(inquiries),
                applications=int(applications),
                contracts=int(contracts),
                spend=Decimal(str(spend)),
                notes=notes,
            )
            optimizer_store.save(updated_ledger)
            st.success(
                f"Saved {CHANNELS_BY_KEY[result_channel_key].name} results for "
                f"{selected_result_property.display_address}."
            )
            st.rerun()
        except (MarketingOptimizerError, ValueError) as exc:
            st.error(f"Marketing results could not be saved: {exc}")

with scoreboard_tab:
    st.write("### All-channel decision board")
    st.dataframe(
        pd.DataFrame(channel_performance_rows(performance)),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Usable Clicks uses the higher of the team's reported platform clicks or tracked Dwelyx "
        "clicks so a partially tracked campaign is not understated. Decisions become stronger as "
        "the team records inquiries, applications, contracts, and spend."
    )

with history_tab:
    st.write("### Saved marketing outcome history")
    rows = history_rows(optimizer_ledger)
    if rows:
        table = pd.DataFrame(rows)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Marketing Performance History (CSV)",
            data=table.to_csv(index=False).encode(),
            file_name="credit_friendly_homes_marketing_performance.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No manual outcome records are saved yet. Tracked Dwelyx click data can still be analyzed."
        )
