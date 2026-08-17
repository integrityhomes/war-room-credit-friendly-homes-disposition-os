from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.chatgpt_ads import SUPPORTED_MARKETS, build_chatgpt_ads_plan


def test_chatgpt_ads_is_registered_as_channel_16():
    channel = CHANNELS_BY_KEY["chatgpt_ads"]
    assert channel.name == "ChatGPT Ads"


def test_chatgpt_ads_supports_all_current_cfh_markets():
    assert set(SUPPORTED_MARKETS) == {
        "Virginia",
        "Illinois",
        "Indiana",
        "Alabama",
        "St. Louis Metro",
        "Michigan",
        "Ohio",
    }


def test_chatgpt_ads_plan_is_buyer_acquisition_and_tracked():
    plan = build_chatgpt_ads_plan(
        market="Virginia",
        intent="Owner-financed homes",
        landing_base_url="https://www.dwelyx.com/buyer/register",
        daily_budget=Decimal("25"),
    )
    query = parse_qs(urlsplit(plan.landing_url).query)
    assert query["medium"] == ["chatgpt_ads"]
    assert query["market"] == ["Virginia"]
    assert query["intent"] == ["Owner-financed homes"]
    assert "property_id" not in query
    assert any("buyer-acquisition" in note.lower() for note in plan.notes)


def test_chatgpt_ads_does_not_generate_specific_property_copy():
    plan = build_chatgpt_ads_plan(
        market="Illinois",
        intent="Alternative path to homeownership",
        landing_base_url="https://www.dwelyx.com/buyer/register",
        daily_budget=Decimal("25"),
    )
    combined = " ".join((*plan.headlines, *plan.descriptions, *plan.context_hints))
    assert "945 W Packard" not in combined
    assert "123 Main" not in combined
