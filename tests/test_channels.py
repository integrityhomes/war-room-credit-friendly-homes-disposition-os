from cfh_disposition.channels import CHANNELS, CHANNELS_BY_KEY, ChannelMode


def test_at_least_twelve_marketing_channels_exist() -> None:
    assert len(CHANNELS) >= 12


def test_marketplace_is_assisted_not_automatic() -> None:
    assert CHANNELS_BY_KEY["marketplace"].mode == ChannelMode.ASSISTED


def test_google_business_profile_is_not_required() -> None:
    assert "google_business_profile" not in CHANNELS_BY_KEY
