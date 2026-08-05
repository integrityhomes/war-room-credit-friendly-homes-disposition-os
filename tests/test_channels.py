from cfh_disposition.channels import CHANNELS, CHANNELS_BY_KEY, ChannelMode


def test_fifteen_marketing_channels_exist() -> None:
    assert len(CHANNELS) == 15


def test_marketplace_is_assisted_not_automatic() -> None:
    assert CHANNELS_BY_KEY["marketplace"].mode == ChannelMode.ASSISTED


def test_nextdoor_is_channel_fifteen_and_requires_assisted_posting() -> None:
    assert CHANNELS[-1].key == "nextdoor"
    assert CHANNELS_BY_KEY["nextdoor"].mode == ChannelMode.ASSISTED
    assert "Dwelyx" in CHANNELS_BY_KEY["nextdoor"].purpose


def test_google_business_profile_is_not_required() -> None:
    assert "google_business_profile" not in CHANNELS_BY_KEY
