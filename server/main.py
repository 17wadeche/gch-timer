import os, io, smtplib, pytz
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
import secrets
from fastapi import HTTPException, status
from pydantic import BaseModel

DB_URL = os.getenv("DATABASE_URL")
if DB_URL:
    if "://" in DB_URL and "+" not in DB_URL.split("://", 1)[0]:
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DB_URL, pool_pre_ping=True)
else:
    DB_PATH = os.getenv("DB_PATH", "events.db")
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},  # critical for threads (scheduler + requests)
        poolclass=NullPool,                         # avoids reusing same connection across threads
        pool_pre_ping=True,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
        conn.exec_driver_sql(DDL)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "chey.wade@medtronic.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "chey.wade@medtronic.com")
SMTP_TO   = os.getenv("SMTP_TO", "chey.wade@medtronic.com")
ADMIN_CLEAR_PASSWORD = os.getenv("ADMIN_CLEAR_PASSWORD", "start")
TZ = pytz.timezone("America/Chicago")
app = FastAPI(title="GCH Timer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://crm.medtronic.com",
        "https://crmstage.medtronic.com",
        "https://cpic1cs.corp.medtronic.com:8008",
        "https://mspm7aapps0377.cfrf.medtronic.com"
    ],
    allow_origin_regex=r"https://.*\.medtronic\.com(?::\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
DDL = """
CREATE TABLE IF NOT EXISTS events (
  ts           TEXT,
  email        TEXT,
  team           TEXT,
  complaint_id TEXT,
  section      TEXT,
  reason       TEXT,
  active_ms    BIGINT,
  idle_ms      BIGINT DEFAULT 0,
  page         TEXT,
  session_id   TEXT
);
"""
with engine.begin() as conn:
    conn.exec_driver_sql(DDL)
class ClearRequest(BaseModel):
    password: str
class Event(BaseModel):
    ts: str
    email: str
    team: str | None = None
    complaint_id: str | None = None
    section: str | None = None
    reason: str
    active_ms: int
    idle_ms: int = 0
    page: str | None = None
    session_id: str
@app.get("/health")
def health():
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
@app.get("/")
def root():
    return {"ok": True, "message": "GCH Timer API"}
@app.post("/ingest")
def ingest(ev: Event):
    sql = text("""
        INSERT INTO events
          (ts,email,team,complaint_id,section,reason,active_ms,idle_ms,page,session_id)
        VALUES
          (:ts,:email,:team,:complaint_id,:section,:reason,:active_ms,:idle_ms,:page,:session_id)
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "ts": ev.ts, "email": ev.email, "team": ev.team or "",
            "complaint_id": ev.complaint_id or "", "section": ev.section or "",
            "reason": ev.reason, "active_ms": int(ev.active_ms),
            "idle_ms": int(ev.idle_ms or 0), "page": ev.page or "",
            "session_id": ev.session_id
        })
    return {"ok": True}
@app.get("/sessions")
def sessions():
    sql = """
      SELECT
        session_id, email, team, complaint_id,
        MIN(ts) AS start_ts,
        COALESCE(SUM(active_ms),0) AS active_ms,
        COALESCE(SUM(idle_ms),0)   AS idle_ms
      FROM events
      GROUP BY session_id, email, team, complaint_id
      ORDER BY MAX(ts) DESC
    """
    try:
        with engine.begin() as conn:
            rows = conn.exec_driver_sql(sql).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/sessions_by_section")
def sessions_by_section():
    sql = """
      SELECT email, team, complaint_id, section,
             COALESCE(SUM(active_ms),0) AS active_ms
      FROM events
      WHERE TRIM(COALESCE(section,'')) <> ''
      GROUP BY email, team, complaint_id, section
      ORDER BY MAX(ts) DESC
    """
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(sql).mappings().all()
    return [dict(r) for r in rows]
@app.get("/events")
def events_for_complaint(complaint_id: str):
    sql = text("""
      SELECT ts, email, team, complaint_id, section, reason, active_ms, idle_ms, page, session_id
      FROM events
      WHERE complaint_id = :cid
      ORDER BY ts ASC
    """)
    with engine.begin() as conn:
        rows = conn.execute(sql, {"cid": complaint_id}).mappings().all()
    return [dict(r) for r in rows]
@app.get("/sections_by_weekday")
def sections_by_weekday():
    with engine.begin() as conn:
        df = pd.read_sql_query(
            "SELECT ts, complaint_id, section, active_ms FROM events WHERE TRIM(COALESCE(section,'')) <> ''",
            conn
        )
    if df.empty:
        return []
    t = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["weekday"] = t.dt.tz_convert("America/Chicago").dt.day_name()
    out = (
        df.groupby(["complaint_id","section","weekday"], as_index=False)["active_ms"]
          .sum()
          .sort_values(["weekday","complaint_id","section"])
    )
    return out.to_dict(orient="records")
@app.get("/export.xlsx")
def export_xlsx():
    with engine.begin() as conn:
        df = pd.read_sql_query("SELECT * FROM events", conn)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="events")
        (df.groupby(["email","complaint_id"], as_index=False)[["active_ms","idle_ms"]]
           .sum().to_excel(w, index=False, sheet_name="by_complaint"))
        (df[df["section"].astype(str)!=""]
           .groupby(["complaint_id","section"], as_index=False)["active_ms"].sum()
           .to_excel(w, index=False, sheet_name="by_section"))
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="export.xlsx"'}
    )
@app.post("/clear")
def clear_events(req: ClearRequest):
    if not ADMIN_CLEAR_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clear endpoint is disabled (ADMIN_CLEAR_PASSWORD not set)."
        )
    if not secrets.compare_digest((req.password or "").strip(), ADMIN_CLEAR_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin password."
        )
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM events")
    return {"ok": True, "cleared": True}
def _export_bytes() -> bytes:
    with engine.begin() as conn:
        df = pd.read_sql_query("SELECT * FROM events", conn)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="events")
        (df.groupby(["email","complaint_id"], as_index=False)[["active_ms","idle_ms"]]
           .sum().to_excel(w, index=False, sheet_name="by_complaint"))
        (df[df["section"].astype(str)!=""]
           .groupby(["complaint_id","section"], as_index=False)["active_ms"].sum()
           .to_excel(w, index=False, sheet_name="by_section"))
    out.seek(0)
    return out.read()
def _send_email(xlsx_bytes: bytes, subject: str, recipients: list[str]):
    if not (SMTP_HOST and SMTP_FROM and recipients):
        raise RuntimeError("SMTP not configured or no recipients.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM           # From = chey.wade@medtronic.com (default)
    msg["To"] = ", ".join(recipients) # To   = chey.wade@medtronic.com (default)
    msg.set_content("Weekly GCH timer export attached.")
    msg.add_attachment(xlsx_bytes,
                       maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       filename="export.xlsx")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        if SMTP_USER and SMTP_PASS:
            s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
def weekly_rollup_job():
    try:
        recipients = [e.strip() for e in SMTP_TO.split(",") if e.strip()]
        xlsx = _export_bytes()
        now = datetime.now(TZ).strftime("%Y-%m-%d")
        _send_email(xlsx, f"GCH Weekly Export – {now}", recipients)
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM events")
        print("[weekly] Sent and cleared successfully.")
    except Exception as e:
        print(f"[weekly] ERROR: {e}")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.add_job(weekly_rollup_job, "cron", day_of_week="sun", hour=23, minute=59)
scheduler.start()