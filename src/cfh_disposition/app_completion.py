from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AppCompletionState(StrEnum):
    COMPLETE = "complete"
    EXTERNAL_BLOCKER = "external_blocker"
    SUPPORT_TOOL = "support_tool"
    DIAGNOSTIC = "diagnostic"
    NEEDS_WORK = "needs_work"


@dataclass(frozen=True, slots=True)
class AppCompletion:
    path: str
    area: str
    state: AppCompletionState
    disposition: str
    blocker: str = ""


APP_COMPLETION: tuple[AppCompletion, ...] = (
    AppCompletion("pages/00_CommandCore.py", "Shell", AppCompletionState.COMPLETE, "Canonical six-area CommandCore shell."),
    AppCompletion("pages/01_Record_Manager.py", "Marketing & Dispo", AppCompletionState.SUPPORT_TOOL, "Legacy property-record support tool; fold under inventory/property setup."),
    AppCompletion("pages/7_Facebook_Group_Posting_Center.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Canonical manual Facebook Group posting workspace."),
    AppCompletion("pages/8_Facebook_Group_Bulk_Import.py", "Marketing & Dispo", AppCompletionState.SUPPORT_TOOL, "Facebook Group directory/import support tool."),
    AppCompletion("pages/9_Facebook_Group_Variation_Pack.py", "Marketing & Dispo", AppCompletionState.SUPPORT_TOOL, "Facebook Group fact-safe variation support tool."),
    AppCompletion("pages/10_Facebook_Daily_Assignments.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Daily team posting assignments and cooldown tracking."),
    AppCompletion("pages/11_AI_Marketing_Optimizer.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Persisted marketing-performance optimization tool."),
    AppCompletion("pages/13_AI_Buyer_Reactivation_Autopilot.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "Canonical buyer-reactivation app; older duplicate removed.", "Live dispatch requires the approved buyer-outreach webhook connection."),
    AppCompletion("pages/14_AI_Creative_Winner_Rotation.py", "Marketing & Dispo", AppCompletionState.NEEDS_WORK, "Keep distinct creative-testing app; add shared property-marketability guard."),
    AppCompletion("pages/15_AI_Buyer_Acquisition_Growth.py", "Marketing & Dispo", AppCompletionState.NEEDS_WORK, "Keep distinct buyer-acquisition app; add shared property-marketability guard."),
    AppCompletion("pages/16_AI_Buyer_Conversion_Command_Center.py", "Marketing & Dispo", AppCompletionState.NEEDS_WORK, "Keep distinct conversion app; block all new work for non-marketable properties."),
    AppCompletion("pages/17_Nextdoor_Channel_15.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Manual-final-step Nextdoor channel workspace."),
    AppCompletion("pages/18_Property_Shutdown_Buyer_Reroute.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Property shutdown and buyer reroute workflow."),
    AppCompletion("pages/19_Dwelyx_Results_Attribution.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "Signed Dwelyx result attribution software and receiver are built.", "Live result events require the Dwelyx server-side sender/shared-secret connection."),
    AppCompletion("pages/20_Vacant_Home_Disposition_Escalation.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Vacant-home disposition escalation workflow."),
    AppCompletion("pages/21_CommandCore_Operator_Dashboard.py", "Tasks & Follow-Up", AppCompletionState.SUPPORT_TOOL, "Operator dashboard; fold into My Work/Operations during final UI pass."),
    AppCompletion("pages/21_Property_Terms_Test_Relaunch.py", "Management", AppCompletionState.DIAGNOSTIC, "Property terms/relaunch diagnostic; keep out of normal operator navigation."),
    AppCompletion("pages/22_Showing_to_Contract_Conversion.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Showing-to-contract conversion workflow."),
    AppCompletion("pages/23_Daily_Executive_Disposition_Command.py", "Management", AppCompletionState.SUPPORT_TOOL, "Executive disposition command support view."),
    AppCompletion("pages/24_15_Channel_Campaign_Cadence_Refresh.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Campaign cadence/refresh operations."),
    AppCompletion("pages/25_Property_Channel_Tracking_Links.py", "Marketing & Dispo", AppCompletionState.SUPPORT_TOOL, "Per-channel tracked-link support tool."),
    AppCompletion("pages/26_Instagram_TikTok_YouTube_Shorts.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "Canonical social-video package/publish-handoff app; duplicate removed.", "Live platform publication requires an approved social publishing adapter/account connection."),
    AppCompletion("pages/27_Classifieds_Channel.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Manual-final-step classifieds channel workspace."),
    AppCompletion("pages/28_Meta_Google_Paid_Traffic.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "Paid-traffic package software is complete and approval-gated.", "Live Meta/Google campaigns require account authorization and explicit spending approval."),
    AppCompletion("pages/29_Email_SMS_Reactivation.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "Email/SMS software handoffs are built with consent/DNC guards.", "Live sender endpoints/accounts must be connected."),
    AppCompletion("pages/30_Owned_Web_SEO_Channels.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Owned-web Blog/Market SEO routes are built; Blog remains approval-gated."),
    AppCompletion("pages/31_16_Channel_Completion_Audit.py", "Management", AppCompletionState.SUPPORT_TOOL, "Truthful channel completion audit."),
    AppCompletion("pages/32_Go_Live_Connection_Center.py", "Management", AppCompletionState.SUPPORT_TOOL, "External connection/readiness center."),
    AppCompletion("pages/33_ChatGPT_Ads_Channel_16.py", "Marketing & Dispo", AppCompletionState.EXTERNAL_BLOCKER, "ChatGPT Ads package/connection path is software-complete.", "Live use requires supported account/platform connection and any required spend approval."),
    AppCompletion("pages/34_Safe_Full_Payload_Test.py", "Management", AppCompletionState.DIAGNOSTIC, "Safe payload diagnostic; keep out of normal operator navigation."),
    AppCompletion("pages/35_CommandCore_My_Work.py", "Tasks & Follow-Up", AppCompletionState.COMPLETE, "Canonical My Work queue."),
    AppCompletion("pages/36_CommandCore_Coverage.py", "Management", AppCompletionState.COMPLETE, "Coverage management."),
    AppCompletion("pages/37_CommandCore_Coverage_Exceptions.py", "Management", AppCompletionState.COMPLETE, "Coverage exception handling."),
    AppCompletion("pages/38_CommandCore_Management_Alerts.py", "Management", AppCompletionState.COMPLETE, "Management alerts."),
    AppCompletion("pages/39_CommandCore_Operations_Hub.py", "Management", AppCompletionState.COMPLETE, "Operations Hub and system readiness."),
    AppCompletion("pages/40_CommandCore_Team_Health.py", "Management", AppCompletionState.COMPLETE, "Team health/workload visibility."),
    AppCompletion("pages/41_CommandCore_Workload_Balance.py", "Management", AppCompletionState.COMPLETE, "Workload balance tooling."),
    AppCompletion("pages/42_CommandCore_Rebalance_Audit.py", "Management", AppCompletionState.COMPLETE, "Auto-rebalance audit view."),
    AppCompletion("pages/43_CommandCore_CRM_Migration.py", "Management", AppCompletionState.EXTERNAL_BLOCKER, "Safe migration preview/apply/reconciliation UI is built.", "CRM cutover remains blocked until real source-CRM reconciliation is verified."),
    AppCompletion("pages/44_CommandCore_CRM.py", "Leads & CRM", AppCompletionState.COMPLETE, "Canonical CommandCore CRM."),
    AppCompletion("pages/45_CommandCore_Deal_Record.py", "Deals", AppCompletionState.COMPLETE, "Canonical Unified Deal Record."),
    AppCompletion("pages/46_CommandCore_Pipeline_Followup.py", "Tasks & Follow-Up", AppCompletionState.COMPLETE, "Pipeline and follow-up workspace."),
    AppCompletion("pages/47_CommandCore_Deal_Workflow_Queue.py", "Deals", AppCompletionState.COMPLETE, "Internal deal workflow queue."),
    AppCompletion("pages/48_CommandCore_Owner_Approvals.py", "Management", AppCompletionState.COMPLETE, "Owner Approval Queue with separate PIN and crash-safe history."),
    AppCompletion("pages/49_CommandCore_Command_Bot.py", "Home / Command Center", AppCompletionState.COMPLETE, "Command Bot with idempotent internal request creation."),
    AppCompletion("pages/90_CFH_Marketing_Dispo.py", "Marketing & Dispo", AppCompletionState.COMPLETE, "Preserved canonical CFH marketing/disposition workspace."),
)


APP_COMPLETION_BY_PATH = {row.path: row for row in APP_COMPLETION}


def needs_work() -> tuple[AppCompletion, ...]:
    return tuple(row for row in APP_COMPLETION if row.state == AppCompletionState.NEEDS_WORK)


def external_blockers() -> tuple[AppCompletion, ...]:
    return tuple(row for row in APP_COMPLETION if row.state == AppCompletionState.EXTERNAL_BLOCKER)
