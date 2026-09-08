from __future__ import annotations

from typing import Any

import streamlit as st
from pydantic import ValidationError

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_phone_system import (
    PROFIT_DIAL_CANCELLATION_WARNING,
    OperationalStatus,
    PhoneNumberRecord,
    PhonePlanningDocumentStore,
    PhonePlanningStorageError,
    PhoneProviderPool,
    PhonePurpose,
    PortingStatus,
    RoutingCategory,
    RoutingPlan,
    StaffPhoneAssignment,
    normalize_phone_planning_crm_response,
    offline_provider_catalog,
    summarize_phone_plan,
)
from supabase import create_client

st.set_page_config(page_title="Phone System Setup", page_icon="☎️", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Phone System Setup")
    with st.form("phone_system_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_supabase():
    url = str(st.secrets.get("SUPABASE_URL", "")).strip()
    key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        raise PhonePlanningStorageError("Supabase configuration is required for private persistence")
    return create_client(url, key)


def call_crm(payload: dict[str, Any]) -> dict[str, Any]:
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": payload})
    return normalize_phone_planning_crm_response(response)


require_password()

if st.sidebar.button("Log out", key="phone_system_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("PHONE SYSTEM — PLANNING MODE")
st.error("NO LIVE CALLS OR TEXTS\n\nNO EXTERNAL PHONE ACTIONS")
st.caption("Private planning storage only. Saving records does not contact any phone provider.")
actor_reference = st.sidebar.text_input(
    "Your CommandCore user reference",
    value=str(st.session_state.get("phone_actor_reference", "authenticated-commandcore-user")),
)
st.session_state.phone_actor_reference = actor_reference
store = PhonePlanningDocumentStore(call_crm)
try:
    numbers = store.list_numbers()
    assignments = store.list_assignments()
    routes = store.list_routes()
    provider_pools = store.list_provider_pools()
except (PhonePlanningStorageError, ValidationError):
    st.error("Private phone planning records could not be loaded safely. No provider action was started.")
    st.stop()
summary = summarize_phone_plan(numbers)

metrics = st.columns(5)
metrics[0].metric("Total phone numbers", summary.total_phone_numbers)
metrics[1].metric("Assigned", summary.assigned_numbers)
metrics[2].metric("Unassigned", summary.unassigned_numbers)
metrics[3].metric("Planned for port", summary.numbers_planned_for_port)
metrics[4].metric("Ready for port", summary.numbers_ready_for_port)

status = st.columns(4)
status[0].metric("Provider status", summary.provider_status)
status[1].metric("Live inbound", summary.live_inbound_status)
status[2].metric("Live outbound", summary.live_outbound_status)
status[3].metric("Nevaeh phone connection", summary.nevaeh_phone_connection_status)

number_tab, pool_tab, staff_tab, routing_tab, porting_tab, providers_tab = st.tabs(
    [
        "Phone number inventory",
        "Marketing / dialer pools",
        "Staff / VA assignments",
        "Routing plan",
        "Profit Dial porting",
        "Providers",
    ]
)

with number_tab:
    st.subheader("Business phone number inventory")
    st.caption("Add existing numbers for planning. No number is tested, called, texted, or changed.")
    with st.form("add_phone_number", clear_on_submit=True):
        left, right = st.columns(2)
        phone_number = left.text_input("Phone number")
        current_provider = right.text_input("Current provider", placeholder="REI BlackBook / Profit Dial")
        current_label = left.text_input("Current label / name")
        department = right.text_input(
            "Department / business purpose (optional)", placeholder="UNKNOWN / NEEDS REVIEW"
        )
        purpose = left.selectbox("Line type", [item.value for item in PhonePurpose])
        assigned = right.text_input("Assigned staff member or team")
        operational_status = left.selectbox(
            "Operational status",
            [item.value for item in OperationalStatus],
            index=list(OperationalStatus).index(OperationalStatus.UNKNOWN_NEEDS_REVIEW),
        )
        pool_options = {"Not assigned to a provider pool": ""} | {
            f"{item.provider_name} — {item.label}": item.pool_id for item in provider_pools
        }
        selected_pool = right.selectbox("Provider pool (optional)", list(pool_options))
        inbound = left.checkbox("Inbound enabled — planned")
        outbound = right.checkbox("Outbound enabled — planned")
        texting = left.checkbox("Texting — planned")
        recording = right.checkbox("Call recording — planned")
        voicemail = left.checkbox("Voicemail — planned")
        port_status = right.selectbox("Porting status", [item.value for item in PortingStatus])
        notes = st.text_area("Notes (never store credentials, PINs, or account secrets)")
        if st.form_submit_button("Add to planning inventory", use_container_width=True):
            try:
                record = PhoneNumberRecord(
                    phone_number=phone_number,
                    current_provider=current_provider,
                    current_label=current_label,
                    department_purpose=department,
                    purpose=PhonePurpose(purpose),
                    provider_pool_id=pool_options[selected_pool],
                    assigned_staff_or_team=assigned,
                    operational_status=OperationalStatus(operational_status),
                    inbound_enabled_planned=inbound,
                    outbound_enabled_planned=outbound,
                    texting_planned=texting,
                    call_recording_planned=recording,
                    voicemail_planned=voicemail,
                    porting_status=PortingStatus(port_status),
                    notes=notes,
                    actor_reference=actor_reference,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                store.save_number(record, action="create")
                st.rerun()
    if numbers:
        st.dataframe([item.model_dump(mode="json") for item in numbers], hide_index=True, use_container_width=True)
    else:
        st.info("No phone numbers have been entered. Real numbers are not required during development.")
    if numbers:
        selected_number_id = st.selectbox(
            "Inventory record to update",
            [item.record_id for item in numbers],
            format_func=lambda item_id: next(item.current_label for item in numbers if item.record_id == item_id),
        )
        selected_number = next(item for item in numbers if item.record_id == selected_number_id)
        with st.form("update_phone_number"):
            revised_status = st.selectbox(
                "Updated migration status",
                [item.value for item in PortingStatus],
                index=list(PortingStatus).index(selected_number.porting_status),
            )
            revised_operational_status = st.selectbox(
                "Updated operational status",
                [item.value for item in OperationalStatus],
                index=list(OperationalStatus).index(selected_number.operational_status),
            )
            revised_notes = st.text_area("Updated notes", value=selected_number.notes)
            update_number = st.form_submit_button("Save inventory update")
            deactivate_number = st.form_submit_button("Deactivate inventory record")
        if update_number:
            updated_number = PhoneNumberRecord.model_validate(
                {
                    **selected_number.model_dump(),
                    "porting_status": revised_status,
                    "operational_status": revised_operational_status,
                    "notes": revised_notes,
                    "actor_reference": actor_reference,
                }
            )
            store.save_number(updated_number, action="update")
            st.rerun()
        if deactivate_number:
            store.deactivate_number(selected_number, actor_reference)
            st.rerun()

with pool_tab:
    st.subheader("Provider-level marketing / dialer pools")
    st.caption(
        "Create a planning category such as XLeads without inventing a phone number. "
        "Actual numbers can be associated later."
    )
    with st.form("add_provider_pool", clear_on_submit=True):
        pool_provider = st.text_input("Provider", placeholder="XLeads")
        pool_label = st.text_input("Pool label", placeholder="MARKETING / DIALER POOL")
        pool_status = st.selectbox(
            "Pool operational status",
            [item.value for item in OperationalStatus],
            index=list(OperationalStatus).index(OperationalStatus.UNKNOWN_NEEDS_REVIEW),
        )
        pool_notes = st.text_area("Pool notes (never store credentials, PINs, or account secrets)")
        if st.form_submit_button("Add provider pool", use_container_width=True):
            try:
                pool = PhoneProviderPool(
                    provider_name=pool_provider,
                    label=pool_label,
                    operational_status=OperationalStatus(pool_status),
                    notes=pool_notes,
                    actor_reference=actor_reference,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                store.save_provider_pool(pool, action="create")
                st.rerun()
    if provider_pools:
        st.dataframe(
            [item.model_dump(mode="json") for item in provider_pools],
            hide_index=True,
            use_container_width=True,
        )
        selected_pool_id = st.selectbox(
            "Provider pool to deactivate",
            [item.pool_id for item in provider_pools],
            format_func=lambda item_id: next(
                item.label for item in provider_pools if item.pool_id == item_id
            ),
        )
        if st.button("Deactivate provider pool"):
            selected_provider_pool = next(
                item for item in provider_pools if item.pool_id == selected_pool_id
            )
            store.deactivate_provider_pool(selected_provider_pool, actor_reference)
            st.rerun()
    else:
        st.info("No provider pools have been entered. A pool does not require a phone number.")

with staff_tab:
    st.subheader("Individual staff / VA routing assignments")
    st.caption("Each entry has its own user reference. This does not create provider users, seats, or shared logins.")
    available_numbers = [item.phone_number for item in numbers]
    with st.form("add_staff_assignment", clear_on_submit=True):
        staff_member = st.text_input("Staff member")
        user_reference = st.text_input("CommandCore user reference")
        role = st.text_input("Role")
        shared = st.multiselect("Assigned shared phone numbers", available_numbers)
        primary = st.selectbox("Primary number", ["", *shared])
        backup = st.selectbox("Backup number", ["", *shared])
        ring_priority = st.number_input("Ring priority / order", min_value=1, max_value=100, value=1)
        business_hours = st.text_input("Business-hours availability")
        after_hours = st.text_input("After-hours routing")
        manager = st.text_input("Manager escalation")
        active = st.checkbox("Active", value=True)
        if st.form_submit_button("Add planning assignment", use_container_width=True):
            try:
                assignment = StaffPhoneAssignment(
                    staff_member=staff_member,
                    user_reference=user_reference,
                    role=role,
                    assigned_shared_phone_numbers=tuple(shared),
                    primary_number=primary,
                    backup_number=backup,
                    ring_priority=int(ring_priority),
                    business_hours_availability=business_hours,
                    after_hours_routing=after_hours,
                    manager_escalation=manager,
                    active=active,
                    actor_reference=actor_reference,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                store.save_assignment(assignment, action="create")
                st.rerun()
    if assignments:
        st.dataframe([item.model_dump(mode="json") for item in assignments], hide_index=True, use_container_width=True)
        selected_assignment_id = st.selectbox(
            "Assignment to update",
            [item.assignment_id for item in assignments],
            format_func=lambda item_id: next(item.staff_member for item in assignments if item.assignment_id == item_id),
        )
        selected_assignment = next(item for item in assignments if item.assignment_id == selected_assignment_id)
        with st.form("update_staff_assignment"):
            revised_priority = st.number_input("Updated ring priority", 1, 100, selected_assignment.ring_priority)
            revised_hours = st.text_input("Updated business hours", value=selected_assignment.business_hours_availability)
            revised_after_hours = st.text_input("Updated after-hours routing", value=selected_assignment.after_hours_routing)
            update_assignment = st.form_submit_button("Save assignment update")
            deactivate_assignment = st.form_submit_button("Deactivate assignment")
        if update_assignment:
            updated_assignment = StaffPhoneAssignment.model_validate(
                {
                    **selected_assignment.model_dump(),
                    "ring_priority": revised_priority,
                    "business_hours_availability": revised_hours,
                    "after_hours_routing": revised_after_hours,
                    "actor_reference": actor_reference,
                }
            )
            store.save_assignment(updated_assignment, action="update")
            st.rerun()
        if deactivate_assignment:
            store.deactivate_assignment(selected_assignment, actor_reference)
            st.rerun()

with routing_tab:
    st.subheader("Provider-neutral routing plan")
    st.caption("Nevaeh may eventually read this plan to recommend routing; it cannot route, call, text, or approve.")
    with st.form("add_routing_plan", clear_on_submit=True):
        category = st.selectbox("Routing category", [item.value for item in RoutingCategory])
        primary_team = st.text_input("Primary staff member or team")
        backup_team = st.text_input("Backup staff member or team")
        instructions = st.text_area("Planning instructions")
        approval = st.checkbox("Manager approval required")
        if st.form_submit_button("Add routing plan", use_container_width=True):
            try:
                route = RoutingPlan(
                    category=RoutingCategory(category),
                    primary_staff_or_team=primary_team,
                    backup_staff_or_team=backup_team,
                    instructions=instructions,
                    manager_approval_required=approval,
                    actor_reference=actor_reference,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                store.save_route(route, action="create")
                st.rerun()
    if routes:
        st.dataframe([item.model_dump(mode="json") for item in routes], hide_index=True, use_container_width=True)
        selected_route_id = st.selectbox(
            "Route to update",
            [item.route_id for item in routes],
            format_func=lambda item_id: next(item.category.value for item in routes if item.route_id == item_id),
        )
        selected_route = next(item for item in routes if item.route_id == selected_route_id)
        with st.form("update_routing_plan"):
            revised_primary = st.text_input("Updated primary staff or team", value=selected_route.primary_staff_or_team)
            revised_backup = st.text_input("Updated backup staff or team", value=selected_route.backup_staff_or_team)
            revised_instructions = st.text_area("Updated planning instructions", value=selected_route.instructions)
            update_route = st.form_submit_button("Save routing update")
            deactivate_route = st.form_submit_button("Deactivate route")
        if update_route:
            updated_route = RoutingPlan.model_validate(
                {
                    **selected_route.model_dump(),
                    "primary_staff_or_team": revised_primary,
                    "backup_staff_or_team": revised_backup,
                    "instructions": revised_instructions,
                    "actor_reference": actor_reference,
                }
            )
            store.save_route(updated_route, action="update")
            st.rerun()
        if deactivate_route:
            store.deactivate_route(selected_route, actor_reference)
            st.rerun()

with porting_tab:
    st.warning(PROFIT_DIAL_CANCELLATION_WARNING)
    st.write("Porting tracker statuses:")
    st.write(" • ".join(item.value for item in PortingStatus))
    st.caption("This tracker records plans only. It has no port-request action and makes no provider changes.")
    if numbers:
        st.dataframe(
            [{"Phone number": item.phone_number, "Provider": item.current_provider, "Porting status": item.porting_status.value, "Notes": item.notes} for item in numbers],
            hide_index=True,
            use_container_width=True,
        )

with providers_tab:
    st.subheader("Provider abstraction")
    st.caption("The existing Quo/OpenPhone inbound adapter is retained as one optional adapter. No provider is configured or connected here.")
    st.dataframe(
        [
            {
                "Provider": item.provider.value,
                "Adapter binding": item.adapter_name,
                "Configured": "NO",
                "Inbound live": "NO",
                "Outbound live": "NO",
                "Webhook active": "NO",
            }
            for item in offline_provider_catalog()
        ],
        hide_index=True,
        use_container_width=True,
    )

st.divider()
st.caption("OUTBOUND SMS: 0 · OUTBOUND CALLS: 0 · WEBHOOKS ACTIVATED: 0 · PHONE NUMBERS PORTED: 0 · EXTERNAL SPEND: $0")
