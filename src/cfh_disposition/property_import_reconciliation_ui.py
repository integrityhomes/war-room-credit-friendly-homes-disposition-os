"""Private read-only review on the existing baseline page."""

import json

import streamlit as st

from .property_import_reconciliation import load_import_reconciliation


def render_import_reconciliation():
    st.subheader("Missing property import reconciliation")
    st.caption("One entry per missing physical property. Yellow inventory appears first. Import and checkpoint creation remain disabled.")
    if st.button("Build missing-property preview", key="build_missing_property_preview", type="primary"):
        st.session_state.pop("missing_property_preview", None)
        try:
            with st.spinner("Reading source fields, canonical properties, and existing clocks…"):
                result = load_import_reconciliation(st.secrets)
        except Exception:
            st.error("The complete read-only reconciliation could not be read. No records or checkpoints were changed.")
        else:
            st.session_state.missing_property_preview = result
    result = st.session_state.get("missing_property_preview")
    if not result:
        return
    if "current_inventory" in result:
        scope = st.radio("Review scope", ("Current inventory only", "Full reconciliation including history"), key="import_reconciliation_scope")
        if scope == "Current inventory only":
            current = result["current_inventory"]
            result = {**result, "properties": current["properties"], "total_missing": current["total_candidates"], "total_ready": current["total_ready"],
                      "summary": current["summary"], "duplicate_conflict_count": sum(not e["duplicate_safe"] for e in current["properties"]),
                      "properties_with_field_warnings": sum(bool(e["field_warnings"]) for e in current["properties"]),
                      "manual_review_count": sum(bool(e["field_warnings"] or e["blocking_reasons"]) for e in current["properties"])}
            st.info("Current yellow and white inventory only. Historical-only SOLD is excluded. Field warnings do not become guessed canonical values.")
    st.caption(f"Source read: {result['observed_at']}")
    st.write(f"**{result['total_missing']} missing properties · {result['total_ready']} ready for a later approved import preview**")
    st.dataframe([{"Classification": k, **v} for k, v in result["summary"].items()], hide_index=True)
    st.caption(f"Duplicate/conflict concerns: {result['duplicate_conflict_count']} · Properties with field warnings: {result['properties_with_field_warnings']} · "
               f"Manual review: {result['manual_review_count']} · Deletions: 0")
    if result["missing_marketing_clocks"]:
        with st.expander("Existing canonical yellow properties missing marketing clocks — no clocks created"):
            st.dataframe(result["missing_marketing_clocks"], hide_index=True)
    entries = result["properties"]
    st.dataframe([{"Property": e["address"], "Classification": e["classification"], "Readiness": e["readiness"],
                   "Field warnings": len(e["field_warnings"]), "Source": e["source_tab"]} for e in entries], hide_index=True)
    if entries:
        index = st.selectbox("Inspect missing property", range(len(entries)), format_func=lambda i: entries[i]["address"], key="missing_property_selection")
        entry = entries[index]
        st.write(f"**{entry['address']} — {entry['readiness']}**")
        st.write(f"Identity verified: {entry['identity_verified']} · Marketing verified: {entry['marketing_verified']} · Access code present: {entry['access_code_present']}")
        for reason in entry["blocking_reasons"]:
            st.warning(reason)
        st.json(entry["normalized_details"])
        with st.expander("Source wording, field warnings, and history"):
            st.dataframe([{**d, "normalized": json.dumps(d["normalized"], ensure_ascii=False)} for d in entry["source_fields"]], hide_index=True)
            st.json(entry["historical_occurrences"])
            st.caption("Historical SOLD is source classification only, never proof of a closing.")
    st.button("Import disabled", disabled=True, key="missing_import_disabled")
