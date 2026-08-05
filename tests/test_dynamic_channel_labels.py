from pathlib import Path

from cfh_disposition.channels import CHANNELS


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


def test_growth_plan_uses_live_channel_count_and_full_table_height() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert 'st.subheader(f"{len(CHANNELS)}-Channel Growth Plan")' in source
    assert "height=max(420, len(CHANNELS) * 35 + 45)" in source
