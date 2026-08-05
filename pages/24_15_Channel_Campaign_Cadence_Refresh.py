from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from cfh_disposition.analytics import AnalyticsError, ClickAnalyticsStore
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.automatic_launch import (
    AutomationDispatchSettings,
    LaunchAction,
)
from cfh_disposition.campaign_cadence import (
    CLOSED_TASK_STATUSES,
    OPEN_TASK_STATUSES,
    CadencePriority,
    CampaignCadenceError,
    CampaignCadenceStore,
    ChannelCadencePolicy,
    RefreshTaskStatus,
    approve_refresh_task,
    build_cadence_queue,
    build_refresh_materials,
    build_refresh_payload,
    cadence_snapshot,
    create_refresh_batch,
    dispatch_refresh_payload,
    ensure_all_policies,
    mark_refresh_dispatched,
    policy_for_channel,
    policy_rows,
    queue_rows,
    task_rows,
    update_refresh_task,
    upsert_policy,
)
from cfh_disposition.campaign_launch import (
    CampaignLaunchStore,
    LaunchStatus,
    LaunchStoreError,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.channels import CHANNELS, CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionStore,
)
from cfh_disposition.models import PropertyStatus
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="15-Channel Campaign Cadence & Refresh",
    page_icon="🔄",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("15-Channel Campaign Cadence & Refresh Center")
    st.caption("Private internal access")
    with st.form("campaign_cadence_login"):
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


def save_ledger(store: CampaignCadenceStore, ledger) -> None:
    store.save(ledger)
    st.session_state.campaign_cadence_refresh = True


def task_label(task) -> str:
    return (
        f"{task.priority.value} — {task.status.value} — "
        f"{task.channel_name} — {task.property_address}"
    )


def queue_label(item) -> str:
    return (
        f"{item.priority.value} — {item.channel_name} — "
        f"{item.property_address}"
    )


def sync_launch_status(
    launch_store: CampaignLaunchStore | None,
    task,
    status: LaunchStatus,
    *,
    actor: str,
    notes: str,
) -> None:
    if launch_store is None:
        return
    state = launch_store.load(task.property_id, "owner_finance_homes")
    state = state or new_launch_state(task.property_id, "owner_finance_homes")
    state = set_channel_status(
        state,
        task.channel_key,
        status,
        updated_by=actor,
        notes=notes,
    )
    launch_store.save(state)


