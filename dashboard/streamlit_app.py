import requests
import pandas as pd
import streamlit as st
import altair as alt
from datetime import timedelta
API_BASE = st.secrets.get("API_BASE", "https://gch-timer-api.onrender.com")
TIMEOUT = 30
TZ_NAME = "America/Chicago"
st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time")
def fmt_hms_from_ms(ms: int | float) -> str:
    ms = 0 if pd.isna(ms) else int(ms)
    s = max(ms, 0) // 1000
    return str(timedelta(seconds=int(s)))
def fmt_hms_from_minutes(minutes: float) -> str:
    return str(timedelta(seconds=int(round((minutes or 0) * 60))))
def to_weekday(dt: pd.Timestamp) -> str:
    if pd.isna(dt):
        return ""
    return dt.day_name()
@st.cache_data(ttl=60)
def fetch_sessions() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    schema = ["session_id","email","ou","complaint_id","start_ts","active_ms","idle_ms",
              "Active HH:MM:SS","Idle HH:MM:SS","Start","Active Minutes","Idle Minutes","Weekday"]
    if df.empty:
        return pd.DataFrame(columns=schema)
    for col in ("active_ms", "idle_ms"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    start = pd.to_datetime(df.get("start_ts"), errors="coerce", utc=True)
    df["Start"] = start.dt.tz_convert(TZ_NAME)
    df["Start"] = df["Start"].dt.tz_localize(None)
    df["Active Minutes"] = (df["active_ms"] / 60000.0)
    df["Idle Minutes"] = (df["idle_ms"] / 60000.0)
    df["Active HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    df["Idle HH:MM:SS"] = df["idle_ms"].apply(fmt_hms_from_ms)
    df["Weekday"] = df["Start"].apply(to_weekday)
    for c in schema:
        if c not in df.columns:
            df[c] = pd.Series(dtype="object")
    return df[schema]
@st.cache_data(ttl=60)
def fetch_by_section() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions_by_section", timeout=TIMEOUT)
    if r.status_code != 200:
        return pd.DataFrame(columns=["email","ou","complaint_id","section","active_ms","Minutes"])
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(columns=["email","ou","complaint_id","section","active_ms","Minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"]/60000.0)
    df["HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    return df[["email","ou","complaint_id","section","active_ms","Minutes","HH:MM:SS"]]
@st.cache_data(ttl=60)
def fetch_sections_by_weekday() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sections_by_weekday", timeout=TIMEOUT)
    if r.status_code != 200:
        return pd.DataFrame(columns=["complaint_id","section","weekday","active_ms"])
    df = pd.DataFrame(r.json())
    if df.empty:
        return df
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    cat = pd.CategoricalDtype(
        categories=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
        ordered=True
    )
    df["weekday"] = df["weekday"].astype(cat)
    return df
@st.cache_data(ttl=30)
def fetch_events_for_complaint(complaint_id: str) -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/events", params={"complaint_id": complaint_id}, timeout=TIMEOUT)
    if r.status_code != 200:
        return pd.DataFrame(columns=["ts","email","ou","complaint_id","section","reason","active_ms","idle_ms","page","session_id"])
    df = pd.DataFrame(r.json())
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.tz_convert(TZ_NAME)
    for c in ("active_ms","idle_ms"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["Active HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    df["Idle HH:MM:SS"] = df["idle_ms"].apply(fmt_hms_from_ms)
    return df.sort_values("ts")
df = fetch_sessions()
all_ous = ["All OUs"] + sorted(df["ou"].fillna("Unknown").unique().tolist()) if not df.empty else ["All OUs"]
ou_choice = st.selectbox("Operating Unit (OU)", all_ous, index=0)
with st.sidebar:
    st.header("Filters")
    email_filter = st.text_input("Email contains", "")
    complaint_filter = st.text_input("Complaint/Transaction ID contains", "")
    min_minutes = st.number_input("Min ACTIVE minutes", min_value=0.0, value=0.0, step=0.5)
    if st.button("Force refresh data"):
        fetch_sessions.clear(); fetch_by_section.clear(); fetch_events_for_complaint.clear(); fetch_sections_by_weekday.clear(); st.experimental_rerun()
if ou_choice != "All OUs":
    df = df[df["ou"] == ou_choice]
if email_filter:
    df = df[df["email"].astype(str).str.contains(email_filter, case=False, na=False)]
if complaint_filter:
    df = df[df["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
df = df[df["Active Minutes"] >= float(min_minutes)]
df = df[df["complaint_id"].astype(str).str.match(r"^[67]\d+", na=False)]
total_active_ms = int(df["active_ms"].sum()) if not df.empty else 0
total_idle_ms   = int(df["idle_ms"].sum()) if not df.empty else 0
sessions_count  = int(len(df))
users_count     = int(df["email"].nunique()) if not df.empty else 0
avg_active_ms = int(total_active_ms / sessions_count) if sessions_count else 0
avg_idle_ms   = int(total_idle_ms / sessions_count) if sessions_count else 0
c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1: st.metric("Total ACTIVE", fmt_hms_from_ms(total_active_ms))
with c2: st.metric("Total IDLE",   fmt_hms_from_ms(total_idle_ms))
with c3: st.metric("Avg ACTIVE / session", fmt_hms_from_ms(avg_active_ms))
with c4: st.metric("Avg IDLE / session",   fmt_hms_from_ms(avg_idle_ms))
with c5: st.metric("Sessions", sessions_count)
with c6: st.metric("Users", users_count)
st.subheader("Sessions")
display_df = df.rename(columns={"email": "Email", "ou": "OU", "complaint_id": "Complaint"})
st.dataframe(
    display_df[["Start", "Email", "OU", "Complaint", "Active HH:MM:SS", "Idle HH:MM:SS"]]
        .sort_values("Start", ascending=False),
    use_container_width=True,
    height=420,
    hide_index=True, 
)
st.subheader("Complaint row details")
if df.empty:
    st.info("No data yet.")
else:
    order = (df.groupby("complaint_id")["active_ms"].sum()
               .sort_values(ascending=False).index.tolist())
    for cid in order:
        sub = df[df["complaint_id"] == cid]
        total_ms = int(sub["active_ms"].sum())
        with st.expander(f"Complaint {cid} — total ACTIVE {fmt_hms_from_ms(total_ms)}"):
            st.markdown("**Sessions**")
            show = (sub[["Start","email","ou","session_id","Active HH:MM:SS","Idle HH:MM:SS"]]
                    .sort_values("Start", ascending=False)
                    .rename(columns={"email":"Email","ou":"OU","session_id":"Session"}))
            st.dataframe(show, use_container_width=True, height=200)
            ev = fetch_events_for_complaint(cid)
            if not ev.empty:
                totals = (ev.assign(section=ev["section"].fillna("").replace("", "Unlabeled"))
                            .groupby("section", as_index=False)["active_ms"].sum()
                            .sort_values("active_ms", ascending=False))
                st.markdown("**Activities (totals)**")
                lines = "\n".join(
                    f"- {row.section} {fmt_hms_from_ms(int(row.active_ms))}"
                    for _, row in totals.iterrows()
                )
                st.markdown(lines)
            if ev.empty:
                st.caption("No activity events recorded for this complaint.")
            else:
                st.markdown("**Timeline (ordered)**")
                timeline = ev[["ts","section","reason","Active HH:MM:SS","Idle HH:MM:SS","session_id","page"]].copy()
                timeline = timeline.rename(columns={
                    "ts":"Timestamp", "section":"Activity", "reason":"Reason", "session_id":"Session"
                })
                st.dataframe(timeline, use_container_width=True, height=260)
sect = fetch_by_section()
if not sect.empty:
    if ou_choice != "All OUs":
        sect = sect[sect["ou"] == ou_choice]
    if email_filter:
        sect = sect[sect["email"].astype(str).str.contains(email_filter, case=False, na=False)]
    if complaint_filter:
        sect = sect[sect["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
    sect = sect[sect["Minutes"] >= float(min_minutes)]
    sect = sect[sect["complaint_id"].astype(str).str.match(r"^[67]\d+", na=False)]
    totals = (sect.groupby("complaint_id", as_index=False)["active_ms"].sum())
    totals["Total HHMMSS"] = totals["active_ms"].apply(fmt_hms_from_ms)
    axis = alt.Axis(
        title="Active (HH:MM:SS)",
        labelExpr=(
            "floor(datum.value/3600000) + ':' + "
            "pad(floor((datum.value%3600000)/60000), 2) + ':' + "
            "pad(floor((datum.value%60000)/1000), 2)"
        )
    )
    bars = alt.Chart(totals).mark_bar().encode(
        x=alt.X("complaint_id:N", title="Complaint", sort="-y"),
        y=alt.Y("active_ms:Q", axis=axis),
        tooltip=[
            alt.Tooltip("complaint_id:N", title="Complaint"),
            alt.Tooltip("Total HHMMSS:N", title="Active (HH:MM:SS)")
        ]
    ).properties(height=360, width="container")
    labels = alt.Chart(totals).mark_text(dy=-6).encode(
        x="complaint_id:N",
        y="active_ms:Q",
        text=alt.Text("Total HHMMSS:N")
    )
    st.subheader("Activity level (totals per complaint)")
    st.altair_chart(bars + labels, use_container_width=True)
wkdf = fetch_sections_by_weekday()
if not wkdf.empty:
    if complaint_filter:
        wkdf = wkdf[wkdf["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
    wkdf = wkdf[wkdf["complaint_id"].astype(str).str.match(r"^[67]\d+", na=False)]
    def map_bucket(s: str) -> str:
        if not isinstance(s,str): return "PLI Level"
        s=s.strip().lower()
        if s.startswith("reportability"):         return "Reportability"
        if s.startswith("regulatory report"):     return "Regulatory Report"
        if s.startswith("regulatory inquiry"):    return "Regulatory Inquiry"
        if s.startswith("product analysis"):      return "Product Analysis"
        if s.startswith("investigation"):         return "Investigation"
        if s.startswith("communication"):         return "Communication"
        if s.startswith("task"):                  return "Task"
        return "PLI Level"
    wkdf["bucket"] = wkdf["section"].apply(map_bucket)
    palette_domain = ["Reportability","Regulatory Report","Regulatory Inquiry",
                      "Product Analysis","Investigation","Communication","Task","PLI Level"]
    palette_range  = ["#ff7f0e","#1f77b4","#2ca02c",
                      "#9467bd","#d62728","#8c564b","#e377c2","#7f7f7f"]
    axis = alt.Axis(
        title="Active (HH:MM:SS)",
        labelExpr=(
            "floor(datum.value/3600000) + ':' + "
            "pad(floor((datum.value%3600000)/60000), 2) + ':' + "
            "pad(floor((datum.value%60000)/1000), 2)"
        )
    )
    for day in ["Monday","Tuesday","Wednesday","Thursday","Friday"]:
        day_df = wkdf[wkdf["weekday"] == day]
        if day_df.empty:
            continue
        agg = (day_df.groupby(["complaint_id","bucket"], as_index=False)["active_ms"].sum())
        agg["HHMMSS"] = agg["active_ms"].apply(fmt_hms_from_ms)
        totals = (agg.groupby("complaint_id", as_index=False)["active_ms"].sum())
        totals["Total HHMMSS"] = totals["active_ms"].apply(fmt_hms_from_ms)
        stacked = alt.Chart(agg).mark_bar().encode(
            x=alt.X("complaint_id:N", title="Complaint", sort="-y"),
            y=alt.Y("sum(active_ms):Q", axis=axis),
            color=alt.Color("bucket:N", scale=alt.Scale(domain=palette_domain, range=palette_range), title="Activity"),
            tooltip=[
                alt.Tooltip("complaint_id:N", title="Complaint"),
                alt.Tooltip("bucket:N", title="Activity"),
                alt.Tooltip("HHMMSS:N", title="Active (HH:MM:SS)")
            ]
        ).properties(height=320, width="container")
        labels = alt.Chart(totals).mark_text(dy=-6).encode(
            x="complaint_id:N",
            y="active_ms:Q",
            text=alt.Text("Total HHMMSS:N")
        )
        st.subheader(f"{day}")
        st.altair_chart(stacked + labels, use_container_width=True)
st.caption("Active time excludes ≥30s idle gaps; 30s–5m are counted as Idle; gaps ≥5m are ignored.")