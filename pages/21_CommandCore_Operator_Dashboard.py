from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CommandCore My Work", page_icon="🧭", layout="wide")

# The former Operator Dashboard has been consolidated into My Work.
# Keep this route as a compatibility redirect so old bookmarks and deep links do not break.
st.switch_page("pages/35_CommandCore_My_Work.py")
