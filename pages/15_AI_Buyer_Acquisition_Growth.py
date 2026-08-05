from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_acquisition import (
    MANUAL_PUBLICATION_SOURCES,
    PAID_SOURCES,
    SUPPORTED_ACQUISITION_SOURCES,
    AcquisitionCampaignStatus,
    BuyerAcquisitionError,
    BuyerAcquisitionStore,
    allocation_rows,
    build_acquisition_campaign,
    build_acquisition_performance,
    create_campaign,
    performance_rows,
    recommend_budget_allocation,
    update_campaign_status,
    upsert_outcome,
)
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Buyer Acquisition & Growth",
    page_icon="📈",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("AI Buyer Acquisition & Audience Growth")
    st.caption("Private internal access")
    with st.form("buyer_acquisition_login"):
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


def campaign_label(campaign) -> str:
    scope = campaign.property_address or f"{campaign.market_city}, {campaign.market_state}"
    return f"{campaign.status.value} — {campaign.source_name} — {scope}"


def campaign_history_rows(ledger) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for campaign in sorted(ledger.campaigns, key=lambda item: item.created_at, reverse=True):
        rows.append(
            {
                "Created": campaign.created_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Status": campaign.status.value,
                "Campaign": campaign.name,
                "Source": campaign.source_name,
                "Market": f"{campaign.market_city}, {campaign.market_state}",
                "Property": campaign.property_address or "Market-wide",
                "Weekly Budget": f"${campaign.weekly_budget:,.2f}",
                "Target Cost / Registration": f"${campaign.target_cost_per_registration:,.2f}",
                "Approved By": campaign.approved_by or "—",
            }
        )
    return rows


