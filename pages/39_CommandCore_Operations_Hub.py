from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_property_source_diagnostics import (
    run_property_source_diagnostic,
    safe_property_diagnostic_failure,
)
from cfh_disposition.commandcore_secretary_orchestrator import (
    CanonicalCommunicationEvent,
    CommunicationChannel,
    CommunicationDirection,
    SecretaryContactContext,
    SecretaryDealContext,
    SecretaryPropertyContext,
    decide_secretary_action,
)
from cfh_disposition.google_property_full_audit import run_full_property_source_audit
from cfh_disposition.google_property_runtime_bridge import GoogleBridgeError
from supabase import create_client

st.set_page_config(page_title="CommandCore Operations", page_icon="🧭", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"
OPERATOR_STATE_BUCKET = "commandcore-operator-state"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Operations")
    st.caption("Private internal access")
    with st.form("commandcore_operations_hub_login"):
        entered_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(entered_password, expected):
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
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in Streamlit Secrets.")
    return create_client(url, key)


def post_commandcore(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        raise RuntimeError("CommandCore services are not configured.")
    req = Request(
        f"{supabase_url}/functions/v1/{function_name}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CommandCore request was rejected ({exc.code}): {detail[:240]}") from exc
    except URLError as exc:
        raise RuntimeError("CommandCore service could not be reached.") from exc
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise RuntimeError("CommandCore did not confirm the request.")
    return parsed


def load_launch_readiness() -> dict[str, Any]:
    """Read the existing launch-readiness auditor without hiding an unhealthy 503 response."""
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        raise RuntimeError("CommandCore services are not configured.")
    req = Request(
        f"{supabase_url}/functions/v1/commandcore-launch-readiness",
        data=b"{}",
        method="POST",
        headers={"Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError as parse_exc:
            raise RuntimeError(f"CommandCore readiness request failed ({exc.code}).") from parse_exc
        if exc.code != 503 or not isinstance(parsed, dict):
            raise RuntimeError(f"CommandCore readiness request failed ({exc.code}).") from exc
    except URLError as exc:
        raise RuntimeError("CommandCore readiness auditor could not be reached.") from exc
    if not isinstance(parsed, dict) or "launch_ready" not in parsed:
        raise RuntimeError("CommandCore readiness auditor returned an invalid response.")
    return parsed


def load_queue_items() -> list[dict[str, Any]]:
    client = get_supabase()
    rows = client.storage.from_(ACTION_BUCKET).list("dispatches") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(ACTION_BUCKET).download(f"dispatches/{name}")
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        for item in parsed.get("items") if isinstance(parsed.get("items"), list) else []:
            if isinstance(item, dict):
                items.append(item)
    return items


def load_operator_states() -> dict[str, dict[str, Any]]:
    client = get_supabase()
    try:
        rows = client.storage.from_(OPERATOR_STATE_BUCKET).list("actions") or []
    except Exception:
        return {}
    states: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(OPERATOR_STATE_BUCKET).download(f"actions/{name}")
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(parsed, dict):
            action_id = str(parsed.get("action_id", "")).strip()
            if action_id:
                states[action_id] = parsed
    return states


def action_id_for(item: dict[str, Any]) -> str:
    return str(item.get("action_id", "") or f"{item.get('dispatch_id', '')}_{item.get('channel_key', '')}").strip()


def load_human_escalations(items: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    result = post_commandcore("commandcore-aging-escalation", {"items": items, "operator_states": states})
    escalations = result.get("escalations") if isinstance(result.get("escalations"), list) else []
    return [item for item in escalations if isinstance(item, dict)]


def load_coverage_alerts() -> list[dict[str, Any]]:
    result = post_commandcore(
        "commandcore-coverage-exception-ledger",
        {"action": "list", "days": 60, "status": "all"},
    )
    raw = result.get("exceptions") if isinstance(result.get("exceptions"), list) else []
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and str(item.get("status", "")).lower() != "resolved"
        and str(item.get("aging_level", "")).lower() in {"overdue", "escalated", "executive"}
    ]


def human_rows(items: list[dict[str, Any]], escalations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("action_id", "")).strip(): item
        for item in escalations
        if str(item.get("action_id", "")).strip()
    }
    rows: list[dict[str, Any]] = []
    for item in items:
        escalation = by_id.get(action_id_for(item), {})
        level = str(escalation.get("escalation_level", "normal")).lower()
        readiness = str(item.get("readiness", "")).upper()
        if level not in {"critical", "overdue"} and readiness not in {"HOLD", "MANUAL", "BLOCKED"}:
            continue
        rows.append(
            {
                "Urgency": level.upper(),
                "Priority": str(item.get("priority", "medium")).upper(),
                "Status": readiness,
                "Property": str(item.get("property_id", "")),
                "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
                "Age Hours": escalation.get("age_hours"),
                "Dispatch": str(item.get("dispatch_id", "")),
                "Action": " • ".join(str(value) for value in item.get("required_actions", []) if value)
                or "Review item",
            }
        )
    rank = {"CRITICAL": 0, "OVERDUE": 1, "NORMAL": 2}
    rows.sort(key=lambda row: (rank.get(str(row["Urgency"]), 9), 0 if row["Priority"] == "HIGH" else 1))
    return rows


def coverage_rows(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "Urgency": str(item.get("aging_level", "")).upper(),
            "Severity": str(item.get("severity", "")).upper(),
            "Owner": str(item.get("owner_name") or item.get("owner_id") or ""),
            "Age Hours": item.get("age_hours"),
            "Dispatch": str(item.get("dispatch_id", "")),
            "Failure": str(item.get("exception_type") or item.get("type") or "coverage_exception")
            .replace("_", " ")
            .title(),
            "Action": str(item.get("recommended_action") or "Review coverage and confirm safe ownership."),
        }
        for item in alerts
    ]
    rank = {"EXECUTIVE": 0, "ESCALATED": 1, "OVERDUE": 2}
    rows.sort(key=lambda row: (rank.get(str(row["Urgency"]), 9), 0 if row["Severity"] == "CRITICAL" else 1))
    return rows


def render_system_readiness(readiness: dict[str, Any] | None, readiness_error: str | None) -> None:
    st.subheader("CommandCore System Readiness")
    if readiness_error:
        st.error(f"System readiness could not be verified: {readiness_error}")
        return
    if readiness is None:
        st.warning("System readiness has not been verified yet.")
        return

    launch_ready = readiness.get("launch_ready") is True
    required_count = int(readiness.get("required_service_count") or 0)
    healthy_count = int(readiness.get("healthy_service_count") or 0)
    failed_count = int(readiness.get("failed_required_count") or 0)
    cutover = readiness.get("crm_cutover") if isinstance(readiness.get("crm_cutover"), dict) else {}
    crm_cutover_ready = cutover.get("crm_cutover_ready") is True
    unsupported = cutover.get("unsupported_migration_entities")
    unsupported_names = [str(name) for name in unsupported] if isinstance(unsupported, list) else []
    source_reconciled = cutover.get("source_crm_data_reconciliation_verified") is True

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Critical Chain", "READY" if launch_ready else "NOT READY")
    r2.metric("Healthy Services", f"{healthy_count}/{required_count}")
    r3.metric("Failed Required", failed_count)
    r4.metric("CRM Cutover", "READY" if crm_cutover_ready else "NOT READY")

    if launch_ready:
        st.success("The required CommandCore operating chain is healthy.")
    else:
        failed_services = readiness.get("failed_required_services")
        failed_names = [str(name) for name in failed_services] if isinstance(failed_services, list) else []
        st.error("CommandCore is not launch-ready. Required service failures need attention before relying on automation.")
        if failed_names:
            st.dataframe(
                [{"Failed Required Service": name} for name in failed_names],
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("#### CRM Replacement / Cutover")
    if crm_cutover_ready:
        st.success("CRM cutover safeguards report ready. Verify the approved cutover plan before discontinuing the old CRM.")
        return

    st.warning(
        "CommandCore can be operationally healthy while CRM cutover is still blocked. "
        "Do not discontinue the outside CRM yet."
    )
    if unsupported_names:
        st.write("**Migration coverage still missing for:** " + ", ".join(unsupported_names))
    if not source_reconciled:
        st.write("**Source CRM reconciliation:** Not yet verified")
    blockers = cutover.get("blockers")
    blocker_names = [str(item) for item in blockers] if isinstance(blockers, list) else []
    if blocker_names:
        with st.expander("CRM cutover blockers", expanded=False):
            for blocker in blocker_names:
                st.write(f"- {blocker}")


require_password()

if st.sidebar.button("Log out", key="commandcore_operations_hub_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Operations")
st.caption(
    "Start with what needs management attention now. System readiness and CRM cutover details remain available below."
)

with st.expander("Secretary Test", expanded=False):
    st.warning("TEST MODE — NOTHING WILL BE SENT")
    st.caption(
        "Evaluate a safe canonical communication example. This panel does not save records, create tasks, or contact anyone."
    )
    secretary_event_id = st.text_input(
        "Communication event reference", value="secretary-safe-test-1"
    )
    secretary_channel = st.selectbox(
        "Communication channel", [item.value for item in CommunicationChannel]
    )
    secretary_direction = st.selectbox(
        "Direction", [item.value for item in CommunicationDirection]
    )
    secretary_message = st.text_area(
        "Safe test message",
        placeholder="Example: I would like to schedule a showing next week.",
    )
    context_left, context_right = st.columns(2)
    secretary_contact_id = context_left.text_input("Matched contact reference (optional)")
    secretary_relationship = context_right.selectbox(
        "Contact relationship", ["Unknown", "Seller", "Buyer", "Investor"]
    )
    secretary_property_id = context_left.text_input("Related property reference (optional)")
    secretary_deal_id = context_right.text_input("Related deal reference (optional)")
    secretary_assigned_worker = st.text_input("Existing assigned worker (optional)")
    if st.button(
        "Evaluate in Test Mode",
        key="commandcore_secretary_test_mode",
        use_container_width=True,
    ):
        if not secretary_message.strip():
            st.error("Enter a safe test message before evaluating it.")
        else:
            test_contacts = (
                SecretaryContactContext(
                    contact_id=secretary_contact_id,
                    relationship=(
                        "" if secretary_relationship == "Unknown" else secretary_relationship
                    ),
                    assigned_worker=secretary_assigned_worker,
                ),
            ) if secretary_contact_id else ()
            test_properties = (
                SecretaryPropertyContext(property_id=secretary_property_id),
            ) if secretary_property_id else ()
            test_deals = (
                SecretaryDealContext(
                    deal_id=secretary_deal_id,
                    contact_id=secretary_contact_id,
                    property_id=secretary_property_id,
                    assigned_worker=secretary_assigned_worker,
                ),
            ) if secretary_deal_id else ()
            secretary_result = decide_secretary_action(
                CanonicalCommunicationEvent(
                    communication_event_id=secretary_event_id,
                    channel=CommunicationChannel(secretary_channel),
                    direction=CommunicationDirection(secretary_direction),
                    message_text=secretary_message,
                    contact_id=secretary_contact_id,
                    property_id=secretary_property_id,
                    deal_id=secretary_deal_id,
                ),
                contacts=test_contacts,
                properties=test_properties,
                deals=test_deals,
            )
            st.markdown("### Secretary Result")
            st.write(
                "**Who this appears to be:** "
                + (secretary_relationship if secretary_contact_id else "Not matched — review needed")
            )
            st.write(
                "**Related deal/property:** "
                + (secretary_result.matched_deal_id or secretary_result.matched_property_id or "Not reliably matched")
            )
            st.write(f"**What they appear to want:** {secretary_result.intent.value}")
            st.write(f"**Urgency:** {secretary_result.urgency.value}")
            st.write(f"**Confidence:** {secretary_result.confidence.value}")
            st.write(f"**Recommended next step:** {secretary_result.suggested_action}")
            st.write(f"**Who should handle it:** {secretary_result.suggested_owner}")
            st.write(
                f"**Approval required:** {'Yes' if secretary_result.approval_required else 'No'}"
            )
            st.write(f"**Why:** {'; '.join(secretary_result.evidence)}")
            st.write(
                "**Draft response, if appropriate:** "
                + (secretary_result.draft_response or "No draft — human review is required.")
            )
            st.caption("No external action, record write, message, call, approval, or task was started.")

with st.expander("Property Source Diagnostics", expanded=False):
    st.caption(
        "Owner/admin diagnostic only. Reads up to three properties from Decatur/Quincy without changing Google or CommandCore."
    )
    if st.button(
        "Run 3-Property Read-Only Test",
        key="commandcore_property_source_diagnostic",
        use_container_width=True,
    ):
        try:
            diagnostic = run_property_source_diagnostic(st.secrets)
        except GoogleBridgeError as error:
            failure = safe_property_diagnostic_failure(error)
            st.error("Live Google connection: FAIL")
            st.write(f"**Failure category:** {failure.category.value}")
            st.write(f"**Safe explanation:** {failure.explanation}")
            st.caption("Google writes: 0 · CommandCore records created: 0")
        else:
            st.success("Live Google connection: PASS")
            status_left, status_middle, status_right = st.columns(3)
            status_left.metric("Read-only scope", "PASS")
            status_middle.metric("Rows read", diagnostic.rows_read)
            status_right.metric("Rows written", diagnostic.google_writes)
            st.dataframe(
                [
                    {
                        "Property address": preview.property_address,
                        "Source tab": preview.worksheet_or_tab,
                        "Canonical identity": preview.canonical_identity or "Needs review",
                        "Normalization result": preview.normalization_result,
                        "Duplicate check": preview.duplicate_result,
                        "Sales price": preview.sales_price,
                        "Down payment": preview.down_payment,
                        "Monthly payment": preview.total_monthly_payment,
                        "Last update": preview.last_update or "Not provided",
                    }
                    for preview in diagnostic.previews
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "CommandCore records created: 0 · Google writes: 0 · Sensitive data exposed: No"
            )
    st.divider()
    if st.button(
        "Run Full Property Source Audit",
        key="commandcore_full_property_source_audit",
        use_container_width=True,
    ):
        try:
            full_audit = run_full_property_source_audit(st.secrets)
        except GoogleBridgeError as error:
            failure = safe_property_diagnostic_failure(error)
            st.error("Full Google property source: FAIL")
            st.write(f"**Failure category:** {failure.category.value}")
            st.write(f"**Safe explanation:** {failure.explanation}")
            st.caption("Google writes: 0 · CommandCore records created: 0")
        else:
            st.success("Full Google property source: PASS")
            first_row = st.columns(4)
            first_row[0].metric("Worksheets discovered", full_audit.worksheets_discovered)
            first_row[1].metric("Worksheets processed", full_audit.worksheets_processed)
            first_row[2].metric("Physical rows inspected", full_audit.total_physical_rows_inspected)
            first_row[3].metric("Source property rows detected", full_audit.source_property_rows_detected)
            second_row = st.columns(4)
            second_row[0].metric("Fully normalized", full_audit.fully_normalized_properties)
            second_row[1].metric("Needs review", full_audit.properties_needing_review)
            second_row[2].metric("True malformed rows", full_audit.true_malformed_property_rows)
            second_row[3].metric("Non-property / header / blank", full_audit.non_property_header_blank_rows)
            third_row = st.columns(4)
            third_row[0].metric("Duplicate candidates", full_audit.duplicate_candidates)
            third_row[1].metric("Sold", full_audit.sold_count)
            third_row[2].metric("Do not sell", full_audit.do_not_sell_count)
            third_row[3].metric("Active / available", full_audit.active_available_count)
            st.markdown("#### Properties by source tab")
            st.dataframe(
                [item.model_dump() for item in full_audit.properties_by_source_tab],
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("#### Safe sample properties")
            safe_rows = [
                {
                    "Property address": preview.property_address,
                    "Source tab": preview.worksheet_or_tab,
                    "Canonical identity": preview.canonical_identity or "Needs review",
                    "Status": preview.status,
                    "Normalization result": preview.normalization_result,
                    "Duplicate check": preview.duplicate_result,
                    "Sales price": preview.sales_price,
                    "Down payment": preview.down_payment,
                    "Monthly payment": preview.total_monthly_payment,
                    "Last update": preview.last_update or "Not provided",
                }
                for preview in full_audit.safe_previews
            ]
            st.dataframe(safe_rows[:5], use_container_width=True, hide_index=True)
            if len(safe_rows) > 5:
                with st.expander("Inspect additional safe previews", expanded=False):
                    st.dataframe(safe_rows[5:25], use_container_width=True, hide_index=True)
                    if len(safe_rows) > 25:
                        st.caption(
                            "Additional properties are included in the summary but are not displayed here."
                        )
            if full_audit.needs_review_previews:
                with st.expander("Properties needing review", expanded=False):
                    st.dataframe(
                        [
                            {
                                "Property address": item.property_address,
                                "Source tab": item.source_tab,
                                "Source identity": item.source_identity,
                                "Source row": item.source_row_number,
                                "Status": item.status,
                                "Sales price": item.sales_price,
                                "Down payment": item.down_payment,
                                "Monthly payment": item.total_monthly_payment,
                                "Last update": item.last_update or "Needs review",
                                "Review reason": "; ".join(item.reasons),
                                "Possible duplicate": "Yes" if item.possible_duplicate else "No",
                            }
                            for item in full_audit.needs_review_previews[:25]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
            st.caption(
                "CommandCore records created: 0 · Google writes: 0 · Sensitive data exposed: No"
            )

try:
    queue_items = load_queue_items()
    operator_states = load_operator_states()
    human_escalations = load_human_escalations(queue_items, operator_states)
    coverage_alerts = load_coverage_alerts()
except Exception as exc:
    st.error(f"CommandCore operations data could not be loaded: {exc}")
    st.stop()

human = human_rows(queue_items, human_escalations)
coverage = coverage_rows(coverage_alerts)

human_critical = sum(row["Urgency"] == "CRITICAL" for row in human)
coverage_executive = sum(row["Urgency"] == "EXECUTIVE" for row in coverage)
coverage_escalated = sum(row["Urgency"] == "ESCALATED" for row in coverage)

st.subheader("Needs Management Attention")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Human Critical", human_critical)
m2.metric("Human Needs Attention", len(human))
m3.metric("Coverage Executive", coverage_executive)
m4.metric("Coverage Escalated", coverage_escalated)
m5.metric("Total Management Alerts", len(human) + len(coverage))

if coverage_executive:
    st.error(f"{coverage_executive} coverage issue(s) require executive attention before normal queue work.")
elif human_critical or coverage_escalated:
    st.warning("Critical or escalated operational work needs management review now.")
else:
    st.success("No executive-level operations alert is currently present.")

st.subheader("Handle These First")
combined: list[dict[str, Any]] = []
for row in coverage:
    urgency_rank = {"EXECUTIVE": 0, "ESCALATED": 1, "OVERDUE": 3}.get(str(row["Urgency"]), 9)
    combined.append({"rank": urgency_rank, "kind": "Coverage", **row})
for row in human:
    urgency_rank = {"CRITICAL": 2, "OVERDUE": 4, "NORMAL": 6}.get(str(row["Urgency"]), 9)
    combined.append({"rank": urgency_rank, "kind": "Human Work", **row})
combined.sort(key=lambda item: int(item.get("rank", 9)))

if not combined:
    with st.container(border=True):
        st.markdown("### Management queue is clear")
        st.write("No escalated human-work or aged coverage issue needs management attention right now.")
        left_action, right_action = st.columns(2)
        if left_action.button("Review Owner Approvals", type="primary", use_container_width=True):
            st.switch_page("pages/48_CommandCore_Owner_Approvals.py")
        if right_action.button("Review My Work", use_container_width=True):
            st.switch_page("pages/35_CommandCore_My_Work.py")
else:
    for item in combined[:10]:
        title = f"{item.get('Urgency', '')} — {item.get('kind', '')} — {item.get('Property') or item.get('Owner') or 'Operational item'}"
        with st.expander(title, expanded=int(item.get("rank", 9)) <= 2):
            if item.get("Dispatch"):
                st.write(f"**Dispatch:** {item['Dispatch']}")
            if item.get("Age Hours") is not None:
                st.write(f"**Age:** {item['Age Hours']} hours")
            if item.get("Failure"):
                st.write(f"**What failed:** {item['Failure']}")
            st.write(f"**Do this next:** {item.get('Action') or 'Review the item.'}")

with st.expander("More alert detail", expanded=False):
    left, right = st.columns(2)
    with left:
        st.subheader("Human Work Escalations")
        if human:
            st.dataframe(human, use_container_width=True, hide_index=True)
        else:
            st.success("No human-work items currently need escalated management attention.")

    with right:
        st.subheader("Coverage Management Alerts")
        if coverage:
            st.dataframe(coverage, use_container_width=True, hide_index=True)
        else:
            st.success("No aged coverage failures currently need management attention.")

readiness: dict[str, Any] | None = None
readiness_error: str | None = None
try:
    readiness = load_launch_readiness()
except Exception as exc:
    readiness_error = str(exc)

with st.expander("System readiness & CRM cutover", expanded=False):
    st.caption("Technical readiness stays available for management without taking over the daily operations view.")
    render_system_readiness(readiness, readiness_error)

st.divider()
st.caption(
    "Read-only management visibility. This screen cannot change assignments, approvals, consent, readiness, budgets, "
    "legal terms, payments, communications, or external execution. Use the dedicated CommandCore work and coverage "
    "screens for permitted internal follow-up actions."
)
