from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.chatgpt_ads import INTENT_OPTIONS, SUPPORTED_MARKETS, build_chatgpt_ads_plan
from cfh_disposition.dwelyx import dwelyx_base_url

st.set_page_config(page_title="ChatGPT Ads Channel 16", page_icon="💬", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("chatgpt_ads_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


require_password()
st.title("Channel 16 — ChatGPT Ads")
st.caption("Buyer-acquisition planning by market and intent, tracked into the CFH/Dwelyx funnel.")
st.info(
    "OpenAI Ads Manager Beta is a live advertiser product. Country availability and product capabilities can change, "
    "so verify the current Ads Manager state before launch. This CommandCore page remains planning-only: it does not "
    "create an account, campaign, ad, billing setup, or spend."
)

cols = st.columns(3)
market = cols[0].selectbox("Market", SUPPORTED_MARKETS)
intent = cols[1].selectbox("Buyer intent", INTENT_OPTIONS)
daily_budget = Decimal(
    str(
        cols[2].number_input(
            "Proposed daily budget",
            min_value=1.0,
            value=25.0,
            step=5.0,
            help="Planning value only. Entering a budget here does not authorize or spend money.",
        )
    )
)

landing_default = dwelyx_base_url(st.secrets)
landing_url = st.text_input("Buyer landing page", value=landing_default)

try:
    plan = build_chatgpt_ads_plan(
        market=market,
        intent=intent,
        landing_base_url=landing_url,
        daily_budget=daily_budget,
    )
except ValueError as exc:
    st.error(str(exc))
    st.stop()

st.write("### Campaign planning package")
metrics = st.columns(5)
metrics[0].metric("Channel", "ChatGPT Ads")
metrics[1].metric("Market", plan.market)
metrics[2].metric("Intent", plan.intent)
metrics[3].metric("Proposed daily budget", f"${plan.daily_budget:,.0f}")
metrics[4].metric("Launch authority", "NO")
st.code(plan.campaign_name, language=None)

st.write("### Relevance / use-case guidance")
st.dataframe(
    pd.DataFrame({"Planning guidance": plan.context_hints}),
    use_container_width=True,
    hide_index=True,
)

st.write("### Headline variations")
st.dataframe(
    pd.DataFrame({"Headline": plan.headlines}),
    use_container_width=True,
    hide_index=True,
)

st.write("### Description variations")
for index, text in enumerate(plan.descriptions, start=1):
    st.text_area(
        f"Description {index}",
        value=text,
        height=90,
        key=f"chatgpt_desc_{index}",
        disabled=True,
    )

st.write("### Tracked buyer destination")
st.code(plan.landing_url, language=None)
st.caption(
    "This link identifies source=Credit Friendly Homes, medium=ChatGPT Ads, campaign, market, and buyer intent. "
    "Preserve the same attribution through registrations, applications, showings, contracts, and filled homes."
)

st.write("### Launch guardrails")
for note in plan.notes:
    st.write(f"- {note}")
st.warning(
    "Nothing on this page records owner approval. Any real ChatGPT Ads campaign still requires separate account/billing setup, "
    "current policy review, exact budget approval, and an explicit external launch step."
)

rows = []
for headline in plan.headlines:
    for description in plan.descriptions:
        rows.append(
            {
                "channel": "ChatGPT Ads",
                "market": plan.market,
                "intent": plan.intent,
                "campaign": plan.campaign_name,
                "headline": headline,
                "description": description,
                "landing_url": plan.landing_url,
                "proposed_daily_budget": str(plan.daily_budget),
                "spend_authorized": "NO",
                "launch_authorized": "NO",
                "ads_manager_action_started": "NO",
            }
        )

csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
st.download_button(
    "Download ChatGPT Ads planning package CSV",
    data=csv_bytes,
    file_name=f"{plan.campaign_name}_planning.csv",
    mime="text/csv",
)

st.warning(
    "Before any future launch, review the current OpenAI Ads policy and Ads Manager availability, "
    "confirm the landing page and conversion measurement, and obtain explicit owner approval for "
    "the exact campaign budget and targeting."
)
