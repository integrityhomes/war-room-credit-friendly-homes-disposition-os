# Review of the 60 previously unexercised modules

Based on the completed 1,617-scenario baseline; these are execution gaps, not proof of dead code. No modules were removed.

A: meaningful business coverage; B: admin/developer/support; C: obsolete/dead; D: external integration requiring fakes; E: other.

Counts: A = 26, B = 10, C = 0, D = 20, E = 4. No module is declared obsolete without evidence.

| Module/route | Classification | Assessment |
|---|---|---|
| `app.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/00_CommandCore.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/01_Record_Manager.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/10_Facebook_Daily_Assignments.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/11_AI_Marketing_Optimizer.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/13_AI_Buyer_Reactivation_Autopilot.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/14_AI_Creative_Winner_Rotation.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/15_AI_Buyer_Acquisition_Growth.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/16_AI_Buyer_Conversion_Command_Center.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/17_Nextdoor_Channel_15.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/18_Property_Shutdown_Buyer_Reroute.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/19_Dwelyx_Results_Attribution.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/20_Vacant_Home_Disposition_Escalation.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/21_CommandCore_Operator_Dashboard.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/21_Property_Terms_Test_Relaunch.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/22_Showing_to_Contract_Conversion.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/23_Daily_Executive_Disposition_Command.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/24_15_Channel_Campaign_Cadence_Refresh.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/25_Property_Channel_Tracking_Links.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/26_Instagram_TikTok_YouTube_Shorts.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/27_Classifieds_Channel.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/28_Meta_Google_Paid_Traffic.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/29_Email_SMS_Reactivation.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/30_Owned_Web_SEO_Channels.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/31_16_Channel_Completion_Audit.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/32_Go_Live_Connection_Center.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/33_ChatGPT_Ads_Channel_16.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/34_Safe_Full_Payload_Test.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/35_CommandCore_My_Work.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/36_CommandCore_Coverage.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/37_CommandCore_Coverage_Exceptions.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/38_CommandCore_Management_Alerts.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/39_CommandCore_Operations_Hub.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/40_CommandCore_Team_Health.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/41_CommandCore_Workload_Balance.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/42_CommandCore_Rebalance_Audit.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/43_CommandCore_CRM_Migration.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/44_CommandCore_CRM.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/45_CommandCore_Deal_Record.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/46_CommandCore_Pipeline_Followup.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/47_CommandCore_Deal_Workflow_Queue.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/48_CommandCore_Owner_Approvals.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/49_CommandCore_Phone_System_Setup.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/50_CommandCore_Contract_Templates.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/51_CommandCore_Communications.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/7_Facebook_Group_Posting_Center.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `pages/8_Facebook_Group_Bulk_Import.py` | B | Setup, diagnostics, coverage administration, or compatibility utility. |
| `pages/90_CFH_Marketing_Dispo.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `pages/9_Facebook_Group_Variation_Pack.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `src/cfh_disposition/__init__.py` | E | Package initializer, declarative channel catalog, or fictional sample constants. |
| `src/cfh_disposition/channels.py` | E | Package initializer, declarative channel catalog, or fictional sample constants. |
| `src/cfh_disposition/facebook_assignments_ui.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `src/cfh_disposition/facebook_failure_scan.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `src/cfh_disposition/facebook_groups_ui.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `src/cfh_disposition/harness/__init__.py` | E | Package initializer, declarative channel catalog, or fictional sample constants. |
| `src/cfh_disposition/marketplace_ui.py` | D | Channel/external-action surface; requires explicit fake transport and no-send assertions. |
| `src/cfh_disposition/my_work_operator.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `src/cfh_disposition/record_manager.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `src/cfh_disposition/record_manager_safe.py` | A | Current business surface; add targeted workflow coverage, not import-only assertions. |
| `src/cfh_disposition/sample_data.py` | E | Package initializer, declarative channel catalog, or fictional sample constants. |

## Required before an inventory-only import

The current-only executor, canonical read-back, identity conflict handling, partial-failure recovery, clock eligibility, historical/current precedence, protected evidence, and CorePilot lookup of imported records must pass. These now have direct scenarios using real logic with fake transport. No uncovered outbound marketing page is required to authorize a create-only inventory import.

The CRM property view and Marketing Home/Record Manager are the highest-priority additional user-interface scenarios. Until their real render paths are exercised with new canonical records, downstream display coverage is incomplete. The remaining A modules are current business functions worth testing, not a reason to fabricate full-app coverage. Cross-process task creation remains unproven; do not enable parallel task workers based on these results.
