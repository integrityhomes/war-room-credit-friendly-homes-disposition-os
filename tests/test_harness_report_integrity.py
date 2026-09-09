from __future__ import annotations

import json

from cfh_disposition.harness.report import write_report
from cfh_disposition.harness.runner import run_offer_no_send


def test_json_and_markdown_reports_agree_on_verdict_counts_and_provider_calls(tmp_path) -> None:
    report = run_offer_no_send()
    json_path, markdown_path = write_report(report, tmp_path)

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert saved["harness"] == "CommandCore Test & Simulation Harness"
    assert saved["scenario"] == report.scenario
    assert saved["mode"] == report.mode
    assert saved["verdict"] == report.verdict
    assert saved["provider_calls"] == report.provider_calls == 0
    assert len(saved["intended_actions"]) == len(report.actions)
    assert len(saved["blocked_actions"]) == sum(
        action.decision == "blocked" for action in report.actions
    )
    assert all(action["deal_id"] for action in saved["intended_actions"])
    assert all(action["action_type"] for action in saved["intended_actions"])
    assert all(action["decision"] for action in saved["intended_actions"])
    assert all(action["reason"] for action in saved["intended_actions"])
    assert all(action["timestamp"] for action in saved["intended_actions"])

    assert f"Scenario: `{report.scenario}`" in markdown
    assert f"Mode: `{report.mode}`" in markdown
    assert f"Verdict: **{report.verdict}**" in markdown
    assert f"Provider calls: **{report.provider_calls}**" in markdown
    assert f"Intended actions: **{len(saved['intended_actions'])}**" in markdown
    assert f"Blocked actions: **{len(saved['blocked_actions'])}**" in markdown
