from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_conversion import (
    BuyerConversionError,
    BuyerConversionLedger,
    BuyerConversionStore,
    build_conversion_queue,
)
from cfh_disposition.campaign_cadence import (
    CampaignCadenceError,
    CampaignCadenceLedger,
    CampaignCadenceStore,
    build_cadence_queue,
)
from cfh_disposition.campaign_launch import CampaignLaunchStore, LaunchStoreError
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionStore,
)
from cfh_disposition.executive_cadence import cadence_action_items
from cfh_disposition.executive_command import (
    ExecutiveLane,
    ExecutivePriority,
    action_rows,
    build_executive_snapshot,
    conversion_action_items,
    daily_brief_text,
    deduplicate_and_sort,
    inventory_action_items,
    portfolio_rows,
    property_control_action_items,
    showing_action_items,
    system_action_items,
    terms_action_items,
)
from cfh_disposition.inventory_velocity import (
    InventoryVelocityError,
    InventoryVelocityLedger,
    InventoryVelocityStore,
    build_velocity_queue,
)
from cfh_disposition.property_shutdown import (
    PropertyControlError,
    PropertyControlLedger,
    PropertyControlStore,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.showing_conversion import (
    ShowingConversionError,
    ShowingConversionLedger,
    ShowingConversionStore,
    build_showing_queue,
)
from cfh_disposition.storage import StorageError, build_storage
from cfh_disposition.terms_testing import (
    TermsExperimentStatus,
    TermsTestingError,
    TermsTestingLedger,
    TermsTestingStore,
    recommendation_for_experiment,
)

st.set_page_config(
    page_title="Daily Executive Disposition Command Center",
    page_icon="🎯",
    layout="wide",
)

PAGE_PATHS = {
    "15-Channel Campaign Cadence & Refresh Center": "pages/24_15_Channel_Campaign_Cadence_Refresh.py",
    "Vacant Home Disposition Escalation Center": "pages/20_Vacant_Home_Disposition_Escalation.py",
    "AI Buyer Conversion & Follow-Up Command Center": "pages/16_AI_Buyer_Conversion_Command_Center.py",
    "Showing-to-Contract Conversion Center": "pages/22_Showing_to_Contract_Conversion.py",
    "Property Terms Test & Relaunch Center": "pages/21_Property_Terms_Test_Relaunch.py",
    "Property Shutdown & Buyer Reroute Center": "pages/18_Property_Shutdown_Buyer_Reroute.py",
    "Dwelyx Results Tracking & Attribution Center": "pages/19_Dwelyx_Results_Attribution.py",
}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Daily Executive Disposition Command Center")
    st.caption("Private internal access")
    with st.form("executive_command_login"):
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


def page_link(page_name: str, *, label: str | None = None) -> None:
    path = PAGE_PATHS.get(page_name)
    if path:
        st.page_link(path, label=label or f"Open {page_name}")


def render_action_cards(items, *, maximum: int = 8) -> None:
    if not items:
        st.success("No actions match this lane and filter.")
        return
    for item in items[:maximum]:
        context = " · ".join(value for value in (item.property_address, item.buyer_name) if value)
        heading = f"{item.priority.value} — {item.title}"
        with st.expander(
            heading,
            expanded=item.priority
            in {
                ExecutivePriority.BLOCKED,
                ExecutivePriority.CRITICAL,
                ExecutivePriority.URGENT,
            },
        ):
            if context:
                st.caption(context)
            columns = st.columns(4)
            columns[0].metric("Lane", item.lane.value)
            columns[1].metric("Owner", item.owner)
            columns[2].metric(
                "Due",
                item.due_at.astimezone().strftime("%b %d, %I:%M %p")
                if item.due_at
                else "Not scheduled",
            )
            columns[3].metric("Source", item.source)
            st.write("**Required action**")
            st.write(item.action)
            st.write("**Why it matters**")
            st.write(item.reason)
            page_link(item.page_name)


require_password()
now = datetime.now(UTC)
st.title("Daily Executive Disposition Command Center")
st.caption(
    "One read-only command screen for 15-channel marketing cadence, management decisions, "
    "team execution, buyer follow-up, showings, property escalation, terms tests, shutdown work, "
    "and connection problems."
)
st.info(
    "This page does not create another task database or change any property, buyer, showing, "
    "campaign, channel, or terms record. Complete each action inside its source operating center."
)

system_errors: dict[str, str] = {}
try:
    storage = get_storage()
    properties = storage.list_properties()
    buyers = storage.list_buyers()
except StorageError as exc:
    st.error(
        f"The Executive Command Center cannot load the core property and buyer records: {exc}"
    )
    st.stop()

try:
    click_events = ClickAnalyticsStore(st.secrets).list_recent(365)
except AnalyticsError as exc:
    click_events = []
    system_errors["Click Analytics"] = str(exc)

try:
    attribution_events = DwelyxAttributionStore(st.secrets).list_events(10000)
except DwelyxAttributionError as exc:
    attribution_events = []
    system_errors["Dwelyx Results"] = str(exc)
real_attribution_events = [event for event in attribution_events if not event.test_mode]
attribution_connected = bool(real_attribution_events)

try:
    velocity_ledger = InventoryVelocityStore(st.secrets).load()
except InventoryVelocityError as exc:
    velocity_ledger = InventoryVelocityLedger()
    system_errors["Vacant Home Escalation"] = str(exc)

launch_states = {}
try:
    launch_store = CampaignLaunchStore(st.secrets)
    for property_record in properties:
        property_id = str(property_record.property_id)
        launch_states[property_id] = launch_store.load(
            property_id,
            "owner_finance_homes",
        )
except LaunchStoreError as exc:
    launch_states = {}
    system_errors["Campaign Launch Records"] = str(exc)

assessments = build_velocity_queue(
    properties,
    ledger=velocity_ledger,
    click_events=click_events,
    attribution_events=attribution_events,
    launch_states=launch_states,
    attribution_connected=attribution_connected,
    now=now,
)

try:
    cadence_ledger = CampaignCadenceStore(st.secrets).load()
except CampaignCadenceError as exc:
    cadence_ledger = CampaignCadenceLedger()
    system_errors["15-Channel Campaign Cadence"] = str(exc)
cadence_queue = build_cadence_queue(
    properties,
    ledger=cadence_ledger,
    launch_states=launch_states,
    click_events=click_events,
    attribution_events=attribution_events,
    now=now,
)

try:
    conversion_ledger = BuyerConversionStore(st.secrets).load()
except BuyerConversionError as exc:
    conversion_ledger = BuyerConversionLedger()
    system_errors["Buyer Conversion Records"] = str(exc)
conversion_queue = build_conversion_queue(
    conversion_ledger,
    buyers,
    properties,
    now=now,
)

try:
    showing_ledger = ShowingConversionStore(st.secrets).load()
except ShowingConversionError as exc:
    showing_ledger = ShowingConversionLedger()
    system_errors["Showing Conversion Records"] = str(exc)
showing_queue = build_showing_queue(
    showing_ledger,
    buyers,
    properties,
    now=now,
)

try:
    terms_ledger = TermsTestingStore(st.secrets).load()
except TermsTestingError as exc:
    terms_ledger = TermsTestingLedger()
    system_errors["Property Terms Testing"] = str(exc)
terms_recommendations = {}
for experiment in terms_ledger.experiments:
    if experiment.status not in {
        TermsExperimentStatus.ACTIVE,
        TermsExperimentStatus.REVIEW_READY,
    }:
        continue
    try:
        terms_recommendations[experiment.experiment_id] = recommendation_for_experiment(
            terms_ledger,
            experiment,
            click_events=click_events,
            attribution_events=attribution_events,
            now=now,
        )
    except TermsTestingError as exc:
        system_errors[f"Terms Test {experiment.experiment_id[:8]}"] = str(exc)

try:
    property_control_ledger = PropertyControlStore(st.secrets).load()
except PropertyControlError as exc:
    property_control_ledger = PropertyControlLedger()
    system_errors["Property Shutdown Records"] = str(exc)

all_items = deduplicate_and_sort(
    [
        *cadence_action_items(cadence_queue, cadence_ledger, now=now),
        *inventory_action_items(assessments, velocity_ledger, now=now),
        *conversion_action_items(conversion_queue, now=now),
        *showing_action_items(showing_queue, now=now),
        *terms_action_items(terms_ledger, terms_recommendations, now=now),
        *property_control_action_items(property_control_ledger, now=now),
        *system_action_items(system_errors, now=now),
    ]
)
snapshot = build_executive_snapshot(
    all_items,
    properties,
    assessments,
    conversion_ledger,
    showing_ledger,
)

metrics = st.columns(6)
metrics[0].metric("Active Vacant Homes", snapshot.active_vacant_properties)
metrics[1].metric("Critical Properties", snapshot.critical_properties)
metrics[2].metric("Urgent / Blocked", snapshot.urgent_or_blocked_actions)
metrics[3].metric("Management Decisions", snapshot.management_decisions)
metrics[4].metric("Team Actions", snapshot.team_actions)
metrics[5].metric(
    "Holding Exposure",
    f"${snapshot.estimated_holding_exposure:,.0f}"
    if snapshot.estimated_holding_exposure > Decimal("0")
    else "Not entered",
)

secondary = st.columns(4)
secondary[0].metric("All Open Actions", snapshot.total_actions)
secondary[1].metric("Compliance Holds", snapshot.compliance_holds)
secondary[2].metric("Contract Pending Buyers", snapshot.contract_pending_records)
secondary[3].metric("Showing Contract Handoffs", snapshot.showing_contract_handoffs)

if attribution_connected:
    st.success(
        f"Dwelyx results connected: {len(real_attribution_events)} live result events available."
    )
else:
    st.warning(
        "Live Dwelyx results are not connected yet. The command center still uses property, buyer, "
        "showing, campaign, channel-cadence, and task records, but registration-to-contract diagnosis "
        "remains limited."
    )

owners = sorted({item.owner for item in all_items if item.owner})
selected_owner = st.sidebar.selectbox("Owner", ["All owners", *owners])
selected_lanes = st.sidebar.multiselect(
    "Lanes",
    list(ExecutiveLane),
    default=list(ExecutiveLane),
    format_func=lambda value: value.value,
)
selected_priorities = st.sidebar.multiselect(
    "Priorities",
    list(ExecutivePriority),
    default=list(ExecutivePriority),
    format_func=lambda value: value.value,
)
filtered_items = [
    item
    for item in all_items
    if (selected_owner == "All owners" or item.owner == selected_owner)
    and item.lane in selected_lanes
    and item.priority in selected_priorities
]

st.sidebar.write("### Operating Centers")
for page_name in PAGE_PATHS:
    page_link(page_name, label=page_name)

today_tab, management_tab, team_tab, portfolio_tab, health_tab, brief_tab = st.tabs(
    [
        "Today's Priorities",
        "Management Decisions",
        "Team Execution",
        "Property Portfolio",
        "System Health",
        "Daily Brief",
    ]
)

with today_tab:
    st.write("### Highest-priority work across the entire disposition system")
    render_action_cards(filtered_items, maximum=8)
    rows = action_rows(filtered_items)
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            height=min(800, max(250, len(frame) * 36 + 45)),
        )
        st.download_button(
            "Download Executive Action Queue",
            frame.to_csv(index=False).encode("utf-8"),
            "daily-executive-disposition-actions.csv",
            "text/csv",
        )

