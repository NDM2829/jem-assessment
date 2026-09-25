"""Minimal Streamlit entrypoint during Step 2 of the Jem assessment."""

import streamlit as st

from jem.status import CURRENT_STATUS


st.set_page_config(page_title="Jem overtime early warning", page_icon="⏱️")

st.title("Jem overtime early warning")
st.caption(CURRENT_STATUS.stage)

st.info(
    "CSV ingestion and validation are implemented in the shared pipeline. "
    "The browser upload workflow arrives in a later stage; the first real predictor arrives in Step 3."
)

st.subheader("Current capability")
st.write("This page verifies the local Streamlit project and deployment entrypoint. The bundled CSV export loads through the shared ingestion pipeline.")

st.subheader("Not yet available")
st.write(
    "No hours, breach predictions, risk scores, supervisor-note classifications, "
    "or model validation results are produced in this stage."
)

st.subheader("Decision already fixed")
st.write(
    "The first working method will be the reference correlated-hours predictor. "
    "A later offline comparison will follow the predeclared selection policy in "
    "`config/prediction_policy.toml`."
)
