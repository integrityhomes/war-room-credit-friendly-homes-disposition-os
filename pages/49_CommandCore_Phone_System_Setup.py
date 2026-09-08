from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_phone_system import (
    PROFIT_DIAL_CANCELLATION_WARNING,
    PhoneNumberRecord,
    PhonePurpose,
    PortingStatus,
    RoutingCategory,
    RoutingPlan,
    StaffPhoneAssignment,
    offline_provider_catalog,
    summarize_phone_plan,
)

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


require_password()

if st.sidebar.button("Log out", key="phone_system_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("PHONE SYSTEM — PLANNING MODE")
st.error("NO LIVE CALLS OR TEXTS\n\nNO EXTERNAL PHONE ACTIONS")
st.caption("Offline setup only. Entries remain in this browser session and do not contact any provider.")

number_rows = st.session_state.setdefault("phone_setup_numbers", [])
assignment_rows = st.session_state.setdefault("phone_setup_assignments", [])
route_rows = st.session_state.setdefault("phone_setup_routes", [])
numbers = tuple(PhoneNumberRecord.model_validate(item) for item in number_rows)
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

number_tab, staff_tab, routing_tab, porting_tab, providers_tab = st.tabs(
    ["Phone number inventory", "Staff / VA assignments", "Routing plan", "Profit Dial porting", "Providers"]
)

with number_tab:
    st.subheader("Business phone number inventory")
    st.caption("Add existing numbers for planning. No number is tested, called, texted, or changed.")
    with st.form("add_phone_number", clear_on_submit=True):
        left, right = st.columns(2)
        phone_number = left.text_input("Phone number")
        current_provider = right.text_input("Current provider", placeholder="REI BlackBook / Profit Dial")
        current_label = left.text_input("Current label / name")
        department = right.text_input("Department / purpose")
        purpose = left.selectbox("Line type", [item.value for item in PhonePurpose])
        assigned = right.text_input("Assigned staff member or team")
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
                    assigned_staff_or_team=assigned,
                    inbound_enabled_planned=inbound,
                    outbound_enabled_planned=outbound,
                    texting_planned=texting,
                    call_recording_planned=recording,
                    voicemail_planned=voicemail,
                    porting_status=PortingStatus(port_status),
                    notes=notes,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                number_rows.append(record.model_dump(mode="json"))
                st.rerun()
    if numbers:
        st.dataframe([item.model_dump(mode="json") for item in numbers], hide_index=True, use_container_width=True)
    else:
        st.info("No phone numbers have been entered. Real numbers are not required during development.")

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
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                assignment_rows.append(assignment.model_dump(mode="json"))
                st.rerun()
    if assignment_rows:
        st.dataframe(assignment_rows, hide_index=True, use_container_width=True)

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
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                route_rows.append(route.model_dump(mode="json"))
                st.rerun()
    if route_rows:
        st.dataframe(route_rows, hide_index=True, use_container_width=True)

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