with management_tab:
    management_items = [
        item
        for item in filtered_items
        if item.manager_only or item.lane == ExecutiveLane.MANAGEMENT
    ]
    st.write("### Decisions only Shawn or Sabrina should make")
    render_action_cards(management_items, maximum=12)
    if management_items:
        st.dataframe(
            pd.DataFrame(action_rows(management_items)),
            use_container_width=True,
            hide_index=True,
        )

with team_tab:
    team_items = [
        item
        for item in filtered_items
        if item.lane in {ExecutiveLane.TEAM, ExecutiveLane.COMPLIANCE}
    ]
    st.write("### Work the team can execute without changing approved business terms")
    render_action_cards(team_items, maximum=12)
    if team_items:
        st.dataframe(
            pd.DataFrame(action_rows(team_items)),
            use_container_width=True,
            hide_index=True,
        )

with portfolio_tab:
    st.write("### Property-by-property risk and next action")
    property_frame = pd.DataFrame(portfolio_rows(properties, assessments, all_items))
    if property_frame.empty:
        st.info("No saved properties are available.")
    else:
        st.dataframe(
            property_frame,
            use_container_width=True,
            hide_index=True,
            height=min(800, max(250, len(property_frame) * 36 + 45)),
        )
        st.download_button(
            "Download Property Command Board",
            property_frame.to_csv(index=False).encode("utf-8"),
            "executive-property-command-board.csv",
            "text/csv",
        )