require_password()
st.title("15-Channel Campaign Cadence & Refresh Center")
st.caption(
    "Keeps every active property current across all 15 marketing lanes, identifies stale or missing placements, "
    "and creates controlled refresh work without pretending an external post is live."
)
st.warning(
    "Cadence days are internal Credit Friendly Homes operating rules—not platform policies. "
    "The system does not change ad budgets, targeting, property terms, or external post status automatically."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
    cadence_store = CampaignCadenceStore(st.secrets)
    cadence_ledger = cadence_store.load()
except (StorageError, CampaignCadenceError) as exc:
    st.error(f"Campaign Cadence Center is safety-locked: {exc}")
    st.stop()

click_events = []
try:
    click_events = ClickAnalyticsStore(st.secrets).list_recent(90)
except AnalyticsError as exc:
    st.warning(f"Tracked-click history is unavailable: {exc}")

attribution_events = []
try:
    attribution_events = DwelyxAttributionStore(st.secrets).list_events(limit=10000)
except DwelyxAttributionError as exc:
    st.warning(f"Dwelyx result events are unavailable: {exc}")

launch_store = None
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
    st.warning(f"Campaign launch records are unavailable: {exc}")
    launch_store = None
    launch_states = {}

cadence_ledger = ensure_all_policies(cadence_ledger)
queue = build_cadence_queue(
    properties,
    ledger=cadence_ledger,
    launch_states=launch_states,
    click_events=click_events,
    attribution_events=attribution_events,
)
snapshot = cadence_snapshot(queue, cadence_ledger)
properties_by_id = {str(item.property_id): item for item in properties}
dwelyx_url = dwelyx_base_url(st.secrets)
dispatch_settings = AutomationDispatchSettings.from_mapping(st.secrets)

metrics = st.columns(7)
metrics[0].metric("Active Channel Lanes", snapshot.total_active_lanes)
metrics[1].metric("Blocked", snapshot.blocked)
metrics[2].metric("Overdue", snapshot.overdue)
metrics[3].metric("Due Now", snapshot.due_now)
metrics[4].metric("Due Soon", snapshot.due_soon)
metrics[5].metric("Open Refresh Tasks", snapshot.open_tasks)
metrics[6].metric("Current Coverage", f"{snapshot.coverage_rate:.1%}")

if not properties:
    st.info("Add and save a property before creating channel cadence work.")
    st.stop()

queue_tab, workbench_tab, matrix_tab, rules_tab, history_tab = st.tabs(
    [
        "Daily Refresh Queue",
        "Refresh Workbench",
        "15-Channel Matrix",
        "Cadence Rules",
        "Refresh History",
    ]
)

with queue_tab:
    st.write("### Marketing lanes requiring action")
    active_items = [item for item in queue if item.priority != CadencePriority.INACTIVE]
    filter_columns = st.columns(3)
    selected_priorities = filter_columns[0].multiselect(
        "Priority",
        list(CadencePriority),
        default=[
            CadencePriority.BLOCKED,
            CadencePriority.OVERDUE,
            CadencePriority.DUE_NOW,
            CadencePriority.DUE_SOON,
        ],
        format_func=lambda value: value.value,
    )
    property_names = sorted({item.property_address for item in active_items})
    selected_properties = filter_columns[1].multiselect(
        "Properties",
        property_names,
        default=property_names,
    )
    selected_channels = filter_columns[2].multiselect(
        "Channels",
        [channel.key for channel in CHANNELS],
        default=[channel.key for channel in CHANNELS],
        format_func=lambda key: CHANNELS_BY_KEY[key].name,
    )

    filtered = [
        item
        for item in active_items
        if item.priority in selected_priorities
        and item.property_address in selected_properties
        and item.channel_key in selected_channels
    ]
    if not filtered:
        st.success("No channel lanes match the selected action filters.")
    else:
        frame = pd.DataFrame(queue_rows(filtered))
        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
            height=min(760, max(250, len(frame) * 36 + 45)),
        )
        st.download_button(
            "Download Daily Refresh Queue",
            frame.to_csv(index=False).encode("utf-8"),
            "15-channel-campaign-refresh-queue.csv",
            "text/csv",
        )

        selectable = [
            item
            for item in filtered
            if not item.open_task_id
            and item.action.value not in {"Protect Signed Contract", "Keep Current", "No Active Marketing"}
        ]
        options = {queue_label(item): item for item in selectable}
        selected_task_labels = st.multiselect(
            "Create refresh tasks for",
            list(options),
            default=list(options),
        )
        requested_by = st.text_input(
            "Batch created by",
            value="Sabrina",
            key="cadence_batch_requested_by",
        )
        if st.button(
            "Create Selected Refresh Tasks",
            type="primary",
            disabled=not selected_task_labels,
        ):
            try:
                cadence_ledger, created = create_refresh_batch(
                    cadence_ledger,
                    [options[label] for label in selected_task_labels],
                    requested_by=requested_by,
                )
                save_ledger(cadence_store, cadence_ledger)
                st.success(f"Created {len(created)} refresh task(s).")
                st.rerun()
            except CampaignCadenceError as exc:
                st.error(str(exc))

