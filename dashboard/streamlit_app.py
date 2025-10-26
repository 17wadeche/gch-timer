import io
import requests
import pandas as pd
import streamlit as st

API_BASE = st.secrets.get("API_BASE", "https://gch-timer-api.onrender.com")
TIMEOUT = 30

st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time")

@st.cache_data(ttl=60)
def fetch_sessions() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(columns=["email","complaint_id","Minutes"])
    # convert and rename
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"] / 60000.0).round(2)
    # keep only desired columns for the main table
    return df[["email","complaint_id","Minutes"]]

@st.cache_data(ttl=60)
def fetch_by_section() -> pd.DataFrame:
    """Optional – used for the ‘by section’ chart if you add the API below."""
    r = requests.get(f"{API_BASE}/sessions_by_section", timeout=TIMEOUT)
    if r.status_code != 200:
        return pd.DataFrame(columns=["email","complaint_id","section","Minutes"])
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(columns=["email","complaint_id","section","Minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"] / 60000.0).round(2)
    return df[["email","complaint_id","section","Minutes"]]

# ----- data -----
df = fetch_sessions()

# KPIs
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total hours", round(df["Minutes"].sum()/60, 2) if not df.empty else 0)
with c2:
    st.metric("Sessions", int(len(df)))
with c3:
    st.metric("Users", int(df["email"].nunique()) if not df.empty else 0)

# Table
st.subheader("Sessions")
st.dataframe(df, use_container_width=True, height=360)

# Charts
st.subheader("Minutes by complaint")
if not df.empty:
    st.bar_chart(df.groupby("complaint_id")["Minutes"].sum().sort_values(ascending=False),
                 use_container_width=True)
else:
    st.info("No complaint data yet.")

st.subheader("Minutes by user")
if not df.empty:
    st.bar_chart(df.groupby("email")["Minutes"].sum().sort_values(ascending=False),
                 use_container_width=True)

# (optional) by section if you wire the API below
by_sec = fetch_by_section()
if not by_sec.empty:
    st.subheader("Minutes by section (within complaint)")
    st.bar_chart(by_sec.groupby("section")["Minutes"].sum().sort_values(ascending=False),
                 use_container_width=True)

# Export
def to_excel(d: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        d.to_excel(w, index=False, sheet_name="sessions")
        d.groupby("complaint_id", as_index=False)["Minutes"].sum() \
         .to_excel(w, index=False, sheet_name="by_complaint")
        d.groupby("email", as_index=False)["Minutes"].sum() \
         .to_excel(w, index=False, sheet_name="by_user")
    return out.getvalue()

if not df.empty:
    st.download_button("Download Excel", to_excel(df),
        file_name="gch_timer.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True)

st.caption("Only active (non-idle) time is counted.")
