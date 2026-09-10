from __future__ import annotations

import argparse
from pathlib import Path

from .gitops import require_feature_branch
from .report import RunReport, write_report
from .workspace import Workspace


def run(goal: str, workspace_root: str | Path) -> RunReport:
    workspace = Workspace.open(workspace_root)
    branch = require_feature_branch(workspace.root)
    return RunReport(
        goal=goal.strip(),
        workspace=str(workspace.root),
        branch=branch,
        files_changed=(),
        commands_run=(),
        tests_passed=False,
        blocked_actions=(
            "commit",
            "push",
            "merge",
            "deploy",
            "production_crm_write",
            "send_sign_spend",
        ),
        approval_required=("commit", "push", "merge", "deploy"),
        status="planned",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Private Coding Runner Phase 1")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--report", default="artifacts/coding-runner-report.json")
    args = parser.parse_args()

    report = run(args.goal, args.workspace)
    path = write_report(report, args.report)
    print(f"Goal: {report.goal}")
    print(f"Workspace: {report.workspace}")
    print(f"Branch: {report.branch}")
    print("Status: planned; no edits or commits performed by this foundation slice")
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