with workbench_tab:
    st.write("### Complete one approved channel refresh")
    open_tasks = [task for task in cadence_ledger.tasks if task.status in OPEN_TASK_STATUSES]
    if not open_tasks:
        st.info("No open refresh tasks. Create due work from the Daily Refresh Queue.")
    else:
        task_options = {task_label(task): task for task in open_tasks}
        selected_task_label = st.selectbox(
            "Refresh task",
            list(task_options),
            key="campaign_cadence_task",
        )
        selected_task = task_options[selected_task_label]
        property_record = properties_by_id.get(selected_task.property_id)
        if property_record is None:
            st.error("The property connected to this refresh task could not be found.")
        else:
            detail = st.columns(6)
            detail[0].metric("Priority", selected_task.priority.value)
            detail[1].metric("Status", selected_task.status.value)
            detail[2].metric("Channel", selected_task.channel_name)
            detail[3].metric("Owner", selected_task.owner)
            detail[4].metric(
                "Approval",
                "Required" if selected_task.manager_approval_required else "Operator",
            )
            detail[5].metric(
                "Due",
                selected_task.due_at.astimezone().strftime("%m/%d %I:%M %p"),
            )
            st.info(selected_task.reason)
            st.write("**Required work**")
            st.write(selected_task.instruction)

            materials = None
            try:
                materials = build_refresh_materials(
                    selected_task,
                    property_record,
                    dwelyx_url,
                )
                st.write("### Current fact-safe channel package")
                st.code(materials.copy)
                if selected_task.channel_key != "marketplace":
                    st.write("**Tracked Dwelyx link**")
                    st.code(materials.tracked_link)
                if materials.requires_manual_final_post:
                    st.warning(
                        "This platform requires a final human post or update. "
                        "Do not mark Confirmed until the team verifies the live placement."
                    )
                elif materials.launch_action == LaunchAction.AUTO_PUBLISH:
                    st.info(
                        "This channel can be delivered to the connected publishing workflow after approval. "
                        "Webhook acceptance records Dispatched—not Confirmed."
                    )
            except Exception as exc:
                st.error(f"The current refresh package could not be generated: {exc}")

            if selected_task.manager_approval_required and not selected_task.approved_at:
                with st.form("approve_campaign_refresh"):
                    approved_by = st.text_input("Approved by", value="Sabrina")
                    approve_phrase = st.text_input('Type "APPROVE" to authorize this refresh')
                    approve = st.form_submit_button(
                        "Approve Current Refresh Package",
                        type="primary",
                    )
                if approve:
                    if approve_phrase.strip().upper() != "APPROVE":
                        st.error('Type "APPROVE" exactly.')
                    else:
                        try:
                            cadence_ledger = approve_refresh_task(
                                cadence_ledger,
                                property_record,
                                task_id=selected_task.task_id,
                                approved_by=approved_by,
                            )
                            save_ledger(cadence_store, cadence_ledger)
                            st.success("Refresh package approved.")
                            st.rerun()
                        except CampaignCadenceError as exc:
                            st.error(str(exc))
            elif selected_task.status in {
                RefreshTaskStatus.READY,
                RefreshTaskStatus.FAILED,
            }:
                if st.button("Start Operator Refresh", type="primary"):
                    try:
                        cadence_ledger = update_refresh_task(
                            cadence_ledger,
                            task_id=selected_task.task_id,
                            status=RefreshTaskStatus.IN_PROGRESS,
                            actor=selected_task.owner,
                            notes="Operator started the current refresh package.",
                        )
                        save_ledger(cadence_store, cadence_ledger)
                        st.rerun()
                    except CampaignCadenceError as exc:
                        st.error(str(exc))

            if (
                materials is not None
                and materials.launch_action == LaunchAction.AUTO_PUBLISH
                and selected_task.status in {
                    RefreshTaskStatus.APPROVED,
                    RefreshTaskStatus.IN_PROGRESS,
                }
            ):
                if dispatch_settings.configured:
                    dispatch_by = st.text_input(
                        "Dispatch requested by",
                        value=selected_task.approved_by or selected_task.owner,
                        key=f"cadence_dispatch_by_{selected_task.task_id}",
                    )
                    if st.button(
                        "Send This Channel Refresh to Publishing Workflow",
                        type="primary",
                    ):
                        try:
                            payload = build_refresh_payload(
                                selected_task,
                                property_record,
                                materials,
                                requested_by=dispatch_by,
                            )
                            receipt = dispatch_refresh_payload(payload, dispatch_settings)
                            cadence_ledger = mark_refresh_dispatched(
                                cadence_ledger,
                                task_id=selected_task.task_id,
                                actor=dispatch_by,
                                receipt=receipt,
                            )
                            save_ledger(cadence_store, cadence_ledger)
                            sync_launch_status(
                                launch_store,
                                selected_task,
                                LaunchStatus.SCHEDULED,
                                actor=dispatch_by,
                                notes="Cadence refresh accepted by the publishing workflow; final live confirmation remains required.",
                            )
                            st.success("Publishing workflow accepted the refresh request.")
                            st.rerun()
                        except (CampaignCadenceError, LaunchStoreError) as exc:
                            st.error(str(exc))
                else:
                    st.info(
                        "The publishing webhook is not connected. Use the copy-ready package and update this task manually."
                    )

            if selected_task.status not in CLOSED_TASK_STATUSES:
                st.write("### Record the real result")
                result_columns = st.columns(2)
                result_status = result_columns[0].selectbox(
                    "Task result",
                    [
                        RefreshTaskStatus.IN_PROGRESS,
                        RefreshTaskStatus.CONFIRMED,
                        RefreshTaskStatus.FAILED,
                        RefreshTaskStatus.SKIPPED,
                        RefreshTaskStatus.CANCELLED,
                    ],
                    format_func=lambda value: value.value,
                    key=f"cadence_result_{selected_task.task_id}",
                )
                result_actor = result_columns[1].text_input(
                    "Recorded by",
                    value=selected_task.owner,
                    key=f"cadence_actor_{selected_task.task_id}",
                )
                result_notes = st.text_area(
                    "Confirmation, posting location, ad ID, failure, or skip notes",
                    key=f"cadence_notes_{selected_task.task_id}",
                )
                confirmation_phrase = st.text_input(
                    'Type "CONFIRM" only when the external placement is verified',
                    key=f"cadence_confirm_{selected_task.task_id}",
                )
                if st.button("Save Refresh Result", type="primary"):
                    if (
                        result_status == RefreshTaskStatus.CONFIRMED
                        and confirmation_phrase.strip().upper() != "CONFIRM"
                    ):
                        st.error('Type "CONFIRM" exactly before recording a live refresh.')
                    else:
                        try:
                            cadence_ledger = update_refresh_task(
                                cadence_ledger,
                                task_id=selected_task.task_id,
                                status=result_status,
                                actor=result_actor,
                                notes=result_notes,
                            )
                            save_ledger(cadence_store, cadence_ledger)
                            if result_status == RefreshTaskStatus.CONFIRMED:
                                sync_launch_status(
                                    launch_store,
                                    selected_task,
                                    LaunchStatus.POSTED,
                                    actor=result_actor,
                                    notes=result_notes or "Cadence refresh confirmed live by the operator.",
                                )
                            elif result_status == RefreshTaskStatus.FAILED:
                                sync_launch_status(
                                    launch_store,
                                    selected_task,
                                    LaunchStatus.FAILED,
                                    actor=result_actor,
                                    notes=result_notes or "Cadence refresh failed and needs repair.",
                                )
                            st.success(f"Refresh task marked {result_status.value}.")
                            st.rerun()
                        except (CampaignCadenceError, LaunchStoreError) as exc:
                            st.error(str(exc))

