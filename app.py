from __future__ import annotations

import streamlit as st

from cfh_disposition.public_pages import render_public_request
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import build_storage


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


storage = get_storage()
if render_public_request(storage):
    st.stop()

pages = {
    "Home / Command Center": [
        st.Page("pages/00_CommandCore.py", title="Command Center", icon="🧭", default=True),
    ],
    "Leads & CRM": [
        st.Page("pages/44_CommandCore_CRM.py", title="CRM Workspace", icon="🏠"),
        st.Page("pages/43_CommandCore_CRM_Migration.py", title="CRM Migration", icon="📥"),
    ],
    "Deals": [
        st.Page("pages/45_CommandCore_Deal_Record.py", title="Unified Deal Record", icon="📂"),
        st.Page("pages/46_CommandCore_Pipeline_Followup.py", title="Pipeline & Follow-Up", icon="📈"),
    ],
    "Tasks & Follow-Up": [
        st.Page("pages/35_CommandCore_My_Work.py", title="My Work", icon="👤"),
        st.Page("pages/36_CommandCore_Coverage.py", title="Coverage", icon="🛡️"),
    ],
    "Marketing & Dispo": [
        st.Page("pages/90_CFH_Marketing_Dispo.py", title="CFH Marketing Flow", icon="📣"),
        st.Page("pages/01_Record_Manager.py", title="Property Records", icon="🏘️"),
        st.Page("pages/19_Dwelyx_Results_Attribution.py", title="Buyer & Dwelyx Results", icon="📊"),
        st.Page("pages/23_Daily_Executive_Disposition_Command.py", title="Disposition Command", icon="🎯"),
    ],
    "Management": [
        st.Page("pages/39_CommandCore_Operations_Hub.py", title="Operations Hub", icon="🧭"),
        st.Page("pages/38_CommandCore_Management_Alerts.py", title="Management Alerts", icon="⚠️"),
        st.Page("pages/37_CommandCore_Coverage_Exceptions.py", title="Coverage Exceptions", icon="🚨"),
        st.Page("pages/40_CommandCore_Team_Health.py", title="Team Health", icon="🩺"),
        st.Page("pages/41_CommandCore_Workload_Balance.py", title="Workload Balance", icon="⚖️"),
        st.Page("pages/42_CommandCore_Rebalance_Audit.py", title="Rebalance Audit", icon="🧾"),
    ],
}

navigation = st.navigation(pages, position="sidebar", expanded=True)
navigation.run()