with health_tab:
    st.write("### Data and connection health")
    if not system_errors:
        st.success("Every required ledger loaded successfully.")
    else:
        st.error(
            f"{len(system_errors)} data source or connection problems require review."
        )
        for source, detail in system_errors.items():
            st.write(f"**{source}**")
            st.write(detail)
    health_rows = [
        {
            "Source": "Core Property & Buyer Storage",
            "Status": "Connected",
            "Detail": storage.mode,
        },
        {
            "Source": "Tracked Clicks",
            "Status": "Connected"
            if not system_errors.get("Click Analytics")
            else "Problem",
            "Detail": f"{len(click_events)} events loaded",
        },
        {
            "Source": "Dwelyx Results",
            "Status": "Connected" if attribution_connected else "Waiting",
            "Detail": f"{len(real_attribution_events)} live events loaded",
        },
        {
            "Source": "15-Channel Campaign Cadence",
            "Status": "Connected"
            if not system_errors.get("15-Channel Campaign Cadence")
            else "Problem",
            "Detail": f"{len(cadence_ledger.tasks)} refresh tasks loaded",
        },
        {
            "Source": "Vacant Home Escalation",
            "Status": "Connected"
            if not system_errors.get("Vacant Home Escalation")
            else "Problem",
            "Detail": f"{len(velocity_ledger.tasks)} tasks loaded",
        },
        {
            "Source": "Buyer Conversion",
            "Status": "Connected"
            if not system_errors.get("Buyer Conversion Records")
            else "Problem",
            "Detail": f"{len(conversion_ledger.records)} records loaded",
        },
        {
            "Source": "Showing Conversion",
            "Status": "Connected"
            if not system_errors.get("Showing Conversion Records")
            else "Problem",
            "Detail": f"{len(showing_ledger.appointments)} appointments loaded",
        },
        {
            "Source": "Terms Testing",
            "Status": "Connected"
            if not system_errors.get("Property Terms Testing")
            else "Problem",
            "Detail": f"{len(terms_ledger.experiments)} experiments loaded",
        },
        {
            "Source": "Property Shutdown",
            "Status": "Connected"
            if not system_errors.get("Property Shutdown Records")
            else "Problem",
            "Detail": f"{len(property_control_ledger.events)} events loaded",
        },
    ]
    st.dataframe(
        pd.DataFrame(health_rows),
        use_container_width=True,
        hide_index=True,
    )

with brief_tab:
    st.write("### Copy-ready daily leadership brief")
    brief = daily_brief_text(snapshot, all_items, generated_at=now)
    st.code(brief, language=None)
    st.download_button(
        "Download Daily Brief",
        brief.encode("utf-8"),
        "daily-executive-disposition-brief.txt",
        "text/plain",
    )
    st.caption(
        "Use this brief in the morning meeting. Source records must still be updated inside their operating centers."
    )
