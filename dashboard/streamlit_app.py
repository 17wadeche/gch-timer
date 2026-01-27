import requests
import pandas as pd
import streamlit as st
import altair as alt
from datetime import timedelta
import io
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
    schema = [
        "session_id", "email", "team", "complaint_id", "start_ts", "active_ms", "idle_ms",
        "Active HH:MM:SS", "Idle HH:MM:SS", "Start", "Active Minutes", "Idle Minutes", "Weekday"
    ]
    try:
        r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
        if r.status_code != 200:
            st.error(f"/sessions failed: {r.status_code} {r.text}")
            return pd.DataFrame(columns=schema)
        df = pd.DataFrame(r.json())
    except Exception as e:
        st.error(f"/sessions failed: {e}")
        return pd.DataFrame(columns=schema)
    if df.empty:
        return pd.DataFrame(columns=schema)
    for col in ("active_ms", "idle_ms"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in ("email", "team", "complaint_id", "session_id"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    df["team"] = df["team"].str.strip().replace("", "Unknown")
    start = pd.to_datetime(df.get("start_ts"), errors="coerce", utc=True)
    df["Start"] = start.dt.tz_convert(TZ_NAME).dt.tz_localize(None)
    df["Active Minutes"] = df["active_ms"] / 60000.0
    df["Idle Minutes"]   = df["idle_ms"] / 60000.0
    df["Active HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    df["Idle HH:MM:SS"]   = df["idle_ms"].apply(fmt_hms_from_ms)
    df["Weekday"]         = df["Start"].apply(to_weekday)
    for c in schema:
        if c not in df.columns:
            df[c] = pd.Series(dtype="object")
    return df[schema]
def _ordinal_word(n: int) -> str:
    d = {1:"first",2:"second",3:"third"}
    if n in d: return d[n]
    return f"{n}th"
def build_excel_bytes(sessions_df: pd.DataFrame,
                      totals_df: pd.DataFrame | None = None,
                      sections_df: pd.DataFrame | None = None,
                      weekday_df: pd.DataFrame | None = None,
                      timeline_df: pd.DataFrame | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        if not sessions_df.empty:
            (sessions_df.sort_values("Start", ascending=False)
                        .to_excel(w, index=False, sheet_name="Sessions"))
        else:
            pd.DataFrame(columns=["Start","Email","Team","Complaint","Active HH:MM:SS","Idle HH:MM:SS"])\
              .to_excel(w, index=False, sheet_name="Sessions")
        if totals_df is not None and not totals_df.empty:
            totals_df.rename(columns={
                "complaint_id":"Complaint",
                "active_ms":"Active (ms)",
                "Total HHMMSS":"Active (HH:MM:SS)"
            }).to_excel(w, index=False, sheet_name="Totals_by_Complaint")
        if sections_df is not None and not sections_df.empty:
            sections_df.rename(columns={
                "complaint_id":"Complaint",
                "section":"Activity",
                "active_ms":"Active (ms)",
                "HH:MM:SS":"Active (HH:MM:SS)"
            }).to_excel(w, index=False, sheet_name="By_Section")
        if weekday_df is not None and not weekday_df.empty:
            weekday_df.rename(columns={
                "active_ms":"Active (ms)",
                "ACTIVE HH:MM:SS":"Active (HH:MM:SS)"
            }).to_excel(w, index=False, sheet_name="Weekday_Totals")
        if timeline_df is not None and not timeline_df.empty:
            timeline_df.to_excel(w, index=False, sheet_name="Activity_Timeline")
    buf.seek(0)
    return buf.read()
@st.cache_data(ttl=60)
def fetch_by_section() -> pd.DataFrame:
    r = requests.get(f"{API_BASE}/sessions_by_section", timeout=TIMEOUT)
    if r.status_code != 200:
        return pd.DataFrame(columns=["email","team","complaint_id","section","active_ms","Minutes"])
    df = pd.DataFrame(r.json())
    if df.empty:
        return pd.DataFrame(columns=["email","team","complaint_id","section","active_ms","Minutes"])
    df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
    df["Minutes"] = (df["active_ms"]/60000.0)
    df["HH:MM:SS"] = df["active_ms"].apply(fmt_hms_from_ms)
    return df[["email","team","complaint_id","section","active_ms","Minutes","HH:MM:SS"]]
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
        return pd.DataFrame(columns=["ts","email","team","complaint_id","section","reason","active_ms","idle_ms","page","session_id"])
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
teams = df["team"].fillna("").replace("", "Unknown")
all_ous = ["All Teams"] + sorted(teams.unique().tolist())
ou_choice = st.selectbox("Team", all_ous, index=0)
with st.sidebar:
    st.header("Filters")
    email_filter = st.text_input("Email contains", "")
    complaint_filter = st.text_input("Complaint/Transaction ID contains", "")
    min_minutes = st.number_input("Min ACTIVE minutes", min_value=0.0, value=0.0, step=0.5)
    if st.button("Force refresh data"):
        for _fn in (fetch_sessions, fetch_by_section, fetch_events_for_complaint, fetch_sections_by_weekday):
            try:
                _fn.clear()
            except Exception:
                pass
        st.rerun()        
    st.divider()
    st.subheader("Admin")
    clear_pw = st.text_input("Clear-all password", type="password")
    confirm_clear = st.checkbox("I understand this deletes ALL records")
    if st.button("Clear ALL data", disabled=not confirm_clear):
        try:
            r = requests.post(f"{API_BASE}/clear", json={"password": clear_pw}, timeout=30)
            if r.status_code == 200:
                st.success("All data cleared.")
                for _fn in (fetch_sessions, fetch_by_section, fetch_events_for_complaint, fetch_sections_by_weekday):
                    try:
                        _fn.clear()
                    except Exception:
                        pass
                st.rerun()
            else:
                st.error(f"Clear failed: {r.status_code} {r.text}")
        except Exception as e:
            st.error(f"Clear failed: {e}")
if ou_choice != "All Teams":
    df = df[df["team"] == ou_choice]
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
display_df = df.rename(columns={"email": "Email", "team": "Team", "complaint_id": "Complaint"})
tmp = display_df.sort_values("Start").copy()
tmp["__occ_n"] = tmp.groupby("Complaint").cumcount() + 1
tmp["Occurrence"] = tmp["__occ_n"].apply(
    lambda n: "" if n == 1 else f"{_ordinal_word(n)} occurrence"
)
display_df = tmp.drop(columns=["__occ_n"])
st.dataframe(
    display_df[[
        "Start", "Email", "Team", "Complaint", "Occurrence",
        "Active HH:MM:SS", "Idle HH:MM:SS"
    ]].sort_values("Start", ascending=False),
    use_container_width=True,
    height=420,
    hide_index=True, 
)
def collapse_activity_blocks(ev: pd.DataFrame, tz_name: str = TZ_NAME) -> pd.DataFrame:
    if ev.empty:
        return pd.DataFrame(columns=[
            "Start","Counted End","Last Event","Activity",
            "Active HH:MM:SS","Idle HH:MM:SS","Ignored HH:MM:SS",
            "Active (ms)","Idle (ms)","Ignored (ms)","Session","Page"
        ])
    ev = ev.copy()
    ev["section"] = ev["section"].fillna("").replace("", "Unlabeled")
    ev = ev.sort_values("ts")
    blocks = []
    cur = None
    for _, r in ev.iterrows():
        sec = r["section"]
        ts  = r["ts"]
        if (cur is None) or (sec != cur["Activity"]):
            if cur is not None:
                counted_ms = cur["Active (ms)"] + cur["Idle (ms)"]
                counted_end = cur["Start"] + pd.to_timedelta(int(counted_ms), unit="ms")
                wall_ms = int((cur["Last Event"] - cur["Start"]).total_seconds() * 1000)
                ignored_ms = max(wall_ms - counted_ms, 0)
                cur["Counted End"] = counted_end
                cur["Ignored (ms)"] = ignored_ms
                blocks.append(cur)
            cur = {
                "Start": ts,
                "Last Event": ts,
                "Activity": sec,
                "Active (ms)": 0,
                "Idle (ms)": 0,
                "Session": r.get("session_id", ""),
                "Page": r.get("page", ""),
            }
        cur["Active (ms)"] += int(r.get("active_ms", 0))
        cur["Idle (ms)"]   += int(r.get("idle_ms", 0))
        cur["Last Event"]   = ts
    if cur is not None:
        counted_ms = cur["Active (ms)"] + cur["Idle (ms)"]
        counted_end = cur["Start"] + pd.to_timedelta(int(counted_ms), unit="ms")
        wall_ms = int((cur["Last Event"] - cur["Start"]).total_seconds() * 1000)
        ignored_ms = max(wall_ms - counted_ms, 0)
        cur["Counted End"] = counted_end
        cur["Ignored (ms)"] = ignored_ms
        blocks.append(cur)
    out = pd.DataFrame(blocks)
    out["Active HH:MM:SS"]  = out["Active (ms)"].apply(fmt_hms_from_ms)
    out["Idle HH:MM:SS"]    = out["Idle (ms)"].apply(fmt_hms_from_ms)
    out["Ignored HH:MM:SS"] = out["Ignored (ms)"].apply(fmt_hms_from_ms)
    for c in ("Start", "Counted End", "Last Event"):
        out[c] = pd.to_datetime(out[c]).dt.tz_convert(tz_name).dt.tz_localize(None)
    return out.sort_values("Start")[
        ["Start","Counted End","Last Event","Activity",
         "Active HH:MM:SS","Idle HH:MM:SS","Ignored HH:MM:SS",
         "Active (ms)","Idle (ms)","Ignored (ms)","Session","Page"]
    ]
st.subheader("Complaint row details")
if df.empty:
    st.info("No data yet.")
else:
    totals_by_c = (
        df.groupby("complaint_id", as_index=False)["active_ms"]
          .sum().sort_values("active_ms", ascending=False)
    )
    all_cids_sorted = totals_by_c["complaint_id"].astype(str).tolist()
    search_q = st.text_input("Search complaint ID", "", placeholder="e.g., 608345634")
    if search_q:
        filtered = [c for c in all_cids_sorted if search_q.lower() in str(c).lower()]
    else:
        filtered = all_cids_sorted
    selected_cid = st.selectbox(
        "Select complaint to view",
        filtered,
        index=0 if filtered else None,
        placeholder="Choose a complaint…",
    )
    if not filtered:
        st.info("No complaints match your search.")
    elif selected_cid:
        sub = df[df["complaint_id"].astype(str) == str(selected_cid)]
        total_ms = int(sub["active_ms"].sum())
        st.markdown(f"**Complaint {selected_cid} — total ACTIVE {fmt_hms_from_ms(total_ms)}**")
        st.markdown("**Timeline (chronological activity blocks)**")
        ev = fetch_events_for_complaint(str(selected_cid))
        if ev.empty:
            st.caption("No activity events recorded for this complaint.")
        else:
            blocks = collapse_activity_blocks(ev, TZ_NAME)
            display_cols = [
                "Start (local)", "End (local)", "Activity",
                "Active HH:MM:SS", "Idle HH:MM:SS", "Page"
            ]
            display_blocks = (
                blocks.rename(columns={
                    "Start": "Start (local)",
                    "Counted End": "End (local)",   # <- use the counted end
                })[display_cols]
            )
            st.dataframe(
                display_blocks,
                use_container_width=True,
                height=280,
                hide_index=True, 
            )
            st.markdown("**Activities (totals)**")
            totals = (ev.assign(section=ev["section"].fillna("").replace("", "Unlabeled"))
                        .groupby("section", as_index=False)["active_ms"].sum()
                        .sort_values("active_ms", ascending=False))
            lines = "\n".join(
                f"- {row.section} {fmt_hms_from_ms(int(row.active_ms))}"
                for _, row in totals.iterrows()
            )
            st.markdown(lines)
sect = fetch_by_section()
if not sect.empty:
    if ou_choice != "All Teams":
        sect = sect[sect["team"] == ou_choice]
    if email_filter:
        sect = sect[sect["email"].astype(str).str.contains(email_filter, case=False, na=False)]
    if complaint_filter:
        sect = sect[sect["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
    sect = sect[sect["Minutes"] >= float(min_minutes)]
    sect = sect[sect["complaint_id"].astype(str).str.match(r"^[67]\d+", na=False)]
    totals = (sect.groupby("complaint_id", as_index=False)["active_ms"].sum())
    totals["Total HHMMSS"] = totals["active_ms"].apply(fmt_hms_from_ms)
    mean_ms = int(totals["active_ms"].mean()) if not totals.empty else 0
    avg_df = pd.DataFrame({"y": [mean_ms], "label": [f"Avg {fmt_hms_from_ms(mean_ms)}"]})
    avg_rule = alt.Chart(avg_df).mark_rule(strokeDash=[6,4]).encode(y="y:Q")
    avg_text = alt.Chart(avg_df).mark_text(align="left", dx=6, dy=-6).encode(y="y:Q", text="label:N")
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
    st.altair_chart(bars + labels + avg_rule + avg_text, use_container_width=True)
wkdf = fetch_sections_by_weekday()
allowed_cids = set(df["complaint_id"].astype(str).unique())
if not wkdf.empty:
    wkdf = wkdf[wkdf["complaint_id"].astype(str).isin(allowed_cids)]
    if complaint_filter:
        wkdf = wkdf[wkdf["complaint_id"].astype(str)
                    .str.contains(complaint_filter, case=False, na=False)]
    wkdf = wkdf[wkdf["complaint_id"].astype(str).str.match(r"^[67]\d+", na=False)].copy()
    def map_bucket(s: str) -> str:
        if not isinstance(s, str): return "PLI Level"
        s = s.strip().lower()
        if s.startswith("reportability"):      return "Reportability"
        if s.startswith("regulatory report"):  return "Regulatory Report"
        if s.startswith("regulatory inquiry"): return "Regulatory Inquiry"
        if s.startswith("product analysis"):   return "Product Analysis"
        if s.startswith("investigation"):      return "Investigation"
        if s.startswith("communication"):      return "Communication"
        if s.startswith("task"):               return "Task"
        return "PLI Level"
    wkdf.loc[:, "bucket"] = wkdf["section"].apply(map_bucket)
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
        st.subheader(day)
        day_df = wkdf[wkdf["weekday"] == day]
        if day_df.empty:
            st.info(f"No data yet for {day}.")
            continue
        agg = (day_df.groupby(["complaint_id","bucket"], as_index=False)["active_ms"].sum())
        agg["HHMMSS"] = agg["active_ms"].apply(fmt_hms_from_ms)
        totals_day = agg.groupby("complaint_id", as_index=False)["active_ms"].sum()
        totals_day["Total HHMMSS"] = totals_day["active_ms"].apply(fmt_hms_from_ms)
        mean_ms_day = int(totals_day["active_ms"].mean()) if not totals_day.empty else 0
        avg_day_df = pd.DataFrame({"y": [mean_ms_day], "label": [f"Avg {fmt_hms_from_ms(mean_ms_day)}"]})
        avg_day_rule = alt.Chart(avg_day_df).mark_rule(strokeDash=[6,4]).encode(y="y:Q")
        avg_day_text = alt.Chart(avg_day_df).mark_text(align="left", dx=6, dy=-6)\
                                            .encode(y="y:Q", text="label:N")
        stacked = alt.Chart(agg).mark_bar().encode(
            x=alt.X("complaint_id:N", title="Complaint", sort="-y"),
            y=alt.Y("sum(active_ms):Q", axis=axis),
            color=alt.Color("bucket:N",
                            scale=alt.Scale(domain=palette_domain, range=palette_range),
                            title="Activity"),
            tooltip=[
                alt.Tooltip("complaint_id:N", title="Complaint"),
                alt.Tooltip("bucket:N",       title="Activity"),
                alt.Tooltip("HHMMSS:N",       title="Active (HH:MM:SS)")
            ]
        ).properties(height=320, width="container")
        labels_day = alt.Chart(totals_day).mark_text(dy=-6).encode(
            x="complaint_id:N",
            y="active_ms:Q",
            text=alt.Text("Total HHMMSS:N")
        )
        st.altair_chart(stacked + labels_day + avg_day_rule + avg_day_text, use_container_width=True)
else:
    for day in ["Monday","Tuesday","Wednesday","Thursday","Friday"]:
        st.subheader(day)
        st.info(f"No data yet for {day}.")
st.subheader("Export")
sessions_view = display_df[["Start","Email","Team","Complaint","Active HH:MM:SS","Idle HH:MM:SS"]].copy()
weekday_totals_df = (
    df.assign(Weekday=pd.Categorical(
        df["Weekday"],
        categories=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
        ordered=True
    ))
    .groupby("Weekday", as_index=False)["active_ms"].sum()
)
weekday_totals_df["ACTIVE HH:MM:SS"] = weekday_totals_df["active_ms"].apply(fmt_hms_from_ms)
timeline_rows = []
visible_complaints = df["complaint_id"].dropna().astype(str).unique().tolist()
for cid in visible_complaints:
    ev = fetch_events_for_complaint(cid)
    if ev.empty:
        continue
    blocks = collapse_activity_blocks(ev, TZ_NAME)
    if not blocks.empty:
        blocks = blocks.copy()
        blocks.insert(0, "Complaint", cid)
        blocks = blocks.rename(columns={"Counted End": "End"})
        blocks = blocks[[
            "Complaint","Start","End","Activity",
            "Active HH:MM:SS","Idle HH:MM:SS",
            "Active (ms)","Idle (ms)","Session","Page"
        ]]
        timeline_rows.append(blocks)
timeline_df = (
    pd.concat(timeline_rows, ignore_index=True)
    if timeline_rows else
    pd.DataFrame(
        columns=[
            "Complaint","Start","End","Activity",
            "Active HH:MM:SS","Idle HH:MM:SS",
            "Active (ms)","Idle (ms)","Session","Page"
        ]
    )
)
excel_bytes = build_excel_bytes(
    sessions_df=sessions_view,
    totals_df=locals().get("totals", None),  # totals per complaint (from the bar chart section)
    sections_df=locals().get("sect", None),  # sessions_by_section (raw)
    weekday_df=weekday_totals_df,
    timeline_df=timeline_df,                 # <<< NEW timeline sheet
)
st.download_button(
    label="⬇️ Export current view (Excel)",
    data=excel_bytes,
    file_name="gch_current_view.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
st.caption("Active time excludes ≥30s idle gaps; 30s–5m are counted as Idle; gaps ≥5m are ignored.")