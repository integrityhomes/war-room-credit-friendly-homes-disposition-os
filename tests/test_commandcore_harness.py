from __future__ import annotations

from cfh_disposition.harness.crm_staging import preview_fixture_commit, stage_fixture_rows
from cfh_disposition.harness.fixtures import load_fixture_family
from cfh_disposition.harness.mode import HarnessMode, parse_mode
from cfh_disposition.harness.runner import (
    run_communications_followup_no_send,
    run_contract_no_sign,
    run_crm_stage_no_commit,
    run_offer_no_send,
)
from cfh_disposition.harness.side_effects import ActionType, SideEffectBus


def test_mode_defaults_to_simulation_and_rejects_unknown_mode() -> None:
    assert parse_mode() is HarnessMode.SIMULATION


def test_simulation_never_emits_real_side_effects() -> None:
    calls: list[tuple[str, dict]] = []
    bus = SideEffectBus(
        HarnessMode.SIMULATION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    deal = {"id": "FIXTURE-DEAL", "internal_only": False, "external_action_started": True}
    approval = {"status": "approved"}

    record = bus.request(
        ActionType.EMAIL_SEND,
        {"to": "nobody@example.invalid"},
        deal=deal,
        owner_approval=approval,
    )

    assert record.decision == "blocked"
    assert bus.provider_calls == 0
    assert calls == []


def test_production_blocks_consequential_action_without_external_start_and_owner_approval() -> None:
    bus = SideEffectBus(HarnessMode.PRODUCTION)

    missing_start = bus.request(
        ActionType.MONEY_MOVE,
        {"amount": 100},
        deal={"id": "deal-1", "internal_only": False, "external_action_started": False},
        owner_approval={"status": "approved"},
    )
    missing_approval = bus.request(
        ActionType.MONEY_MOVE,
        {"amount": 100},
        deal={"id": "deal-2", "internal_only": False, "external_action_started": True},
        owner_approval={"status": "pending"},
    )

    assert missing_start.decision == "blocked"
    assert missing_approval.decision == "blocked"
    assert bus.provider_calls == 0


def test_fixtures_load_without_live_supabase_and_are_internal_only() -> None:
    fixture = load_fixture_family()
    for key in (
        "contact",
        "property",
        "deal",
        "offer",
        "contract_draft",
        "task",
        "communication",
        "approval",
    ):
        assert fixture[key]["internal_only"] is True
        assert str(fixture[key]["id"]).startswith("FIXTURE-")


def test_offer_scenario_runs_existing_math_and_blocks_send() -> None:
    report = run_offer_no_send()
    data = report.to_dict()

    assert report.verdict == "PASS"
    assert report.mode == "simulation"
    assert report.provider_calls == 0
    assert data["artifacts"]["offer"]["starting_offer"] == 28000
    assert data["artifacts"]["offer"]["max_offer"] == 32000
    offer_send = next(
        action for action in data["blocked_actions"] if action["action_type"] == "offer.send"
    )
    assert offer_send["payload_summary"]["offer_amount"] == 28000


def test_contract_scenario_creates_new_private_version_and_blocks_send_and_sign() -> None:
    report = run_contract_no_sign()
    data = report.to_dict()

    assert report.verdict == "PASS"
    assert report.provider_calls == 0
    generated = data["artifacts"]["generated_document"]
    assert generated["version"] == 2
    assert generated["storage_bucket"] == "commandcore-contract-documents"
    assert "/generated_contract/v2/" in generated["storage_object_path"]
    assert generated["internal_only"] is True
    blocked_types = {action["action_type"] for action in data["blocked_actions"]}
    assert {"contract.send", "contract.sign"}.issubset(blocked_types)


def test_crm_commit_in_simulation_never_calls_live_upsert_executor() -> None:
    calls: list[tuple[str, dict]] = []
    bus = SideEffectBus(
        HarnessMode.SIMULATION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    record = bus.request(
        ActionType.CRM_COMMIT,
        {"table": "deals", "id": "FIXTURE-DEAL"},
        deal={"id": "FIXTURE-DEAL", "internal_only": True, "external_action_started": False},
    )

    assert record.decision == "blocked"
    assert calls == []
    assert bus.provider_calls == 0


def test_crm_staging_adapter_preserves_fixture_and_produces_no_write_preview() -> None:
    rows = stage_fixture_rows(load_fixture_family())
    preview = preview_fixture_commit(rows)

    assert [row.entity for row in rows] == ["contacts", "properties", "deals"]
    assert all(row.internal_only for row in rows)
    assert all(row.source_payload_preserved for row in rows)
    assert preview["approved_rows"] == 3
    assert preview["would_create"] == 3
    assert preview["would_update"] == 0
    assert preview["records_written"] == 0
    assert preview["source_records_modified"] is False
    assert preview["destructive_delete_used"] is False
    assert preview["external_action_started"] is False


def test_crm_stage_no_commit_scenario_reports_would_write_and_blocks_production_commit() -> None:
    report = run_crm_stage_no_commit()
    data = report.to_dict()

    assert report.verdict == "PASS"
    assert report.mode == "simulation"
    assert report.provider_calls == 0
    preview = data["artifacts"]["commit_preview"]
    assert preview["apply_requested"] is False
    assert preview["would_create"] == 3
    assert preview["records_written"] == 0
    assert data["artifacts"]["production_commit_attempted"] is True
    assert data["artifacts"]["production_commit_performed"] is False
    crm_commit = next(
        action for action in data["blocked_actions"] if action["action_type"] == "crm.commit"
    )
    assert crm_commit["payload_summary"]["apply"] is False
    assert crm_commit["payload_summary"]["confirm_apply"] is False


def test_communications_followup_creates_internal_task_and_draft_but_sends_nothing() -> None:
    report = run_communications_followup_no_send()
    data = report.to_dict()

    assert report.verdict == "PASS"
    assert report.mode == "simulation"
    assert report.provider_calls == 0
    assert data["artifacts"]["inbound_communication"]["direction"] == "inbound"
    assert data["artifacts"]["follow_up_task"]["status"] == "open"
    assert data["artifacts"]["follow_up_task"]["internal_only"] is True
    assert data["artifacts"]["reply_draft"]["direction"] == "outbound_draft"
    assert data["artifacts"]["reply_draft"]["internal_only"] is True
    assert data["artifacts"]["message_sent"] is False
    blocked_types = {action["action_type"] for action in data["blocked_actions"]}
    assert "crm.commit" in blocked_types
    assert "sms.send" in blocked_types


def test_verdict_report_separates_intended_blocked_and_approval_required_actions() -> None:
    data = run_offer_no_send().to_dict()

    assert data["intended_actions"]
    assert data["blocked_actions"]
    assert any(
        action["action_type"] == "offer.send" for action in data["approval_required_actions"]
    )
