from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CodingTicket:
    ticket_id: str
    goal: str
    branch_name: str
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_request(request: str) -> str:
    return " ".join(request.strip().split())


def build_ticket(request: str) -> CodingTicket:
    """Create a deterministic Dev-team ticket without touching CRM or production."""
    normalized = normalize_request(request)
    if not normalized:
        raise ValueError("A software-change request is required.")
    digest = hashlib.sha256(normalized.casefold().encode()).hexdigest()[:12]
    return CodingTicket(
        ticket_id=f"DEV-{digest}",
        goal=normalized,
        branch_name=f"coding-agent/{digest}",
        allowed_actions=(
            "search_repo",
            "prepare_feature_branch",
            "edit_code",
            "run_ruff",
            "run_pytest",
            "run_simulation_harness",
            "draft_pull_request",
        ),
        forbidden_actions=(
            "crm.commit",
            "email.send",
            "sms.send",
            "offer.send",
            "contract.send",
            "contract.sign",
            "ads.spend",
            "ads.authorized_scrape",
            "money.move",
            "merge_main",
            "deploy_edge_function",
        ),
    )


def write_ticket(ticket: CodingTicket, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ticket.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="CommandCore Dev-team Coding Agent entrypoint.")
    parser.add_argument("--request", required=True, help="Software-change ticket to plan.")
    parser.add_argument("--output", default="artifacts/coding-agent-ticket.json")
    args = parser.parse_args()
    ticket = build_ticket(args.request)
    output = write_ticket(ticket, args.output)
    print(f"Coding Agent ticket: {ticket.ticket_id}")
    print(f"Feature branch: {ticket.branch_name}")
    print("CRM writes: blocked by design")
    print("Command Center launch: unsupported")
    print(f"Ticket artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
