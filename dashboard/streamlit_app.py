import time
import io
import requests
import pandas as pd
import streamlit as st

# ===== Config =====
API_BASE = "https://gch-timer-api.onrender.com"   # <- your API
TIMEOUT = 60                                       # allow cold-starts
RETRIES = 3

st.set_page_config(page_title="GCH Work Time", layout="wide")
st.title("GCH Work Time Dashboard")

# Small helper to show a line of debug on the page
def log(msg: str):
    st.write(f"🔎 {msg}")

# ---- Connectivity health check (root endpoint) ----
@st.cache_data(ttl=30)
def api_health():
    t0 = time.time()
    r = requests.get(f"{API_BASE}/", timeout=TIMEOUT)
    dt = (time.time() - t0) * 1000
    return r.status_code, r.text, int(dt)

# ---- Robust fetch with retries ----
@st.cache_data(ttl=60)
def fetch_sessions() -> pd.DataFrame:
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            t0 = time.time()
            r = requests.get(f"{API_BASE}/sessions", timeout=TIMEOUT)
            r.raise_for_status()
            dt = (time.time() - t0) * 1000
            log(f"/sessions {r.status_code} in {int(dt)} ms")
            df = pd.DataFrame(r.json())
            if df.empty:
                return pd.DataFrame(columns=["session_id","email","complaint_id","active_ms","active_minutes"])
            df["active_ms"] = pd.to_numeric(df["active_ms"], errors="coerce").fillna(0).astype(int)
            df["active_minutes"] = (df["active_ms"]/60000.0).round(2)
            return df
        except Exception as e:
            last_err = e
            log(f"Attempt {attempt} failed: {e}")
            time.sleep(2 * attempt)  # backoff
    raise last_err

# ---------- UI ----------
with st.spinner("Checking API health…"):
    try:
        code, text, ms = api_health()
        st.success(f"API health: {code} in {ms} ms")
    except Exception as e:
        st.error(f"Could not reach API root {API_BASE}/")
        st.exception(e)
        st.stop()

with st.spinner("Loading session data…"):
    try:
        df = fetch_sessions()
    except Exception as e:
        st.error(f"Failed to load {API_BASE}/sessions")
        st.exception(e)
        st.stop()

# KPIs
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Total active hours", round(df["active_ms"].sum()/3_600_000, 2) if not df.empty else 0)
with c2:
    st.metric("Sessions", int(len(df)))
with c3:
    st.metric("Unique users", int(df["email"].nunique()) if not df.empty else 0)

# Table
st.subheader("Sessions")
st.dataframe(df, use_container_width=True, height=320)

# Charts
st.subheader("Active minutes by complaint")
if not df.empty:
    st.bar_chart(df.groupby("complaint_id")["active_minutes"].sum(), use_container_width=True)
else:
    st.info("No complaint data yet.")

st.subheader("Active minutes by user")
if not df.empty:
    st.bar_chart(df.groupby("email")["active_minutes"].sum(), use_container_width=True)
else:
    st.info("No user data yet.")

# Excel export
def to_excel(d: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        d.to_excel(w, index=False, sheet_name="sessions")
        d.groupby("complaint_id", as_index=False)["active_minutes"].sum().to_excel(w, index=False, sheet_name="by_complaint")
        d.groupby("email", as_index=False)["active_minutes"].sum().to_excel(w, index=False, sheet_name="by_user")
    return out.getvalue()

if not df.empty:
    st.download_button(
        "Download Excel",
        to_excel(df),
        file_name="gch_timer.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.caption("Data refreshes every ~60s. Only active (non-idle) time on tracked pages is counted.")
