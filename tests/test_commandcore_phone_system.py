from pathlib import Path

import pytest
from pydantic import ValidationError

from cfh_disposition.commandcore_phone_system import (
    PROFIT_DIAL_CANCELLATION_WARNING,
    PhoneNumberRecord,
    PhoneProvider,
    PhonePurpose,
    PhoneSystemPlan,
    PortingStatus,
    ProviderConfiguration,
    RoutingCategory,
    RoutingPlan,
    StaffPhoneAssignment,
    offline_provider_catalog,
    summarize_phone_plan,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "pages/49_CommandCore_Phone_System_Setup.py").read_text(encoding="utf-8")
QUO_ADAPTER = (ROOT / "supabase/functions/commandcore-quo-openphone-adapter/index.ts").read_text(encoding="utf-8")


def fictional_number(**overrides: object) -> PhoneNumberRecord:
    values: dict[str, object] = {
        "phone_number": "+1 202-555-0142",
        "current_provider": "Fictional Profit Dial",
        "current_label": "Example main line",
        "department_purpose": "Fictional general inquiries",
        "purpose": PhonePurpose.MAIN_LINE,
    }
    values.update(overrides)
    return PhoneNumberRecord(**values)


def test_phone_inventory_and_dashboard_use_fictional_fixture_only() -> None:
    assigned = fictional_number(assigned_staff_or_team="Example Team", porting_status=PortingStatus.READY_TO_PORT)
    unassigned = fictional_number(phone_number="+1 202-555-0179")
    summary = summarize_phone_plan((assigned, unassigned))
    assert assigned.phone_number == "+12025550142"
    assert summary.total_phone_numbers == 2
    assert summary.assigned_numbers == 1
    assert summary.unassigned_numbers == 1
    assert summary.numbers_planned_for_port == 1
    assert summary.numbers_ready_for_port == 1


def test_staff_assignments_use_separate_user_references_and_known_numbers() -> None:
    assignment = StaffPhoneAssignment(
        staff_member="Fictional VA",
        user_reference="user-example-1",
        role="VA",
        assigned_shared_phone_numbers=("+12025550142",),
        primary_number="+12025550142",
        business_hours_availability="Weekdays, example schedule",
    )
    assert assignment.user_reference == "user-example-1"
    with pytest.raises(ValidationError, match="Primary number"):
        assignment.model_copy(update={"primary_number": "+12025550179"}).model_validate(
            assignment.model_copy(update={"primary_number": "+12025550179"}).model_dump()
        )


@pytest.mark.parametrize("category", [RoutingCategory.STOP_CONSENT, RoutingCategory.MONEY_LEGAL_HIGH_RISK])
def test_high_risk_routes_force_manager_approval_and_nevaeh_is_recommend_only(category: RoutingCategory) -> None:
    route = RoutingPlan(category=category, primary_staff_or_team="Fictional Manager")
    assert route.manager_approval_required is True
    assert route.nevaeh_may_recommend_only is True
    with pytest.raises(ValidationError, match="only recommend"):
        RoutingPlan(category=category, primary_staff_or_team="Fictional Manager", nevaeh_may_recommend_only=False)


def test_provider_layer_retains_existing_adapter_without_connecting_it() -> None:
    providers = offline_provider_catalog()
    quo = next(item for item in providers if item.provider is PhoneProvider.QUO_OPENPHONE)
    assert quo.adapter_name == "commandcore-quo-openphone-adapter"
    assert quo.configured is False
    assert quo.inbound_live is False
    assert quo.outbound_live is False
    assert quo.webhook_active is False


@pytest.mark.parametrize(
    "unsafe",
    [
        {"inbound_live": True},
        {"outbound_live": True},
        {"webhook_active": True},
        {"account_created_by_commandcore": True},
        {"paid_action_started": True},
    ],
)
def test_no_external_provider_or_paid_action_can_be_enabled(unsafe: dict[str, bool]) -> None:
    with pytest.raises(ValidationError, match="offline"):
        ProviderConfiguration(provider=PhoneProvider.FUTURE, adapter_name="example", **unsafe)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"planning_mode": False},
        {"external_actions_allowed": True},
        {"runtime_flag_enabled": True},
        {"port_requests_started": 1},
        {"outbound_sms_sent": 1},
        {"outbound_calls_made": 1},
        {"external_spend_usd": 1},
    ],
)
def test_plan_blocks_live_mode_sms_calls_port_requests_and_spend(unsafe: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="planning mode|live, paid, or porting"):
        PhoneSystemPlan(**unsafe)


def test_setup_page_has_no_provider_execution_or_webhook_controls() -> None:
    for marker in (
        "PHONE SYSTEM — PLANNING MODE",
        "NO LIVE CALLS OR TEXTS",
        "NO EXTERNAL PHONE ACTIONS",
        "st.warning(PROFIT_DIAL_CANCELLATION_WARNING)",
    ):
        assert marker in PAGE
    assert PROFIT_DIAL_CANCELLATION_WARNING == (
        "DO NOT CANCEL PROFIT DIAL OR REI BLACKBOOK UNTIL EVERY NUMBER IS VERIFIED "
        "WORKING ON THE NEW PROVIDER."
    )
    for forbidden in (
        "requests.",
        "request.urlopen",
        "functions.invoke",
        "send_sms",
        "sendSms",
        "makeCall",
        "create_webhook",
        "port_request",
        "COMMANDCORE_QUO_OPENPHONE_MODE",
    ):
        assert forbidden not in PAGE


def test_existing_nevaeh_inbound_adapter_safety_remains_intact() -> None:
    assert 'lower(Deno.env.get("COMMANDCORE_QUO_OPENPHONE_MODE")) === "inbound"' in QUO_ADAPTER
    assert 'error: "live_phone_ingress_disabled"' in QUO_ADAPTER
    assert "outbound_messages: 0" in QUO_ADAPTER
    assert "outbound_calls: 0" in QUO_ADAPTER
    assert "outbound_enabled: false" in QUO_ADAPTER
    assert "api.openphone.com" not in QUO_ADAPTER
