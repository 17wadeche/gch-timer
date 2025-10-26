import streamlit as st
import pandas as pd
import io, requests

API_BASE = "https://YOUR-RENDER-APP.onrender.com"  # <- CHANGE THIS

st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time Dashboard")

@st.cache_data(ttl=60)
def fetch_sessions():
    r = requests.get(f"{API_BASE}/sessions", timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(columns=["session_id","email","complaint_id","active_ms","active_minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["active_minutes"] = (df["active_ms"] / 60000).round(2)
    return df

df = fetch_sessions()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total active hours", round(df["active_ms"].sum()/3600000, 2) if not df.empty else 0)
with col2:
    st.metric("Sessions", len(df))
with col3:
    st.metric("Unique users", df["email"].nunique() if not df.empty else 0)

st.subheader("Sessions")
st.dataframe(df, use_container_width=True, height=320)

st.subheader("Active minutes by complaint")
if not df.empty:
    st.bar_chart(df.groupby("complaint_id")["active_minutes"].sum(), use_container_width=True)

st.subheader("Active minutes by user")
if not df.empty:
    st.bar_chart(df.groupby("email")["active_minutes"].sum(), use_container_width=True)

# ---- Excel Download (sessions + summaries) ----
def to_excel(sessions_df):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        sessions_df.to_excel(w, index=False, sheet_name="sessions")
        by_complaint = sessions_df.groupby("complaint_id", as_index=False)["active_minutes"].sum()
        by_user = sessions_df.groupby("email", as_index=False)["active_minutes"].sum()
        by_complaint.to_excel(w, index=False, sheet_name="by_complaint")
        by_user.to_excel(w, index=False, sheet_name="by_user")
    return out.getvalue()

if not df.empty:
    xlsx = to_excel(df)
    st.download_button(
        "Download Excel",
        xlsx,
        file_name="gch_timer.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

st.caption("Data updates every ~60 seconds. Extension only counts active time (no keystrokes/screenshots).")
