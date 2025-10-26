import io
import requests
import pandas as pd
import streamlit as st
from pathlib import Path
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
        return pd.DataFrame(columns=["email", "complaint_id", "Minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"] / 60000.0).round(2)
    return df[["email", "complaint_id", "Minutes"]]
@st.cache_data(ttl=60)
def fetch_by_section() -> pd.DataFrame:
    try:
        r = requests.get(f"{API_BASE}/sessions_by_section", timeout=TIMEOUT)
        if r.status_code != 200:
            return pd.DataFrame(columns=["email", "complaint_id", "section", "Minutes"])
        df = pd.DataFrame(r.json())
        if df.empty:
            return pd.DataFrame(columns=["email", "complaint_id", "section", "Minutes"])
        df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
        df["Minutes"] = (df["active_ms"] / 60000.0).round(2)
        return df[["email", "complaint_id", "section", "Minutes"]]
    except Exception:
        return pd.DataFrame(columns=["email", "complaint_id", "section", "Minutes"])
def _normalize_email_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()
@st.cache_data(ttl=300)
def load_default_ou_map() -> pd.DataFrame:
    p = Path(__file__).with_name("ou.csv")
    if not p.exists():
        return pd.DataFrame(columns=["email", "ou"])
    df = pd.read_csv(p)
    if "email" not in df.columns or "ou" not in df.columns:
        return pd.DataFrame(columns=["email", "ou"])
    df["email"] = _normalize_email_series(df["email"])
    df["ou"] = df["ou"].astype(str).str.strip()
    return df[["email", "ou"]]
def apply_ou(df_sessions: pd.DataFrame, ou_map: pd.DataFrame) -> pd.DataFrame:
    if df_sessions.empty:
        out = df_sessions.copy()
        out["OU"] = pd.Series(dtype=str)
        return out
    m = ou_map.copy()
    m["email"] = _normalize_email_series(m["email"])
    s = df_sessions.copy()
    s["email_norm"] = _normalize_email_series(s["email"])
    s = s.merge(m.rename(columns={"email": "email_norm"}), on="email_norm", how="left")
    s["OU"] = s["ou"].fillna("Unknown").astype(str)
    s = s.drop(columns=["email_norm", "ou"])
    return s
with st.sidebar:
    st.header("Org Unit (OU)")
    uploaded_map = st.file_uploader("Upload OU mapping CSV (columns: email, ou)", type=["csv"])
    if uploaded_map:
        ou_map = pd.read_csv(uploaded_map)
    else:
        ou_map = load_default_ou_map()
try:
    df = fetch_sessions()
except Exception as e:
    st.error("Failed to load session data.")
    st.exception(e)
    st.stop()
df = apply_ou(df, ou_map)
all_ous = sorted(df["OU"].dropna().unique().tolist()) if not df.empty else []
default_label = "All OUs"
selection = st.selectbox("Select OU", [default_label] + all_ous, index=0)
if selection != default_label:
    df = df[df["OU"] == selection]
with st.sidebar:
    st.header("Filters")
    email_filter = st.text_input("Email contains", "")
    complaint_filter = st.text_input("Complaint/Transaction ID contains", "")
    min_minutes = st.number_input("Min minutes", min_value=0.0, value=0.0, step=0.5)
    if st.button("Force refresh data"):
        fetch_sessions.clear()
        fetch_by_section.clear()
        st.experimental_rerun()
if email_filter:
    df = df[df["email"].astype(str).str.contains(email_filter, case=False, na=False)]
if complaint_filter:
    df = df[df["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
df = df[df["Minutes"] >= float(min_minutes)]
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total hours", round(df["Minutes"].sum() / 60.0, 2) if not df.empty else 0)
with c2:
    st.metric("Sessions", int(len(df)))
with c3:
    st.metric("Users", int(df["email"].nunique()) if not df.empty else 0)
st.subheader("Sessions")
st.dataframe(df[["email", "complaint_id", "OU", "Minutes"]], use_container_width=True, height=380)
st.subheader("Minutes by complaint")
if not df.empty:
    st.bar_chart(
        df.groupby("complaint_id")["Minutes"].sum().sort_values(ascending=False),
        use_container_width=True,
    )
else:
    st.info("No complaint data yet.")
st.subheader("Minutes by user")
if not df.empty:
    st.bar_chart(
        df.groupby("email")["Minutes"].sum().sort_values(ascending=False),
        use_container_width=True,
    )
by_sec = fetch_by_section()
if not by_sec.empty:
    by_sec = apply_ou(by_sec, ou_map)
    if selection != default_label:
        by_sec = by_sec[by_sec["OU"] == selection]
    if email_filter:
        by_sec = by_sec[by_sec["email"].astype(str).str.contains(email_filter, case=False, na=False)]
    if complaint_filter:
        by_sec = by_sec[by_sec["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
    by_sec = by_sec[by_sec["Minutes"] >= float(min_minutes)]

    if not by_sec.empty:
        st.subheader("Minutes by section (within complaint)")
        st.bar_chart(
            by_sec.groupby("section")["Minutes"].sum().sort_values(ascending=False),
            use_container_width=True,
        )
st.caption(
    "Upload an OU mapping CSV or include 'dashboard/ou.csv' (columns: email, ou). "
    "Only active (non-idle) time is counted."
)