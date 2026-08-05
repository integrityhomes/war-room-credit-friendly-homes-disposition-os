from pathlib import Path

from cfh_disposition.channels import CHANNELS
from cfh_disposition.simple_flow import PRIMARY_NAVIGATION

UI_FILES = (
    Path("app.py"),
    Path("src/cfh_disposition/auth.py"),
    Path("src/cfh_disposition/public_pages.py"),
    Path("src/cfh_disposition/campaign_launch.py"),
)


def test_current_marketing_plan_has_fifteen_channels() -> None:
    assert len(CHANNELS) == 15
    assert CHANNELS[-1].key == "nextdoor"


def test_key_ui_files_do_not_hard_code_the_old_channel_count() -> None:
    for path in UI_FILES:
        source = path.read_text(encoding="utf-8")
        assert "14-Channel" not in source
        assert "14-channel" not in source
        assert "all 14 channels" not in source


def test_home_uses_live_channel_count_and_simple_default_flow() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert 'st.subheader(f"Simple {len(CHANNELS)}-Channel Marketing Flow")' in source
    assert PRIMARY_NAVIGATION[0] == "Simple Marketing Flow"
    assert "height=max(420, len(CHANNELS) * 35 + 45)" not in source
