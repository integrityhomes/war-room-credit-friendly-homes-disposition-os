from __future__ import annotations

import streamlit as st

from cfh_disposition.blog_public import render_blog_request
from cfh_disposition.commandcore_ux import (
    NavigationItem,
    NavigationSection,
    render_sidebar_navigation,
)
from cfh_disposition.market_seo_public import render_market_seo_request
from cfh_disposition.public_pages import render_public_request
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import build_storage


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


DIAGNOSTIC_PAGE = "pages/" + "34_Safe_Full_Payload_Test.py"

EVERYDAY_NAVIGATION = (
    NavigationSection(
        "Home",
        (
            NavigationItem("pages/00_CommandCore.py", "Home"),
            NavigationItem("pages/49_CommandCore_Command_Bot.py", "Ask CommandCore"),
        ),
    ),
    NavigationSection("Leads / Sellers", (NavigationItem("pages/44_CommandCore_CRM.py", "Leads"),)),
    NavigationSection(
        "Deals / Properties",
        (
            NavigationItem("pages/45_CommandCore_Deal_Record.py", "Deal Workspace"),
            NavigationItem("pages/47_CommandCore_Deal_Workflow_Queue.py", "Deal Work Queue"),
        ),
    ),
    NavigationSection(
        "My Work",
        (
            NavigationItem("pages/35_CommandCore_My_Work.py", "My Work"),
            NavigationItem("pages/46_CommandCore_Pipeline_Followup.py", "Follow-Up & Pipeline"),
        ),
    ),
    NavigationSection(
        "Buyers / Marketing",
        (
            NavigationItem("pages/90_CFH_Marketing_Dispo.py", "Marketing Home"),
            NavigationItem("pages/19_Dwelyx_Results_Attribution.py", "Buyer Results"),
        ),
    ),
    NavigationSection(
        "Management",
        (
            NavigationItem("pages/39_CommandCore_Operations_Hub.py", "Operations"),
            NavigationItem("pages/38_CommandCore_Management_Alerts.py", "Alerts"),
            NavigationItem("pages/40_CommandCore_Team_Health.py", "Team Health"),
        ),
    ),
    NavigationSection(
        "Owner Approvals",
        (NavigationItem("pages/48_CommandCore_Owner_Approvals.py", "Owner Approvals"),),
    ),
)

ADMIN_ADVANCED_NAVIGATION = (
    NavigationSection(
        "Records and setup",
        (
            NavigationItem("pages/01_Record_Manager.py", "Properties & Buyers"),
            NavigationItem("pages/43_CommandCore_CRM_Migration.py", "CRM Import"),
            NavigationItem("pages/50_CommandCore_Contract_Templates.py", "Contract Templates"),
            NavigationItem("pages/49_CommandCore_Phone_System_Setup.py", "Phone Planning"),
            NavigationItem("pages/32_Go_Live_Connection_Center.py", "Connections"),
            NavigationItem("pages/31_16_Channel_Completion_Audit.py", "Marketing Setup Status"),
            NavigationItem(DIAGNOSTIC_PAGE, "Internal Connection Check"),
        ),
    ),
    NavigationSection(
        "Marketing and buyer tools",
        (
            NavigationItem("pages/7_Facebook_Group_Posting_Center.py", "Facebook Groups"),
            NavigationItem("pages/8_Facebook_Group_Bulk_Import.py", "Facebook Group Import"),
            NavigationItem("pages/9_Facebook_Group_Variation_Pack.py", "Facebook Variations"),
            NavigationItem("pages/10_Facebook_Daily_Assignments.py", "Facebook Assignments"),
            NavigationItem("pages/11_AI_Marketing_Optimizer.py", "Marketing Optimizer"),
            NavigationItem("pages/13_AI_Buyer_Reactivation_Autopilot.py", "Buyer Reactivation"),
            NavigationItem("pages/14_AI_Creative_Winner_Rotation.py", "Creative Testing"),
            NavigationItem("pages/15_AI_Buyer_Acquisition_Growth.py", "Buyer Acquisition"),
            NavigationItem("pages/16_AI_Buyer_Conversion_Command_Center.py", "Buyer Conversion"),
            NavigationItem("pages/17_Nextdoor_Channel_15.py", "Nextdoor"),
            NavigationItem("pages/18_Property_Shutdown_Buyer_Reroute.py", "Buyer Reroute"),
            NavigationItem("pages/20_Vacant_Home_Disposition_Escalation.py", "Vacant Home Escalation"),
            NavigationItem("pages/21_Property_Terms_Test_Relaunch.py", "Property Terms Testing"),
            NavigationItem("pages/22_Showing_to_Contract_Conversion.py", "Showing Conversion"),
            NavigationItem("pages/23_Daily_Executive_Disposition_Command.py", "Disposition Performance"),
            NavigationItem("pages/24_15_Channel_Campaign_Cadence_Refresh.py", "Campaign Refresh"),
            NavigationItem("pages/25_Property_Channel_Tracking_Links.py", "Tracking Links"),
            NavigationItem("pages/26_Instagram_TikTok_YouTube_Shorts.py", "Social Video"),
            NavigationItem("pages/27_Classifieds_Channel.py", "Classifieds"),
            NavigationItem("pages/28_Meta_Google_Paid_Traffic.py", "Paid Ads Planning"),
            NavigationItem("pages/29_Email_SMS_Reactivation.py", "Buyer Outreach"),
            NavigationItem("pages/30_Owned_Web_SEO_Channels.py", "Web & SEO"),
            NavigationItem("pages/33_ChatGPT_Ads_Channel_16.py", "ChatGPT Ads Planning"),
        ),
    ),
    NavigationSection(
        "Team and reporting tools",
        (
            NavigationItem("pages/21_CommandCore_Operator_Dashboard.py", "Operator Dashboard Redirect"),
            NavigationItem("pages/36_CommandCore_Coverage.py", "Coverage"),
            NavigationItem("pages/37_CommandCore_Coverage_Exceptions.py", "Coverage Exceptions"),
            NavigationItem("pages/41_CommandCore_Workload_Balance.py", "Workload"),
            NavigationItem("pages/42_CommandCore_Rebalance_Audit.py", "Workload Audit"),
        ),
    ),
)


