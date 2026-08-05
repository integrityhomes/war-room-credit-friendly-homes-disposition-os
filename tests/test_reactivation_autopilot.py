from datetime import UTC, datetime, timedelta

import pytest

from cfh_disposition.buyer_intent import (
    BuyerEngagementSignal,
    BuyerIntentLedger,
    BuyerPropertyMatch,
    IntentTier,
    OutreachChannel,
)
from cfh_disposition.reactivation_autopilot import (
    ReactivationAutopilotError,
    ReactivationAutopilotLedger,
    ReactivationDispatchReceipt,
    ReactivationJobStatus,
    approve_job,
    build_dispatch_payload,
    build_reactivation_jobs,
    cancel_job,
    due_jobs,
    engagement_stop_reason,
    record_dispatch_failure,
    record_dispatch_success,
    sequence_plan,
    stop_job_for_engagement,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def match(
    *,
    tier: IntentTier = IntentTier.HOT,
    email_allowed: bool = True,
    sms_allowed: bool = True,
    buyer_id: str = "buyer-1",
    property_id: str = "property-1",
) -> BuyerPropertyMatch:
    return BuyerPropertyMatch(
        buyer_id=buyer_id,
        buyer_name="Alex Buyer",
        property_id=property_id,
        property_address="945 W Packard St, Decatur, IL, 62522",
        score=88 if tier == IntentTier.HOT else 62 if tier == IntentTier.WARM else 40,
        tier=tier,
        reasons=("location match", "monthly payment fits"),
        email_allowed=email_allowed,
        sms_allowed=sms_allowed,
        email="alex@example.com",
        phone="2175550100",
        tracked_link="https://www.dwelyx.com/buyer/register?utm_source=test",
        email_subject="Owner-finance home match",
        email_body="Exact property facts and opt-out language.",
        sms_message="Exact property facts. Reply STOP to opt out.",
    )


def test_hot_sequence_uses_sms_then_email() -> None:
    plan = sequence_plan(match(), now=NOW)

    assert plan[0][0] == OutreachChannel.SMS
    assert plan[0][1] == NOW
    assert plan[1][0] == OutreachChannel.EMAIL
    assert plan[1][1] == NOW + timedelta(days=1)


def test_warm_sequence_uses_email_then_sms_after_two_days() -> None:
    plan = sequence_plan(match(tier=IntentTier.WARM), now=NOW)

    assert plan[0][0] == OutreachChannel.EMAIL
    assert plan[0][1] == NOW
    assert plan[1][0] == OutreachChannel.SMS
    assert plan[1][1] == NOW + timedelta(days=2)


def test_nurture_sequence_uses_one_consent_channel() -> None:
    plan = sequence_plan(
        match(tier=IntentTier.NURTURE, email_allowed=False, sms_allowed=True),
        now=NOW,
    )

    assert len(plan) == 1
    assert plan[0][0] == OutreachChannel.SMS


def test_build_jobs_prevents_duplicate_sequence_steps() -> None:
    first, created, skipped = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    second, created_again, skipped_again = build_reactivation_jobs(
        first,
        [match()],
        now=NOW,
    )

    assert created == 2
    assert skipped == 0
    assert created_again == 0
    assert skipped_again == 2
    assert len(second.jobs) == 2


def test_approve_and_dispatch_success_updates_status() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    job = ledger.jobs[0]
    approved = approve_job(
        ledger,
        job_id=job.job_id,
        approved_by="Sabrina",
        now=NOW,
    )
    receipt = ReactivationDispatchReceipt(
        status_code=200,
        dispatched_at=NOW + timedelta(minutes=1),
        response_text="accepted",
    )
    completed = record_dispatch_success(
        approved,
        job_id=job.job_id,
        receipt=receipt,
    )
    updated = next(item for item in completed.jobs if item.job_id == job.job_id)

    assert updated.status == ReactivationJobStatus.DISPATCHED
    assert updated.approved_by == "Sabrina"
    assert updated.dispatch_attempts == 1
    assert updated.external_response == "accepted"


def test_failed_dispatch_can_be_reapproved() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    job = ledger.jobs[0]
    approved = approve_job(ledger, job_id=job.job_id, approved_by="Sabrina", now=NOW)
    failed = record_dispatch_failure(
        approved,
        job_id=job.job_id,
        error="temporary timeout",
        now=NOW,
    )
    reapproved = approve_job(
        failed,
        job_id=job.job_id,
        approved_by="Carlos",
        now=NOW + timedelta(minutes=5),
    )
    updated = next(item for item in reapproved.jobs if item.job_id == job.job_id)

    assert updated.status == ReactivationJobStatus.APPROVED
    assert updated.approved_by == "Carlos"
    assert updated.dispatch_attempts == 1


def test_engagement_stops_future_sequence_step() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    email_job = next(job for job in ledger.jobs if job.channel == OutreachChannel.EMAIL)
    intent_ledger = BuyerIntentLedger(
        signals=[
            BuyerEngagementSignal(
                buyer_id=email_job.buyer_id,
                property_id=email_job.property_id,
                signal_type="showing_requested",
                occurred_at=NOW + timedelta(hours=2),
            )
        ]
    )
    reason = engagement_stop_reason(intent_ledger, email_job)
    stopped = stop_job_for_engagement(
        ledger,
        job_id=email_job.job_id,
        reason=reason,
        now=NOW + timedelta(hours=2),
    )
    updated = next(item for item in stopped.jobs if item.job_id == email_job.job_id)

    assert "showing requested" in reason
    assert updated.status == ReactivationJobStatus.STOPPED


def test_due_jobs_excludes_future_and_completed_jobs() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    sms_job = next(job for job in ledger.jobs if job.channel == OutreachChannel.SMS)
    email_job = next(job for job in ledger.jobs if job.channel == OutreachChannel.EMAIL)
    approved = approve_job(ledger, job_id=sms_job.job_id, approved_by="Sabrina", now=NOW)
    completed = record_dispatch_success(
        approved,
        job_id=sms_job.job_id,
        receipt=ReactivationDispatchReceipt(
            status_code=200,
            dispatched_at=NOW,
            response_text="accepted",
        ),
    )

    due_now = due_jobs(completed, now=NOW)
    due_tomorrow = due_jobs(completed, now=NOW + timedelta(days=1))

    assert sms_job.job_id not in {job.job_id for job in due_now}
    assert email_job.job_id not in {job.job_id for job in due_now}
    assert email_job.job_id in {job.job_id for job in due_tomorrow}


def test_dispatch_payload_is_idempotent_and_compliance_labeled() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    job = ledger.jobs[0]
    approved = approve_job(ledger, job_id=job.job_id, approved_by="Sabrina", now=NOW)
    approved_job = next(item for item in approved.jobs if item.job_id == job.job_id)
    payload = build_dispatch_payload(approved_job)

    assert payload["idempotency_key"] == job.job_id
    assert payload["recipient"] == job.recipient
    assert payload["tracked_dwelyx_link"] == job.tracked_link
    assert payload["compliance"]["consent_required"] is True
    assert payload["compliance"]["approval_promises_allowed"] is False


def test_dispatched_job_cannot_be_cancelled() -> None:
    ledger, _, _ = build_reactivation_jobs(
        ReactivationAutopilotLedger(),
        [match()],
        now=NOW,
    )
    job = ledger.jobs[0]
    approved = approve_job(ledger, job_id=job.job_id, approved_by="Sabrina", now=NOW)
    completed = record_dispatch_success(
        approved,
        job_id=job.job_id,
        receipt=ReactivationDispatchReceipt(status_code=200, dispatched_at=NOW),
    )

    with pytest.raises(ReactivationAutopilotError, match="cannot be cancelled"):
        cancel_job(completed, job_id=job.job_id)
