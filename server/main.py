import os, io, smtplib, pytz
from email.message import EmailMessage
from datetime import datetime
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
DB_URL = os.getenv("DATABASE_URL")
if DB_URL:
    if "://" in DB_URL and "+" not in DB_URL.split("://", 1)[0]:
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DB_URL, pool_pre_ping=True)
else:
    DB_PATH = os.getenv("DB_PATH", "events.db")          # local/dev
    engine = create_engine(f"sqlite:///{DB_PATH}", pool_pre_ping=True)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "")
SMTP_TO   = os.getenv("SMTP_TO", "")  # comma-separated list; if empty, will fall back to per-user list from data
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
  ou           TEXT,
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
class Event(BaseModel):
    ts: str
    email: str
    ou: str | None = None
    complaint_id: str | None = None
    section: str | None = None
    reason: str
    active_ms: int
    idle_ms: int = 0
    page: str | None = None
    session_id: str
@app.get("/")
def root():
    return {"ok": True, "message": "GCH Timer API"}
@app.post("/ingest")
def ingest(ev: Event):
    sql = text("""
        INSERT INTO events
          (ts,email,ou,complaint_id,section,reason,active_ms,idle_ms,page,session_id)
        VALUES
          (:ts,:email,:ou,:complaint_id,:section,:reason,:active_ms,:idle_ms,:page,:session_id)
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "ts": ev.ts, "email": ev.email, "ou": ev.ou or "",
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
        session_id, email, ou, complaint_id,
        MIN(ts) AS start_ts,
        COALESCE(SUM(active_ms),0) AS active_ms,
        COALESCE(SUM(idle_ms),0)   AS idle_ms
      FROM events
      GROUP BY session_id, email, ou, complaint_id
      ORDER BY MAX(ts) DESC
    """
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(sql).mappings().all()
    return [dict(r) for r in rows]
@app.get("/sessions_by_section")
def sessions_by_section():
    sql = """
      SELECT email, ou, complaint_id, section,
             COALESCE(SUM(active_ms),0) AS active_ms
      FROM events
      WHERE TRIM(COALESCE(section,'')) <> ''
      GROUP BY email, ou, complaint_id, section
      ORDER BY MAX(ts) DESC
    """
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(sql).mappings().all()
    return [dict(r) for r in rows]
@app.get("/events")
def events_for_complaint(complaint_id: str = Query(...)):
    sql = text("""
      SELECT ts, email, ou, complaint_id, section, reason, active_ms, idle_ms, page, session_id
      FROM events
      WHERE complaint_id = :cid
      ORDER BY ts ASC
    """)
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(sql, {"cid": complaint_id}).mappings().all()
    return [dict(r) for r in rows]
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
def clear_events():
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
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(recipients)
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
        if not recipients:
            with engine.begin() as conn:
                emails = conn.exec_driver_sql("SELECT DISTINCT email FROM events WHERE email <> ''").scalars().all()
            recipients = emails
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