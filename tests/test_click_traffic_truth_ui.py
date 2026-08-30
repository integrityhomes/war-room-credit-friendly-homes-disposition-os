from pathlib import Path


def test_channel_test_link_records_test_traffic() -> None:
    source = Path("src/cfh_disposition/public_pages.py").read_text(encoding="utf-8")

    for marker in (
        'traffic_type = TEST_TRAFFIC if _query_flag("test_mode") else LIVE_TRAFFIC',
        '"Test This Channel Link — records TEST click"',
        '_test_tracking_url(live_tracking_url)',
        'traffic_type=traffic_type',
    ):
        assert marker in source


def test_marketing_analytics_defaults_to_live_buyer_traffic() -> None:
    source = Path("src/cfh_disposition/public_pages.py").read_text(encoding="utf-8")

    for marker in (
        '"Live buyer traffic"',
        '"Live buyer clicks"',
        '"Test clicks"',
        '"Unclassified legacy clicks"',
        'include_test=True',
        'include_unclassified=True',
        'event.traffic_type == LIVE_TRAFFIC',
    ):
        assert marker in source


def test_default_click_store_reads_verified_live_traffic_only() -> None:
    source = Path("src/cfh_disposition/analytics.py").read_text(encoding="utf-8")

    assert "include_test: bool = False" in source
    assert "include_unclassified: bool = False" in source
    assert "traffic_type == TEST_TRAFFIC and not include_test" in source
    assert "traffic_type == UNCLASSIFIED_TRAFFIC and not include_unclassified" in source
