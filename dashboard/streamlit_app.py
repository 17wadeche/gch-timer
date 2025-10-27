import requests
import pandas as pd
import streamlit as st
import altair as alt
API_BASE = st.secrets.get("API_BASE", "https://gch-timer-api.onrender.com")
TIMEOUT = 30
st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time")
@st.cache_data(ttl=60)
def fetch_sessions() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    schema = ["email", "ou", "complaint_id", "start_ts", "active_ms", "idle_ms",
              "Minutes", "Idle Minutes", "Start"]
    if df.empty:
        return pd.DataFrame(columns=schema)
    for col in ("active_ms", "idle_ms"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"] / 60000.0).round(2)
    df["Idle Minutes"] = (df["idle_ms"] / 60000.0).round(2)
    df["Start"] = pd.to_datetime(df.get("start_ts"), errors="coerce")
    for c in schema:
        if c not in df.columns:
            df[c] = pd.Series(dtype="float64" if "Minutes" in c else "object")
    return df[schema]
@st.cache_data(ttl=60)
def fetch_by_section() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions_by_section", timeout=TIMEOUT)
    if r.status_code != 200: 
        return pd.DataFrame(columns=["email","ou","complaint_id","section","Minutes"])
    df = pd.DataFrame(r.json())
    if df.empty: 
        return pd.DataFrame(columns=["email","ou","complaint_id","section","Minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"]/60000.0).round(2)
    return df[["email","ou","complaint_id","section","Minutes"]]
df = fetch_sessions()
all_ous = ["All OUs"] + sorted(df["ou"].fillna("Unknown").unique().tolist()) if not df.empty else ["All OUs"]
ou_choice = st.selectbox("Operating Unit (OU)", all_ous, index=0)
with st.sidebar:
    st.header("Filters")
    email_filter = st.text_input("Email contains", "")
    complaint_filter = st.text_input("Complaint/Transaction ID contains", "")
    min_minutes = st.number_input("Min active minutes", min_value=0.0, value=0.0, step=0.5)
    if st.button("Force refresh data"):
        fetch_sessions.clear(); fetch_by_section.clear(); st.experimental_rerun()
if ou_choice != "All OUs":
    df = df[df["ou"] == ou_choice]
if email_filter:
    df = df[df["email"].astype(str).str.contains(email_filter, case=False, na=False)]
if complaint_filter:
    df = df[df["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
df = df[df["Minutes"] >= float(min_minutes)]
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("Total ACTIVE hours", round(df["Minutes"].sum()/60.0, 2) if not df.empty else 0)
with c2: st.metric("Total IDLE hours",   round(df["Idle Minutes"].sum()/60.0, 2) if not df.empty else 0)
with c3: st.metric("Sessions", int(len(df)))
with c4: st.metric("Users", int(df["email"].nunique()) if not df.empty else 0)
st.subheader("Sessions")
st.dataframe(
    df[["Start","email","ou","complaint_id","Minutes","Idle Minutes"]].sort_values("Start", ascending=False),
    use_container_width=True, height=420
)
st.subheader("Active minutes by complaint")
if not df.empty:
    st.bar_chart(
        df.groupby("complaint_id")["Minutes"].sum().sort_values(ascending=False),
        use_container_width=True,
    )
else:
    st.info("No data yet.")
sect = fetch_by_section()
if not sect.empty:
    if ou_choice != "All OUs":
        sect = sect[sect["ou"] == ou_choice]
    if email_filter:
        sect = sect[sect["email"].astype(str).str.contains(email_filter, case=False, na=False)]
    if complaint_filter:
        sect = sect[sect["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
    sect = sect[sect["Minutes"] >= float(min_minutes)]
    def map_bucket(s: str) -> str:
        if not isinstance(s,str): return "Other"
        s=s.strip().lower()
        if s.startswith("reportability"):         return "Reportability"
        if s.startswith("regulatory report"):     return "Regulatory Report"
        if s.startswith("regulatory inquiry"):    return "Regulatory Inquiry"
        if s.startswith("product analysis"):      return "Product Analysis"
        if s.startswith("investigations"):        return "Investigations"
        if s.startswith("communications"):        return "Communications"
        if s.startswith("tasks"):                 return "Tasks"
        return "Other"
    sect["bucket"] = sect["section"].apply(map_bucket)
    palette_domain = ["Reportability","Regulatory Report","Regulatory Inquiry",
                      "Product Analysis","Investigations","Communications","Tasks","Other"]
    palette_range  = ["#ff7f0e","#1f77b4","#2ca02c",
                      "#9467bd","#d62728","#8c564b","#e377c2","#7f7f7f"]
    stacked = alt.Chart(sect).mark_bar().encode(
        x=alt.X("complaint_id:N", title="Complaint / Transaction", sort="-y"),
        y=alt.Y("sum(Minutes):Q", title="Active Minutes"),
        color=alt.Color("bucket:N", scale=alt.Scale(domain=palette_domain, range=palette_range), title="Activity"),
        tooltip=["complaint_id","bucket","sum(Minutes)"]
    ).properties(height=380, width="container")
    totals = (sect.groupby("complaint_id")["Minutes"].sum()
                .reset_index().rename(columns={"Minutes":"Total"}))
    text = alt.Chart(totals).mark_text(dy=-5).encode(
        x="complaint_id:N",
        y="Total:Q",
        text=alt.Text("Total:Q", format=".1f")
    )
    st.subheader("Active minutes by activity within complaint")
    st.altair_chart(stacked + text, use_container_width=True)
st.caption("Active minutes exclude ≥30s idle gaps; 30s–5m are counted as Idle Minutes; gaps ≥5m are ignored.")