storage = get_storage()
if render_blog_request(storage):
    st.stop()
if render_market_seo_request(storage):
    st.stop()
if render_public_request(storage):
    st.stop()

# All working user-facing pages remain registered so deep links and specialty
# workflows continue to function.

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
        st.Page("pages/47_CommandCore_Deal_Workflow_Queue.py", title="Deal Work Queue", icon="🔄"),
    ],
    "Tasks & Follow-Up": [
        st.Page("pages/35_CommandCore_My_Work.py", title="My Work", icon="👤"),
        st.Page("pages/46_CommandCore_Pipeline_Followup.py", title="Follow-Up & Pipeline", icon="📈"),
        st.Page("pages/21_CommandCore_Operator_Dashboard.py", title="Operator Dashboard"),
    ],
    "Marketing & Dispo": [
        st.Page("pages/90_CFH_Marketing_Dispo.py", title="Marketing Home", icon="📣"),
        st.Page("pages/01_Record_Manager.py", title="Properties & Buyers"),
        st.Page("pages/7_Facebook_Group_Posting_Center.py", title="Facebook Groups"),
        st.Page("pages/8_Facebook_Group_Bulk_Import.py", title="Facebook Group Import"),
        st.Page("pages/9_Facebook_Group_Variation_Pack.py", title="Facebook Variations"),
        st.Page("pages/10_Facebook_Daily_Assignments.py", title="Facebook Assignments"),
        st.Page("pages/11_AI_Marketing_Optimizer.py", title="Marketing Optimizer"),
        st.Page("pages/13_AI_Buyer_Reactivation_Autopilot.py", title="Buyer Reactivation"),
        st.Page("pages/14_AI_Creative_Winner_Rotation.py", title="Creative Testing"),
        st.Page("pages/15_AI_Buyer_Acquisition_Growth.py", title="Buyer Acquisition"),
        st.Page("pages/16_AI_Buyer_Conversion_Command_Center.py", title="Buyer Conversion"),
        st.Page("pages/17_Nextdoor_Channel_15.py", title="Nextdoor"),
        st.Page("pages/18_Property_Shutdown_Buyer_Reroute.py", title="Buyer Reroute"),
        st.Page("pages/19_Dwelyx_Results_Attribution.py", title="Buyer Results"),
        st.Page("pages/20_Vacant_Home_Disposition_Escalation.py", title="Vacant Home Escalation"),
        st.Page("pages/22_Showing_to_Contract_Conversion.py", title="Showing Conversion"),
        st.Page("pages/24_15_Channel_Campaign_Cadence_Refresh.py", title="Campaign Refresh"),
        st.Page("pages/25_Property_Channel_Tracking_Links.py", title="Tracking Links"),
        st.Page("pages/26_Instagram_TikTok_YouTube_Shorts.py", title="Social Video"),
        st.Page("pages/27_Classifieds_Channel.py", title="Classifieds"),
        st.Page("pages/28_Meta_Google_Paid_Traffic.py", title="Paid Ads Planning"),
        st.Page("pages/29_Email_SMS_Reactivation.py", title="Buyer Outreach"),
        st.Page("pages/30_Owned_Web_SEO_Channels.py", title="Web & SEO"),
        st.Page("pages/33_ChatGPT_Ads_Channel_16.py", title="ChatGPT Ads Planning"),
    ],
    "Management": [
        st.Page("pages/48_CommandCore_Owner_Approvals.py", title="Owner Approvals", icon="✅"),
        st.Page("pages/49_CommandCore_Phone_System_Setup.py", title="Phone System Setup", icon="☎️"),
        st.Page("pages/50_CommandCore_Contract_Templates.py", title="Contract Templates", icon="📄"),
        st.Page("pages/39_CommandCore_Operations_Hub.py", title="Operations", icon="🧭"),
        st.Page("pages/36_CommandCore_Coverage.py", title="Coverage"),
        st.Page("pages/38_CommandCore_Management_Alerts.py", title="Alerts"),
        st.Page("pages/37_CommandCore_Coverage_Exceptions.py", title="Coverage Exceptions"),
        st.Page("pages/40_CommandCore_Team_Health.py", title="Team Health"),
        st.Page("pages/41_CommandCore_Workload_Balance.py", title="Workload"),
        st.Page("pages/42_CommandCore_Rebalance_Audit.py", title="Workload Audit"),
        st.Page("pages/43_CommandCore_CRM_Migration.py", title="CRM Import"),
        st.Page("pages/31_16_Channel_Completion_Audit.py", title="Marketing Setup Status"),
        st.Page("pages/32_Go_Live_Connection_Center.py", title="Connections"),
        st.Page("pages/21_Property_Terms_Test_Relaunch.py", title="Property Terms Diagnostic"),
        st.Page("pages/23_Daily_Executive_Disposition_Command.py", title="Disposition"),
        st.Page(DIAGNOSTIC_PAGE, title="Internal Check"),
    ],
}

navigation = st.navigation(pages, position="hidden")
render_sidebar_navigation(EVERYDAY_NAVIGATION, ADMIN_ADVANCED_NAVIGATION)
navigation.run()
