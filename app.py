"""Minimal Streamlit entrypoint during Step 3 of the Jem assessment."""

import streamlit as st

from jem.status import CURRENT_STATUS


st.set_page_config(page_title="Jem overtime early warning", page_icon="⏱️")

st.title("Jem overtime early warning")
st.caption(CURRENT_STATUS.stage)

st.info(
    "CSV ingestion, hours features and the first correlated-hours predictor are implemented "
    "in shared modules. The browser results workflow arrives in a later stage."
)

st.subheader("Current capability")
st.write("This page verifies the local Streamlit project and deployment entrypoint. Genuine current-week predictions can be exported from the command line.")

st.subheader("Not yet available")
st.write(
    "The dashboard does not yet display hours, breach predictions, risk scores, "
    "or supervisor-note classifications. Note validation remains pending."
)

st.subheader("Current method")
st.write(
    "The shared export uses the reference correlated-hours predictor and a fixed "
    "historically selected threshold. A later offline comparison will follow "
    "the predeclared selection policy in "
    "`config/prediction_policy.toml`."
)
