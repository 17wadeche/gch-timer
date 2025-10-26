import io
import time
import requests
import pandas as pd
import streamlit as st

# ============ Config ============
# Prefer a secret if you set one in Streamlit → Settings → Secrets
API_BASE = st.secrets.get("API_BASE", "https://gch-timer-api.onrender.com")
TIMEOUT = 40
RETRIES = 3

st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time Dashboard")

# Small log helper so you can see timings inline
def dbg(msg: str):
    st.write(f"🔎 {msg}")

# ---------- Health check ----------
@st.cache_data(ttl=30)
def api_health():
    t0 = time.time()
    r = requests.get(f"{API_BASE}/", timeout=TIMEOUT)
    ms = int((time.time() - t0) * 1000)
    return r.status_code, r.text, ms

# ---------- Data fetch ----------
@st.cache_data(ttl=60)
def fetch_sessions() -> pd.DataFrame:
    """Fetch aggregated sessions and compute minutes."""
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            t0 = time.time()
            r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
            r.raise_for_status()
            ms = int((time.time() - t0) * 1000)
            dbg(f"/sessions {r.status_code} in {ms} ms")

            df = pd.DataFrame(r.json())
            if df.empty:
                return pd.DataFrame(
                    columns=["session_id", "email", "complaint_id", "active_ms", "active_minutes"]
                )
            df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
            df["active_minutes"] = (df["active_ms"] / 60000.0).round(2)
            return df
        except Exception as e:
            last_err = e
            dbg(f"Attempt {attempt} failed: {e}")
            time.sleep(1.5 * attempt)
    raise last_err

# ---------- UI: health ----------
with st.spinner("Checking API health…"):
    try:
        code, text, ms = api_health()
        st.success(f"API health: {code} in {ms} ms")
    except Exception as e:
        st.error(f"Could not reach API root {API_BASE}/")
        st.exception(e)
        st.stop()

# Sidebar filters / actions
with st.sidebar:
    st.header("Filters")
    st.caption("Use these to narrow the table & charts.")
    email_filter = st.text_input("Email contains", "")
    complaint_filter = st.text_input("Complaint/Transaction ID contains", "")
    min_minutes = st.number_input("Min active minutes", min_value=0.0, value=0.0, step=0.5)
    st.divider()
    if st.button("Force refresh data"):
        fetch_sessions.clear()   # clear cache
        st.experimental_rerun()

# ---------- Data ----------
with st.spinner("Loading session data…"):
    try:
        df = fetch_sessions()
    except Exception as e:
        st.error(f"Failed to load {API_BASE}/sessions")
        st.exception(e)
        st.stop()

# Apply filters
if email_filter:
    df = df[df["email"].astype(str).str.contains(email_filter, case=False, na=False)]
if complaint_filter:
    df = df[df["complaint_id"].astype(str).str.contains(complaint_filter, case=False, na=False)]
df = df[df["active_minutes"] >= float(min_minutes)]

# ---------- KPIs ----------
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total active hours", round(df["active_ms"].sum() / 3_600_000, 2) if not df.empty else 0)
with c2:
    st.metric("Sessions", int(len(df)))
with c3:
    st.metric("Unique users", int(df["email"].nunique()) if not df.empty else 0)
with c4:
    st.metric("Unique complaints", int(df["complaint_id"].nunique()) if not df.empty else 0)

# ---------- Table ----------
st.subheader("Sessions")
st.dataframe(df, use_container_width=True, height=360)

# ---------- Charts ----------
st.subheader("Active minutes by complaint")
if not df.empty:
    st.bar_chart(df.groupby("complaint_id")["active_minutes"].sum().sort_values(ascending=False), use_container_width=True)
else:
    st.info("No data yet for complaints.")

st.subheader("Active minutes by user")
if not df.empty:
    st.bar_chart(df.groupby("email")["active_minutes"].sum().sort_values(ascending=False), use_container_width=True)
else:
    st.info("No data yet for users.")

# ---------- Excel export ----------
def to_excel(sessions_df: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        sessions_df.to_excel(w, index=False, sheet_name="sessions")
        sessions_df.groupby("complaint_id", as_index=False)["active_minutes"].sum() \
                   .sort_values("active_minutes", ascending=False) \
                   .to_excel(w, index=False, sheet_name="by_complaint")
        sessions_df.groupby("email", as_index=False)["active_minutes"].sum() \
                   .sort_values("active_minutes", ascending=False) \
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

st.caption(
    "Data refreshes every ~60s. Only active (non-idle) time on tracked pages is counted. "
    "Set API_BASE in Streamlit Secrets to override the default."
)
