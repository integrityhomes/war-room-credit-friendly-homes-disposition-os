from cfh_disposition.operations_readiness import journey_readiness_summary


def test_journey_summary_counts_healthy_and_failed_business_flows() -> None:
    summary = journey_readiness_summary(
        {
            "journeys": [
                {
                    "journey": "Lead Intake & CRM",
                    "healthy": True,
                    "failed_services": [],
                },
                {
                    "journey": "Closing & Disposition",
                    "healthy": False,
                    "failed_services": ["commandcore-deal-completion"],
                },
            ]
        }
    )

    assert summary.total == 2
    assert summary.healthy == 1
    assert summary.failed == 1
    assert summary.label == "1/2 healthy"
    assert summary.rows[1]["Status"] == "Needs attention"
    assert "commandcore-deal-completion" in summary.rows[1]["Problem"]


def test_missing_journey_payload_is_safe_and_empty() -> None:
    summary = journey_readiness_summary({"launch_ready": True})

    assert summary.total == 0
    assert summary.healthy == 0
    assert summary.failed == 0
    assert summary.rows == ()
