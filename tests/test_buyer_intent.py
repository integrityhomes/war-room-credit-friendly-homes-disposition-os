from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfh_disposition.buyer_intent import (
    BuyerIntentError,
    BuyerIntentLedger,
    IntentTier,
    OutreachChannel,
    build_match,
    build_match_queue,
    outreach_ready,
    record_outreach,
    record_signal,
    score_buyer_for_property,
)
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty


def property_record() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        total_price=Decimal("94500"),
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        public_disclosures="Possible updating.",
    )


def buyer(**overrides) -> BuyerProfile:
    values = {
        "first_name": "Quynh",
        "last_name": "Tran",
        "email": "buyer@example.com",
        "phone": "5551234567",
        "preferred_cities": ["Decatur"],
        "preferred_states": ["IL"],
        "minimum_bedrooms": 3,
        "maximum_monthly_payment": Decimal("1100"),
        "available_down_payment": Decimal("3000"),
        "move_timeframe_days": 30,
        "repair_tolerance": "Medium",
        "email_consent": True,
        "sms_consent": True,
    }
    values.update(overrides)
    return BuyerProfile(**values)


def test_strong_financial_and_location_match_is_hot() -> None:
    score, tier, reasons, blocked = score_buyer_for_property(
        buyer(),
        property_record(),
        BuyerIntentLedger(),
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )

    assert score >= 75
    assert tier == IntentTier.HOT
    assert "location match" in reasons
    assert "monthly payment fits" in reasons
    assert blocked == ""


def test_do_not_contact_is_never_eligible() -> None:
    score, tier, _, blocked = score_buyer_for_property(
        buyer(do_not_contact=True),
        property_record(),
        BuyerIntentLedger(),
    )

    assert score == 0
    assert tier == IntentTier.NOT_ELIGIBLE
    assert "Do Not Contact" in blocked


def test_missing_email_and_sms_consent_is_blocked() -> None:
    score, tier, _, blocked = score_buyer_for_property(
        buyer(email_consent=False, sms_consent=False),
        property_record(),
        BuyerIntentLedger(),
    )

    assert score == 0
    assert tier == IntentTier.NOT_ELIGIBLE
    assert "consent" in blocked.lower()


def test_recent_showing_signal_increases_score() -> None:
    item = buyer(maximum_monthly_payment=Decimal("900"))
    prop = property_record()
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    baseline, _, _, _ = score_buyer_for_property(item, prop, BuyerIntentLedger(), now=now)
    ledger = record_signal(
        BuyerIntentLedger(),
        buyer_id=item.buyer_id,
        property_id=prop.property_id,
        signal_type="showing_requested",
        occurred_at=now - timedelta(days=1),
    )
    improved, _, reasons, _ = score_buyer_for_property(item, prop, ledger, now=now)

    assert improved > baseline
    assert "recent engagement" in reasons


def test_match_copy_preserves_terms_and_hides_total_price() -> None:
    item = buyer()
    prop = property_record()
    match = build_match(
        item,
        prop,
        BuyerIntentLedger(),
        "https://www.dwelyx.com/buyer/register",
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )
    combined = f"{match.email_subject}\n{match.email_body}\n{match.sms_message}"

    assert prop.display_address in combined
    assert "$2,000" in combined
    assert "$950" in combined
    assert "$94,500" not in combined
    assert "not rent" in combined.lower()
    assert "subject to review" in combined.lower()
    assert "STOP" in combined
    assert match.tracked_link in combined


def test_queue_excludes_unconsented_and_low_fit_buyers() -> None:
    prop = property_record()
    matches = build_match_queue(
        [
            buyer(first_name="Strong"),
            buyer(first_name="NoConsent", email_consent=False, sms_consent=False),
            buyer(
                first_name="LowFit",
                preferred_cities=["Chicago"],
                preferred_states=["WI"],
                maximum_monthly_payment=Decimal("500"),
                available_down_payment=Decimal("500"),
            ),
        ],
        [prop],
        BuyerIntentLedger(),
        "https://www.dwelyx.com/buyer/register",
        minimum_score=35,
    )

    assert len(matches) == 1
    assert matches[0].buyer_name.startswith("Strong")


def test_recorded_outreach_activates_channel_cooldown() -> None:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    item = buyer()
    prop = property_record()
    ledger = BuyerIntentLedger()
    match = build_match(
        item,
        prop,
        ledger,
        "https://www.dwelyx.com/buyer/register",
        now=now,
    )
    updated = record_outreach(
        ledger,
        match,
        channel=OutreachChannel.EMAIL,
        sent_by="Sabrina",
        sent_at=now,
    )

    assert outreach_ready(
        updated,
        item.buyer_id,
        prop.property_id,
        OutreachChannel.EMAIL,
        now=now + timedelta(days=1),
    ) is False
    assert outreach_ready(
        updated,
        item.buyer_id,
        prop.property_id,
        OutreachChannel.SMS,
        now=now + timedelta(days=1),
    ) is True
    assert outreach_ready(
        updated,
        item.buyer_id,
        prop.property_id,
        OutreachChannel.EMAIL,
        now=now + timedelta(days=14),
    ) is True


def test_record_outreach_blocks_channel_without_permission() -> None:
    item = buyer(email_consent=False)
    match = build_match(
        item,
        property_record(),
        BuyerIntentLedger(),
        "https://www.dwelyx.com/buyer/register",
    )

    with pytest.raises(BuyerIntentError, match="not allowed"):
        record_outreach(
            BuyerIntentLedger(),
            match,
            channel=OutreachChannel.EMAIL,
            sent_by="Sabrina",
        )
