import streamlit as st

st.title("🎯 GEX / DEX / OI Dashboard")

ticker = st.text_input(
    "티커",
    value="SPY"
)

if st.button("분석"):
    st.success(f"{ticker} 분석 시작")
