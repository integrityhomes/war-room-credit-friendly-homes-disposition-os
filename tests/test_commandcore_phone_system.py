from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cfh_disposition.commandcore_phone_system import (
    PHONE_AUDIT_DOCUMENT,
    PROFIT_DIAL_CANCELLATION_WARNING,
    OperationalStatus,
    PhoneNumberRecord,
    PhonePlanningDocumentStore,
    PhonePlanningStorageError,
    PhoneProvider,
    PhoneProviderPool,
    PhonePurpose,
    PhoneSystemPlan,
    PortingStatus,
    ProviderConfiguration,
    RoutingCategory,
    RoutingPlan,
    StaffPhoneAssignment,
    normalize_phone_planning_crm_response,
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


def test_staff_line_unknown_status_and_optional_department_are_supported() -> None:
    blank_department = fictional_number(
        purpose=PhonePurpose.STAFF_LINE,
        department_purpose="",
        operational_status=OperationalStatus.UNKNOWN_NEEDS_REVIEW,
    )
    unknown_department = fictional_number(
        phone_number="+1 202-555-0151",
        department_purpose="UNKNOWN / NEEDS REVIEW",
    )

    assert blank_department.purpose is PhonePurpose.STAFF_LINE
    assert blank_department.operational_status is OperationalStatus.UNKNOWN_NEEDS_REVIEW
    assert blank_department.department_purpose == ""
    assert unknown_department.department_purpose == "UNKNOWN / NEEDS REVIEW"
    assert blank_department.porting_status is PortingStatus.KEEP_PROTECTED_MIGRATION_UNDECIDED


@pytest.mark.parametrize(
    ("legacy_active", "expected_status"),
    [
        (True, OperationalStatus.ACTIVE),
        (False, OperationalStatus.INACTIVE_RESERVED),
    ],
)
def test_legacy_phase_5b_active_records_remain_readable(
    legacy_active: bool, expected_status: OperationalStatus
) -> None:
    legacy_payload = fictional_number().model_dump(mode="json")
    legacy_payload.pop("operational_status")
    legacy_payload.pop("provider_pool_id")
    legacy_payload["active"] = legacy_active

    loaded = PhoneNumberRecord.model_validate(legacy_payload)

    assert loaded.operational_status is expected_status
    assert loaded.active is legacy_active
    assert loaded.provider_pool_id == ""


class FakePrivateCrm:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        assert payload["entity"] == "documents"
        action = payload["action"]
        if action == "list":
            return {"ok": True, "records": list(self.documents.values())}
        assert action == "upsert"
        record = dict(payload["record"])  # type: ignore[arg-type]
        self.documents[str(record["id"])] = record
        return {"ok": True, "record": record}


def test_phone_planning_crm_response_accepts_successful_byte_encoded_json() -> None:
    response = b'{"ok":true,"records":[]}'

    assert normalize_phone_planning_crm_response(response) == {"ok": True, "records": []}


def test_phone_planning_crm_response_keeps_dictionary_support() -> None:
    response = {"ok": True, "records": []}

    assert normalize_phone_planning_crm_response(response) is response


def test_phone_planning_crm_response_accepts_object_data() -> None:
    response = SimpleNamespace(data={"ok": True, "records": []})

    assert normalize_phone_planning_crm_response(response) == {"ok": True, "records": []}


@pytest.mark.parametrize("response", [b"not-json", bytearray(b"[]")])
def test_phone_planning_crm_response_fails_closed(response: bytes | bytearray) -> None:
    with pytest.raises(PhonePlanningStorageError, match="invalid|unsupported"):
        normalize_phone_planning_crm_response(response)


def test_private_persistence_survives_a_new_store_session_and_keeps_audit_history() -> None:
    backend = FakePrivateCrm()
    first_session = PhonePlanningDocumentStore(backend)
    saved = first_session.save_number(fictional_number(), action="create")

    second_session = PhonePlanningDocumentStore(backend)
    loaded = second_session.list_numbers()
    assert len(loaded) == 1
    assert loaded[0].record_id == saved.record_id
    assert loaded[0].phone_number == "+12025550142"
    assert loaded[0].porting_status is PortingStatus.KEEP_PROTECTED_MIGRATION_UNDECIDED

    second_session.deactivate_number(loaded[0], "fictional-admin-user")
    assert second_session.list_numbers() == ()
    assert second_session.list_numbers(include_inactive=True)[0].active is False
    audit_events = [
        item for item in backend.documents.values() if item.get("document_type") == PHONE_AUDIT_DOCUMENT
    ]
    assert [item["event_action"] for item in audit_events] == ["create", "deactivate"]


@pytest.mark.parametrize(
    "unsafe_notes",
    [
        "carrier pin=example-12345678",
        "api_key=example-credential-value",
        "Bearer " + "abcdefghijklmnop",
    ],
)
def test_private_persistence_rejects_credentials_before_storage(unsafe_notes: str) -> None:
    backend = FakePrivateCrm()
    store = PhonePlanningDocumentStore(backend)
    with pytest.raises(ValueError, match="Credentials are prohibited"):
        store.save_number(fictional_number(notes=unsafe_notes))
    assert backend.documents == {}


def test_provider_pool_rejects_credentials_before_storage() -> None:
    backend = FakePrivateCrm()
    store = PhonePlanningDocumentStore(backend)
    with pytest.raises(ValueError, match="Credentials are prohibited"):
        store.save_provider_pool(
            PhoneProviderPool(
                provider_name="XLeads",
                label="MARKETING / DIALER POOL",
                notes="carrier pin=example-12345678",
            )
        )
    assert backend.documents == {}


def test_assignments_and_routes_persist_across_sessions() -> None:
    backend = FakePrivateCrm()
    first_session = PhonePlanningDocumentStore(backend)
    first_session.save_assignment(
        StaffPhoneAssignment(
            staff_member="Fictional VA",
            user_reference="fictional-user-1",
            role="VA",
            assigned_shared_phone_numbers=("+12025550142",),
            primary_number="+12025550142",
        ),
        action="create",
    )
    first_session.save_route(
        RoutingPlan(
            category=RoutingCategory.SELLER_LEADS,
            primary_staff_or_team="Fictional Seller Team",
        ),
        action="create",
    )

    new_session = PhonePlanningDocumentStore(backend)
    assert new_session.list_assignments()[0].user_reference == "fictional-user-1"
    assert new_session.list_routes()[0].category is RoutingCategory.SELLER_LEADS


def test_xleads_pool_persists_with_zero_phone_numbers_across_sessions() -> None:
    backend = FakePrivateCrm()
    first_session = PhonePlanningDocumentStore(backend)
    saved = first_session.save_provider_pool(
        PhoneProviderPool(
            provider_name="XLeads",
            label="MARKETING / DIALER POOL",
            actor_reference="fictional-admin-user",
        ),
        action="create",
    )

    second_session = PhonePlanningDocumentStore(backend)
    pools = second_session.list_provider_pools()
    assert second_session.list_numbers() == ()
    assert len(pools) == 1
    assert pools[0].pool_id == saved.pool_id
    assert pools[0].provider_name == "XLeads"
    assert pools[0].category is PhonePurpose.MARKETING_DIALER_POOL
    assert pools[0].operational_status is OperationalStatus.UNKNOWN_NEEDS_REVIEW


def test_phone_number_can_be_added_under_provider_pool_later() -> None:
    pool = PhoneProviderPool(provider_name="XLeads", label="MARKETING / DIALER POOL")
    number = fictional_number(
        phone_number="+1 202-555-0168",
        purpose=PhonePurpose.MARKETING_DIALER_POOL,
        provider_pool_id=pool.pool_id,
    )

    assert number.provider_pool_id == pool.pool_id


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
        'functions.invoke("commandcore-quo-openphone-adapter"',
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
