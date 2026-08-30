from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .coding_repo import RepositorySnapshot


class TicketLike(Protocol):
    ticket_id: str
    goal: str


@dataclass(frozen=True, slots=True)
class ChangePlan:
    ticket_id: str
    goal: str
    repository_root: str
    likely_areas: tuple[str, ...]
    tests_to_run: tuple[str, ...]
    safety_notes: tuple[str, ...]
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_change_plan(ticket: TicketLike, snapshot: RepositorySnapshot) -> ChangePlan:
    """Create a conservative plan from a ticket and read-only repository snapshot."""
    goal = ticket.goal.casefold()
    likely: list[str] = []

    if any(term in goal for term in ("frontend", "dashboard", "screen", "mobile", "ui")):
        likely.extend(path for path in snapshot.files if path.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".css")))
    if any(term in goal for term in ("api", "backend", "server", "endpoint")):
        likely.extend(path for path in snapshot.python_files if "test" not in path.casefold())
    if any(term in goal for term in ("database", "migration", "supabase", "sql")):
        likely.extend(path for path in snapshot.files if path.endswith((".sql", ".py")))
    if any(term in goal for term in ("test", "bug", "broken", "fix", "regression")):
        likely.extend(snapshot.test_files)

    if not likely:
        likely.extend(snapshot.key_files)
        likely.extend(snapshot.python_files[:20])

    deduped = tuple(dict.fromkeys(likely))[:40]
    tests: list[str] = ["ruff check <touched paths>", "pytest -q <related tests>"]
    if snapshot.test_files:
        tests.append("pytest -q")

    return ChangePlan(
        ticket_id=ticket.ticket_id,
        goal=ticket.goal,
        repository_root=snapshot.root,
        likely_areas=deduped,
        tests_to_run=tuple(tests),
        safety_notes=(
            "Read the existing implementation before editing.",
            "Work on a feature branch only.",
            "Do not write CRM data or trigger production providers.",
            "Do not deploy or merge main without owner approval.",
            "Preserve rollback by keeping the existing working version in Git.",
        ),
    )