with matrix_tab:
    st.write("### Every active property across every registered marketing channel")
    matrix_items = [item for item in queue if item.priority != CadencePriority.INACTIVE]
    matrix_frame = pd.DataFrame(queue_rows(matrix_items))
    if matrix_frame.empty:
        st.info("No active property/channel lanes are available.")
    else:
        st.dataframe(
            matrix_frame,
            use_container_width=True,
            hide_index=True,
            height=min(850, max(320, len(matrix_frame) * 35 + 45)),
        )
        coverage = pd.pivot_table(
            matrix_frame,
            index="Property",
            columns="Priority",
            values="Channel",
            aggfunc="count",
            fill_value=0,
        )
        st.write("### Property cadence summary")
        st.dataframe(coverage, use_container_width=True)

with rules_tab:
    st.write("### Internal cadence rules for all 15 channels")
    st.caption(
        "These values control the team's review and refresh schedule only. They do not override platform rules, "
        "Facebook Group cooldowns, Marketplace limits, consent cooldowns, or manager approval requirements."
    )
    rules_frame = pd.DataFrame(policy_rows(cadence_ledger.policies))
    st.dataframe(
        rules_frame,
        use_container_width=True,
        hide_index=True,
        height=max(420, len(CHANNELS) * 35 + 45),
    )

    selected_channel_key = st.selectbox(
        "Edit channel rule",
        [channel.key for channel in CHANNELS],
        format_func=lambda key: CHANNELS_BY_KEY[key].name,
    )
    selected_policy = policy_for_channel(cadence_ledger, selected_channel_key)
    with st.form("edit_cadence_rule"):
        rule_columns = st.columns(4)
        enabled = rule_columns[0].checkbox("Enabled", value=selected_policy.enabled)
        cadence_days = rule_columns[1].number_input(
            "Cadence days",
            min_value=1,
            max_value=365,
            value=selected_policy.cadence_days,
            step=1,
        )
        warning_days = rule_columns[2].number_input(
            "Warning days",
            min_value=0,
            max_value=max(0, int(cadence_days) - 1),
            value=min(selected_policy.warning_days, max(0, int(cadence_days) - 1)),
            step=1,
        )
        owner = rule_columns[3].text_input(
            "Default owner",
            value=selected_policy.default_owner,
        )
        notes = st.text_area("Internal notes", value=selected_policy.notes)
        save_rule = st.form_submit_button("Save Cadence Rule", type="primary")
    if save_rule:
        try:
            cadence_ledger = upsert_policy(
                cadence_ledger,
                ChannelCadencePolicy(
                    channel_key=selected_channel_key,
                    cadence_days=int(cadence_days),
                    warning_days=int(warning_days),
                    enabled=enabled,
                    default_owner=owner,
                    notes=notes,
                    updated_at=datetime.now().astimezone(),
                ),
            )
            save_ledger(cadence_store, cadence_ledger)
            st.success("Cadence rule saved.")
            st.rerun()
        except CampaignCadenceError as exc:
            st.error(str(exc))
        except ValueError as exc:
            st.error(str(exc))

with history_tab:
    st.write("### Refresh task history")
    if not cadence_ledger.tasks:
        st.info("No refresh tasks have been created yet.")
    else:
        history_frame = pd.DataFrame(task_rows(cadence_ledger.tasks))
        st.dataframe(
            history_frame,
            use_container_width=True,
            hide_index=True,
            height=min(850, max(280, len(history_frame) * 36 + 45)),
        )
        st.download_button(
            "Download Refresh History",
            history_frame.to_csv(index=False).encode("utf-8"),
            "15-channel-campaign-refresh-history.csv",
            "text/csv",
        )
