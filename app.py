from __future__ import annotations

import streamlit as st

from cfh_disposition.blog_public import render_blog_request
from cfh_disposition.market_seo_public import render_market_seo_request
from cfh_disposition.public_pages import render_public_request
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import build_storage


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


storage = get_storage()
if render_blog_request(storage):
    st.stop()
if render_market_seo_request(storage):
    st.stop()
if render_public_request(storage):
    st.stop()

pages = {
    "Home / Command Center": [
        st.Page(
            "pages/00_CommandCore.py",
            title="Command Center",
            icon="🧭",
            default=True,
        ),
        st.Page("pages/49_CommandCore_Command_Bot.py", title="Command Bot", icon="🤖"),
    ],
    "Leads & CRM": [
        st.Page("pages/44_CommandCore_CRM.py", title="Leads", icon="🏠"),
    ],
    "Deals": [
        st.Page("pages/45_CommandCore_Deal_Record.py", title="Deal Workspace", icon="📂"),
        st.Page("pages/47_CommandCore_Deal_Workflow_Queue.py", title="Deal Next Steps", icon="🔄"),
    ],
    "Tasks & Follow-Up": [
        st.Page("pages/35_CommandCore_My_Work.py", title="My Work", icon="👤"),
        st.Page("pages/46_CommandCore_Pipeline_Followup.py", title="Follow-Up & Pipeline", icon="📈"),
        st.Page("pages/36_CommandCore_Coverage.py", title="Coverage", icon="🛡️"),
    ],
    "Marketing & Dispo": [
        st.Page("pages/90_CFH_Marketing_Dispo.py", title="Marketing Home", icon="📣"),
        st.Page("pages/01_Record_Manager.py", title="Properties & Buyers", icon="🏘️"),
        st.Page("pages/29_Email_SMS_Reactivation.py", title="Buyer Outreach", icon="✉️"),
        st.Page(
            "pages/26_Instagram_TikTok_YouTube_Shorts.py",
            title="Social Video",
            icon="🎬",
        ),
        st.Page("pages/19_Dwelyx_Results_Attribution.py", title="Buyer Results", icon="📊"),
        st.Page("pages/23_Daily_Executive_Disposition_Command.py", title="Disposition", icon="🎯"),
        st.Page("pages/28_Meta_Google_Paid_Traffic.py", title="Paid Ads Planning", icon="📈"),
        st.Page("pages/33_ChatGPT_Ads_Channel_16.py", title="ChatGPT Ads Planning", icon="💬"),
    ],
    "Management": [
        st.Page("pages/48_CommandCore_Owner_Approvals.py", title="Owner Approvals", icon="✅"),
        st.Page("pages/50_CommandCore_Contract_Templates.py", title="Contract Templates", icon="📄"),
        st.Page("pages/39_CommandCore_Operations_Hub.py", title="Operations", icon="🧭"),
        st.Page("pages/38_CommandCore_Management_Alerts.py", title="Alerts", icon="⚠️"),
        st.Page("pages/37_CommandCore_Coverage_Exceptions.py", title="Coverage Exceptions", icon="🚨"),
        st.Page("pages/40_CommandCore_Team_Health.py", title="Team Health", icon="🩺"),
        st.Page("pages/41_CommandCore_Workload_Balance.py", title="Workload", icon="⚖️"),
        st.Page("pages/42_CommandCore_Rebalance_Audit.py", title="Workload Audit", icon="🧾"),
        st.Page("pages/43_CommandCore_CRM_Migration.py", title="CRM Import", icon="📥"),
        st.Page("pages/31_16_Channel_Completion_Audit.py", title="Marketing Setup Status", icon="✅"),
        st.Page("pages/32_Go_Live_Connection_Center.py", title="Connections", icon="🔌"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
