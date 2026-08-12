from pathlib import Path


def test_social_video_streamlit_page_exists_and_names_all_three_channels():
    page = Path("pages/26_Instagram_TikTok_YouTube_Shorts.py")
    text = page.read_text(encoding="utf-8")
    assert "Instagram Reels & Posts" in text
    assert "TikTok" in text
    assert "YouTube Shorts" in text
    assert "build_channel_links" in text
