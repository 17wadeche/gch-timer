import io
import requests
import pandas as pd
import streamlit as st
API_BASE = st.secrets.get("API_BASE", "https://gch-timer-api.onrender.com")
st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time Dashboard")
@st.cache_data(ttl=60)
def fetch_sessions(api_base: str) -> pd.DataFrame:
    r = requests.get(f"{api_base}/sessions", timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(
            columns=["session_id", "email", "complaint_id", "active_ms", "active_minutes"]
        )
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["active_minutes"] = (df["active_ms"] / 60000.0).round(2)
    return df
try:
    with st.spinner("Loading data from API…"):
        df = fetch_sessions(API_BASE)
except Exception as e:
    st.error(f"Failed to load data from {API_BASE}/sessions")
    st.exception(e)
    st.stop()
col1, col2, col3 = st.columns(3)
with col1:
    total_hours = round(df["active_ms"].sum() / 3_600_000, 2) if not df.empty else 0
    st.metric("Total active hours", total_hours)
with col2:
    st.metric("Sessions", int(len(df)))
with col3:
    unique_users = int(df["email"].nunique()) if not df.empty else 0
    st.metric("Unique users", unique_users)
st.subheader("Sessions")
st.dataframe(df, use_container_width=True, height=320)
st.subheader("Active minutes by complaint")
if not df.empty:
    st.bar_chart(df.groupby("complaint_id")["active_minutes"].sum(), use_container_width=True)
else:
    st.info("No data yet for complaints.")
st.subheader("Active minutes by user")
if not df.empty:
    st.bar_chart(df.groupby("email")["active_minutes"].sum(), use_container_width=True)
else:
    st.info("No data yet for users.")
def to_excel(sessions_df: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        sessions_df.to_excel(w, index=False, sheet_name="sessions")
        sessions_df.groupby("complaint_id", as_index=False)["active_minutes"].sum() \
                   .to_excel(w, index=False, sheet_name="by_complaint")
        sessions_df.groupby("email", as_index=False)["active_minutes"].sum() \
                   .to_excel(w, index=False, sheet_name="by_user")
    return out.getvalue()
if not df.empty:
    st.download_button(
        label="Download Excel",
        data=to_excel(df),
        file_name="gch_timer.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
st.caption("Data refreshes every ~60s. Only active (non-idle) time on tracked pages is counted.")