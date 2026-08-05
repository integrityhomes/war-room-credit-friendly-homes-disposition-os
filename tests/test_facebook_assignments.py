from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cfh_disposition.facebook_assignments import (
    AssignmentStatus,
    FacebookAssignmentError,
    FacebookAssignmentLedger,
    active_operators,
    assignments_for_date,
    complete_assignment_and_record_group_post,
    daily_assignment_summary,
    generate_daily_assignments,
    update_assignment_status,
    upsert_operator,
)
from cfh_disposition.facebook_groups import (
    FacebookGroupLedger,
    facebook_group_post_status,
    upsert_group,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property(number: int) -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address=f"{900 + number} W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        square_feet=1352,
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        showing_instructions="Appointment required.",
        public_disclosures="Possible updating.",
    )


def group_ledger() -> FacebookGroupLedger:
    ledger = FacebookGroupLedger()
    for number in range(1, 4):
        ledger = upsert_group(
            ledger,
            name=f"Illinois Owner Finance Group {number}",
            group_url=f"https://www.facebook.com/groups/{1000 + number}",
            cooldown_days=7,
            now=datetime(2026, 8, 1, 12, number, tzinfo=UTC),
        )
    return ledger


def assignment_ledger() -> FacebookAssignmentLedger:
    ledger = upsert_operator(
        FacebookAssignmentLedger(),
        name="Sabrina",
        daily_goal=2,
        notes="Primary operator",
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )
    return upsert_operator(
        ledger,
        name="Carlos",
        daily_goal=1,
        notes="Backup operator",
        now=datetime(2026, 8, 4, 12, 1, tzinfo=UTC),
    )


def test_operator_upsert_updates_existing_name_instead_of_duplicating() -> None:
    ledger = assignment_ledger()
    sabrina = next(operator for operator in ledger.operators if operator.name == "Sabrina")
    updated = upsert_operator(
        ledger,
        name="sabrina",
        daily_goal=30,
        notes="Updated goal",
        now=datetime(2026, 8, 4, 13, 0, tzinfo=UTC),
    )

    assert len(updated.operators) == 2
    refreshed = next(
        operator for operator in updated.operators if operator.operator_id == sabrina.operator_id
    )
    assert refreshed.daily_goal == 30
    assert refreshed.active is True


def test_balanced_generation_respects_goals_and_one_group_per_day() -> None:
    ledger = assignment_ledger()
    operators = active_operators(ledger)
    assignment_date = date(2026, 8, 5)
    result = generate_daily_assignments(
        ledger,
        group_ledger(),
        [sample_property(1), sample_property(2)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )

    assignments = assignments_for_date(result.ledger, assignment_date)
    assert result.created == 3
    assert len(assignments) == 3
    assert len({assignment.group_id for assignment in assignments}) == 3

    loads = {
        operator.name: sum(
            assignment.assigned_to_id == operator.operator_id
            for assignment in assignments
        )
        for operator in operators
    }
    assert loads["Sabrina"] == 2
    assert loads["Carlos"] == 1

    for assignment in assignments:
        assert assignment.property_address in assignment.post_copy
        assert "$2,000" in assignment.post_copy
        assert "$950" in assignment.post_copy
        assert "$94,500" not in assignment.post_copy
        assert assignment.post_copy.count(assignment.tracked_link) == 1
        assert "not rent" in assignment.post_copy.lower()


def test_second_generation_does_not_duplicate_same_day_assignments() -> None:
    ledger = assignment_ledger()
    operators = active_operators(ledger)
    assignment_date = date(2026, 8, 5)
    first = generate_daily_assignments(
        ledger,
        group_ledger(),
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    second = generate_daily_assignments(
        first.ledger,
        group_ledger(),
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 5, tzinfo=UTC),
    )

    assert first.created == 3
    assert second.created == 0
    assert len(assignments_for_date(second.ledger, assignment_date)) == 3


def test_complete_assignment_records_group_post_and_activates_cooldown() -> None:
    ledger = assignment_ledger()
    groups = group_ledger()
    operators = active_operators(ledger)
    assignment_date = date(2026, 8, 5)
    generated = generate_daily_assignments(
        ledger,
        groups,
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    assignment = assignments_for_date(generated.ledger, assignment_date)[0]
    completed_assignments, completed_groups = complete_assignment_and_record_group_post(
        generated.ledger,
        groups,
        assignment_id=assignment.assignment_id,
        actor="Sabrina",
        notes="Facebook post URL saved",
        now=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
    )

    completed = next(
        item
        for item in completed_assignments.assignments
        if item.assignment_id == assignment.assignment_id
    )
    assert completed.status == AssignmentStatus.POSTED
    assert completed.completed_by == "Sabrina"
    assert len(completed_groups.posts) == 1
    assert completed_groups.posts[0].tracked_link == assignment.tracked_link

    cooldown = facebook_group_post_status(
        completed_groups,
        property_id=assignment.property_id,
        group_id=assignment.group_id,
        now=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
    )
    assert cooldown.eligible is False
    assert cooldown.wait_days == 6


def test_skipped_assignment_releases_daily_goal_capacity() -> None:
    ledger = assignment_ledger()
    groups = group_ledger()
    operators = active_operators(ledger)
    assignment_date = date(2026, 8, 5)
    generated = generate_daily_assignments(
        ledger,
        groups,
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    first = assignments_for_date(generated.ledger, assignment_date)[0]
    skipped = update_assignment_status(
        generated.ledger,
        assignment_id=first.assignment_id,
        status=AssignmentStatus.SKIPPED,
        actor="Sabrina",
        notes="Group temporarily paused posts",
        now=datetime(2026, 8, 5, 9, 30, tzinfo=UTC),
    )
    regenerated = generate_daily_assignments(
        skipped,
        groups,
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 35, tzinfo=UTC),
    )

    assert regenerated.created == 1
    assert len(assignments_for_date(regenerated.ledger, assignment_date)) == 4


def test_daily_summary_tracks_workload_and_completion() -> None:
    ledger = assignment_ledger()
    operators = active_operators(ledger)
    assignment_date = date(2026, 8, 5)
    generated = generate_daily_assignments(
        ledger,
        group_ledger(),
        [sample_property(1)],
        operator_ids=[operator.operator_id for operator in operators],
        assignment_date=assignment_date,
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
    )
    first, second, _ = assignments_for_date(generated.ledger, assignment_date)
    updated = update_assignment_status(
        generated.ledger,
        assignment_id=first.assignment_id,
        status=AssignmentStatus.IN_PROGRESS,
        actor="Sabrina",
        now=datetime(2026, 8, 5, 9, 15, tzinfo=UTC),
    )
    updated = update_assignment_status(
        updated,
        assignment_id=second.assignment_id,
        status=AssignmentStatus.SKIPPED,
        actor="Carlos",
        now=datetime(2026, 8, 5, 9, 20, tzinfo=UTC),
    )
    summary = daily_assignment_summary(updated, assignment_date)

    assert summary.total == 3
    assert summary.in_progress == 1
    assert summary.skipped == 1
    assert summary.remaining == 2
    assert summary.completion_percent == 0


def test_completing_missing_assignment_is_blocked() -> None:
    with pytest.raises(FacebookAssignmentError, match="could not be found"):
        complete_assignment_and_record_group_post(
            assignment_ledger(),
            group_ledger(),
            assignment_id="missing",
            actor="Sabrina",
        )