require_password()
st.title("AI Buyer Acquisition & Audience Growth Engine")
st.caption(
    "Builds measured campaigns that bring new owner-finance buyers into Dwelyx, tracks which sources "
    "produce qualified buyers, and recommends where the next marketing dollar should go."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    acquisition_store = BuyerAcquisitionStore(st.secrets)
    ledger = acquisition_store.load()
    try:
        click_events = ClickAnalyticsStore(st.secrets).list_recent(120)
        click_warning = ""
    except AnalyticsError as exc:
        click_events = []
        click_warning = str(exc)
except (StorageError, BuyerAcquisitionError) as exc:
    st.error(f"Buyer Acquisition Engine is safety-locked: {exc}")
    st.stop()

if click_warning:
    st.warning(
        "Tracked Dwelyx clicks could not be loaded. The engine will use platform-reported clicks until "
        f"analytics is restored: {click_warning}"
    )

create_tab, launch_tab, results_tab, score_tab, history_tab = st.tabs(
    [
        "Create Growth Campaign",
        "Approve & Launch",
        "Record Results",
        "AI Growth Scoreboard",
        "History",
    ]
)

with create_tab:
    st.write("### Create a new-buyer campaign")
    source_key = st.selectbox(
        "Buyer-acquisition source",
        list(SUPPORTED_ACQUISITION_SOURCES),
        format_func=lambda key: SUPPORTED_ACQUISITION_SOURCES[key],
    )
    scope = st.radio(
        "Campaign scope",
        ["Grow the buyer list for a market", "Promote one available property"],
        horizontal=True,
    )
    property_record = None
    if scope == "Promote one available property":
        if not properties:
            st.info("Add a property before creating a property-specific buyer campaign.")
        else:
            property_options = {
                item.display_address or str(item.property_id): item for item in properties
            }
            property_name = st.selectbox("Property", list(property_options))
            property_record = property_options[property_name]
    market_columns = st.columns(2)
    default_city = property_record.city if property_record else ""
    default_state = property_record.state if property_record else ""
    market_city = market_columns[0].text_input("Target market city*", value=default_city)
    market_state = market_columns[1].text_input("State*", value=default_state, max_chars=2)
    goal_columns = st.columns(3)
    weekly_budget = goal_columns[0].number_input(
        "Weekly campaign budget",
        min_value=0.0,
        value=0.0,
        step=25.0,
    )
    target_cost = goal_columns[1].number_input(
        "Target cost per Dwelyx registration",
        min_value=1.0,
        value=20.0,
        step=5.0,
    )
    weekly_goal = goal_columns[2].number_input(
        "New buyer registrations per week",
        min_value=1,
        max_value=100000,
        value=10,
    )
    campaign_name = st.text_input(
        "Campaign name — optional",
        placeholder="Example: Decatur buyer list growth — Meta",
    )
    audience_notes = st.text_area(
        "Audience and targeting notes",
        value="Adults seeking owner-finance home information in the selected market.",
        height=100,
    )
    st.info(
        "The engine allows broad market and housing-intent targeting only. Protected-class targeting, "
        "approval promises, neighborhood safety claims, and discriminatory housing language are blocked."
    )
    create_disabled = scope == "Promote one available property" and property_record is None
    if st.button(
        "Create Fact-Safe Buyer Growth Campaign",
        type="primary",
        use_container_width=True,
        disabled=create_disabled,
    ):
        try:
            campaign = build_acquisition_campaign(
                source_key=source_key,
                market_city=market_city,
                market_state=market_state,
                dwelyx_url=dwelyx_base_url(st.secrets),
                weekly_budget=Decimal(str(weekly_budget)),
                target_cost_per_registration=Decimal(str(target_cost)),
                weekly_registration_goal=int(weekly_goal),
                audience_notes=audience_notes,
                property_record=property_record,
                name=campaign_name,
            )
            updated = create_campaign(ledger, campaign)
            acquisition_store.save(updated)
            st.success("Buyer-growth campaign created. Review and approve it before launch.")
            st.rerun()
        except BuyerAcquisitionError as exc:
            st.error(str(exc))

with launch_tab:
    if not ledger.campaigns:
        st.info("Create the first buyer-growth campaign before approval or launch.")
    else:
        options = {campaign_label(campaign): campaign for campaign in ledger.campaigns}
        selected_label = st.selectbox("Campaign", list(options), key="buyer_growth_launch_campaign")
        campaign = options[selected_label]
        status_columns = st.columns(5)
        status_columns[0].metric("Status", campaign.status.value)
        status_columns[1].metric("Source", campaign.source_name)
        status_columns[2].metric("Weekly Budget", f"${campaign.weekly_budget:,.0f}")
        status_columns[3].metric("Registration Goal", campaign.weekly_registration_goal)
        status_columns[4].metric("Target Cost", f"${campaign.target_cost_per_registration:,.0f}")

        st.write("### Campaign package")
        st.text_input("Headline", value=campaign.headline)
        st.text_area("Primary campaign copy", value=campaign.primary_copy, height=260)
        st.text_area("Short video hook", value=campaign.short_video_hook, height=130)
        st.text_area("Call to action", value=campaign.call_to_action, height=100)
        st.text_input("Tracked Dwelyx registration link", value=campaign.tracked_link)
        st.info(campaign.publication_instructions)

        if campaign.source_key in MANUAL_PUBLICATION_SOURCES:
            st.warning("This source requires the final publication step to remain manual or platform-approved.")
        if campaign.source_key in PAID_SOURCES:
            st.warning("Do not spend money until a manager approves the campaign and the platform setup is reviewed.")

        manager = st.text_input("Manager", value="Sabrina", key="buyer_growth_manager")
        action_columns = st.columns(4)
        if action_columns[0].button(
            "Approve Campaign",
            type="primary",
            use_container_width=True,
            disabled=campaign.status != AcquisitionCampaignStatus.DRAFT,
        ):
            try:
                updated = update_campaign_status(
                    ledger,
                    campaign_id=campaign.campaign_id,
                    status=AcquisitionCampaignStatus.APPROVED,
                    actor=manager,
                )
                acquisition_store.save(updated)
                st.success("Campaign approved. It is ready for platform setup or manual publication.")
                st.rerun()
            except BuyerAcquisitionError as exc:
                st.error(str(exc))
        if action_columns[1].button(
            "Mark Live",
            use_container_width=True,
            disabled=campaign.status not in {AcquisitionCampaignStatus.APPROVED, AcquisitionCampaignStatus.PAUSED},
        ):
            try:
                updated = update_campaign_status(
                    ledger,
                    campaign_id=campaign.campaign_id,
                    status=AcquisitionCampaignStatus.LIVE,
                    actor=manager,
                )
                acquisition_store.save(updated)
                st.success("Campaign marked Live. Start recording results by reporting period.")
                st.rerun()
            except BuyerAcquisitionError as exc:
                st.error(str(exc))
        if action_columns[2].button(
            "Pause",
            use_container_width=True,
            disabled=campaign.status != AcquisitionCampaignStatus.LIVE,
        ):
            updated = update_campaign_status(
                ledger,
                campaign_id=campaign.campaign_id,
                status=AcquisitionCampaignStatus.PAUSED,
            )
            acquisition_store.save(updated)
            st.success("Campaign paused.")
            st.rerun()
        if action_columns[3].button(
            "Complete",
            use_container_width=True,
            disabled=campaign.status == AcquisitionCampaignStatus.COMPLETED,
        ):
            updated = update_campaign_status(
                ledger,
                campaign_id=campaign.campaign_id,
                status=AcquisitionCampaignStatus.COMPLETED,
            )
            acquisition_store.save(updated)
            st.success("Campaign completed and retained in history.")
            st.rerun()

with results_tab:
    if not ledger.campaigns:
        st.info("Create a campaign before recording buyer-acquisition results.")
    else:
        campaign_options = {campaign_label(campaign): campaign for campaign in ledger.campaigns}
        result_label = st.selectbox("Campaign", list(campaign_options), key="buyer_growth_result_campaign")
        campaign = campaign_options[result_label]
        today = date.today()
        with st.form("buyer_acquisition_results"):
            period_columns = st.columns(2)
            period_start = period_columns[0].date_input("Period start", value=today - timedelta(days=7))
            period_end = period_columns[1].date_input("Period end", value=today)
            traffic_columns = st.columns(3)
            impressions = traffic_columns[0].number_input("Impressions", min_value=0, value=0)
            reported_clicks = traffic_columns[1].number_input("Platform-reported clicks", min_value=0, value=0)
            registrations = traffic_columns[2].number_input("New Dwelyx buyer registrations", min_value=0, value=0)
            buyer_columns = st.columns(3)
            qualified_buyers = buyer_columns[0].number_input("Qualified buyers", min_value=0, value=0)
            applications = buyer_columns[1].number_input("Applications", min_value=0, value=0)
            contracts = buyer_columns[2].number_input("Filled homes / contracts", min_value=0, value=0)
            spend = st.number_input("Campaign spend", min_value=0.0, value=0.0, step=25.0)
            result_notes = st.text_area("Notes", height=80)
            save_results = st.form_submit_button("Save Acquisition Results", type="primary")
        if save_results:
            try:
                updated = upsert_outcome(
                    ledger,
                    campaign_id=campaign.campaign_id,
                    period_start=period_start,
                    period_end=period_end,
                    impressions=int(impressions),
                    reported_clicks=int(reported_clicks),
                    registrations=int(registrations),
                    qualified_buyers=int(qualified_buyers),
                    applications=int(applications),
                    contracts=int(contracts),
                    spend=Decimal(str(spend)),
                    notes=result_notes,
                )
                acquisition_store.save(updated)
                st.success("Acquisition results saved. Matching campaign/date records are updated instead of duplicated.")
                st.rerun()
            except (BuyerAcquisitionError, ValueError) as exc:
                st.error(str(exc))

with score_tab:
    performance = build_acquisition_performance(ledger, click_events)
    if not performance:
        st.info("Create campaigns to start the buyer-acquisition scoreboard.")
    else:
        total_registrations = sum(row.registrations for row in performance)
        total_qualified = sum(row.qualified_buyers for row in performance)
        total_applications = sum(row.applications for row in performance)
        total_contracts = sum(row.contracts for row in performance)
        metrics = st.columns(5)
        metrics[0].metric("New Registrations", total_registrations)
        metrics[1].metric("Qualified Buyers", total_qualified)
        metrics[2].metric("Applications", total_applications)
        metrics[3].metric("Filled / Contracts", total_contracts)
        metrics[4].metric(
            "Tracked Dwelyx Clicks",
            sum(row.tracked_clicks for row in performance),
        )
        st.dataframe(
            pd.DataFrame(performance_rows(performance)),
            use_container_width=True,
            hide_index=True,
        )

        st.write("### AI weekly budget allocation")
        current_total = sum((campaign.weekly_budget for campaign in ledger.campaigns), Decimal("0"))
        total_budget = st.number_input(
            "Total weekly buyer-acquisition budget to allocate",
            min_value=0.0,
            value=float(current_total),
            step=50.0,
        )
        allocations = recommend_budget_allocation(
            ledger.campaigns,
            performance,
            Decimal(str(total_budget)),
        )
        if allocations:
            st.dataframe(
                pd.DataFrame(allocation_rows(allocations)),
                use_container_width=True,
                hide_index=True,
            )
            projected = sum(row.projected_registrations for row in allocations)
            st.success(
                f"At the saved target acquisition costs, this allocation projects about {projected} new "
                "Dwelyx registrations per week. This is a planning estimate, not a guarantee."
            )
        else:
            st.info("Approve at least one campaign before the engine allocates a weekly budget.")

        st.write("### Next 30-day growth actions")
        for index, row in enumerate(performance[:8], start=1):
            st.write(
                f"**{index}. {row.recommendation.value}: {row.campaign_name}** — {row.reason}"
            )

with history_tab:
    campaign_rows = campaign_history_rows(ledger)
    if campaign_rows:
        campaign_table = pd.DataFrame(campaign_rows)
        st.dataframe(campaign_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Buyer Acquisition Campaigns (CSV)",
            data=campaign_table.to_csv(index=False).encode(),
            file_name="buyer_acquisition_campaigns.csv",
            mime="text/csv",
        )
    else:
        st.info("No buyer-acquisition campaigns have been created yet.")

    if ledger.outcomes:
        outcome_rows = [
            {
                "Campaign ID": row.campaign_id,
                "Period Start": row.period_start.isoformat(),
                "Period End": row.period_end.isoformat(),
                "Impressions": row.impressions,
                "Reported Clicks": row.reported_clicks,
                "Registrations": row.registrations,
                "Qualified Buyers": row.qualified_buyers,
                "Applications": row.applications,
                "Filled / Contracts": row.contracts,
                "Spend": f"${row.spend:,.2f}",
                "Notes": row.notes or "—",
            }
            for row in sorted(ledger.outcomes, key=lambda item: item.period_end, reverse=True)
        ]
        outcome_table = pd.DataFrame(outcome_rows)
        st.write("### Reporting-period history")
        st.dataframe(outcome_table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Buyer Acquisition Results (CSV)",
            data=outcome_table.to_csv(index=False).encode(),
            file_name="buyer_acquisition_results.csv",
            mime="text/csv",
        )

st.info(
    "The engine creates and measures buyer-acquisition campaigns. It does not purchase ads, publish to "
    "member-only Facebook Groups, send unsolicited messages, or change budgets without manager action."
)
