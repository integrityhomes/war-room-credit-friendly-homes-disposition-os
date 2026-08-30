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
        st.Page("pages/44_CommandCore_CRM.py", title="CRM Workspace", icon="🏠"),
    ],
    "Deals": [
        st.Page("pages/45_CommandCore_Deal_Record.py", title="Unified Deal Record", icon="📂"),
        st.Page("pages/47_CommandCore_Deal_Workflow_Queue.py", title="Deal Workflow", icon="🔄"),
    ],
    "Tasks & Follow-Up": [
        st.Page("pages/35_CommandCore_My_Work.py", title="My Work", icon="👤"),
        st.Page("pages/46_CommandCore_Pipeline_Followup.py", title="Pipeline & Follow-Up", icon="📈"),
        st.Page("pages/36_CommandCore_Coverage.py", title="Coverage", icon="🛡️"),
    ],
    "Marketing & Dispo": [
        st.Page("pages/90_CFH_Marketing_Dispo.py", title="Marketing Command", icon="📣"),
        st.Page("pages/01_Record_Manager.py", title="Property Records", icon="🏘️"),
        st.Page("pages/29_Email_SMS_Reactivation.py", title="Buyer Outreach", icon="✉️"),
        st.Page(
            "pages/26_Instagram_TikTok_YouTube_Shorts.py",
            title="Social Video",
            icon="🎬",
        ),
        st.Page("pages/19_Dwelyx_Results_Attribution.py", title="Buyer & Dwelyx Results", icon="📊"),
        st.Page("pages/23_Daily_Executive_Disposition_Command.py", title="Disposition Command", icon="🎯"),
        st.Page("pages/28_Meta_Google_Paid_Traffic.py", title="Meta & Google Ads Plan", icon="📈"),
        st.Page("pages/33_ChatGPT_Ads_Channel_16.py", title="ChatGPT Ads Plan", icon="💬"),
    ],
    "Management": [
        st.Page("pages/48_CommandCore_Owner_Approvals.py", title="Owner Approvals", icon="✅"),
        st.Page("pages/39_CommandCore_Operations_Hub.py", title="Operations Hub", icon="🧭"),
        st.Page("pages/38_CommandCore_Management_Alerts.py", title="Management Alerts", icon="⚠️"),
        st.Page("pages/37_CommandCore_Coverage_Exceptions.py", title="Coverage Exceptions", icon="🚨"),
        st.Page("pages/40_CommandCore_Team_Health.py", title="Team Health", icon="🩺"),
        st.Page("pages/41_CommandCore_Workload_Balance.py", title="Workload Balance", icon="⚖️"),
        st.Page("pages/42_CommandCore_Rebalance_Audit.py", title="Rebalance Audit", icon="🧾"),
        st.Page("pages/43_CommandCore_CRM_Migration.py", title="CRM Migration", icon="📥"),
        st.Page("pages/31_16_Channel_Completion_Audit.py", title="Marketing Completion Audit", icon="✅"),
        st.Page("pages/32_Go_Live_Connection_Center.py", title="Go-Live Connections", icon="🔌"),
        st.Page("pages/34_Safe_Full_Payload_Test.py", title="Safe Payload Diagnostic", icon="🧪"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
