"""Results and launcher for the existing project's isolated simulator."""

from pathlib import Path

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.harness.business_simulator import RESULTS, launch, read_result

st.set_page_config(page_title="CommandCore Business Simulator", page_icon="🧪", layout="wide")
if not st.session_state.get("authenticated"):
    with st.form("simulator_sign_in"):
        password = st.text_input("App password", type="password")
        if st.form_submit_button("Sign in") and configured_password(st.secrets) and password_matches(password, configured_password(st.secrets)):
            st.session_state.authenticated = True
            st.rerun()
    st.stop()

st.title("CommandCore Business Simulator")
st.caption("Synthetic data only · Offline subprocess · Production credentials and runtime files blocked · No live import or clock creation")
st.info("PASS means a scenario met its assertions. Uncovered modules remain WARNING. Business-rule failures require review, not automatic repair.")
with st.expander("Meaningful surfaces, integration boundaries, and known workflow gaps"):
    st.markdown((Path(__file__).resolve().parents[1] / "docs/simulator-surface-inventory.md").read_text(encoding="utf-8"))
if st.button("Run full offline simulation", type="primary"):
    st.session_state.simulator_run = str(launch())
if st.button("Refresh results"):
    st.rerun()
runs = sorted((p for p in RESULTS.glob("run-*") if not (p / "probe.json").exists()), key=lambda path: path.stat().st_mtime, reverse=True) if RESULTS.exists() else []
if not runs:
    st.write("No simulation results yet.")
    st.stop()
chosen = st.selectbox("Simulation run", runs, format_func=lambda path: path.name)
result = read_result(chosen)
if result.get("operation_blocked"):
    st.error("FAIL — the safety wall blocked an external/protected operation and terminated the simulation immediately.")
    st.json(result)
    st.stop()
if "counts" not in result:
    st.write("Simulation running", result)
    st.stop()
for column, (status, count) in zip(st.columns(3), result["counts"].items(), strict=True):
    column.metric(status, count)
st.write(f"{result['scenarios_run']} scenarios · {result['modules_exercised']} of {result['modules_inventoried']} modules/routes exercised")
st.write("Production access attempted:", result["production_access_attempted"])
problems = [r for r in result["results"] if r["status"] != "PASS"]
st.subheader("Warnings and failures")
st.dataframe([{**r, "subsystem": ", ".join(r["subsystem"])} for r in problems], hide_index=True)
with st.expander("All scenario results"):
    st.dataframe([{**r, "subsystem": ", ".join(r["subsystem"])} for r in result["results"]], hide_index=True)
with st.expander("Whole-app module and route coverage"):
    st.dataframe([{**r, "scenarios": len(r["scenarios"])} for r in result["coverage"]], hide_index=True)
st.caption("No production writes, sends, imports, or checkpoint additions are available from this screen.")
