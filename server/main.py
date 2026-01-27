# server/main.py
import os
import io
import smtplib
import secrets
from datetime import datetime
from email.message import EmailMessage
import pytz
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
DDL = """
CREATE TABLE IF NOT EXISTS events (
  ts           TEXT,
  email        TEXT,
  team         TEXT,
  complaint_id TEXT,
  source       TEXT,
  section      TEXT,
  reason       TEXT,
  active_ms    BIGINT,
  idle_ms      BIGINT DEFAULT 0,
  page         TEXT,
  session_id   TEXT
);
"""
def ensure_schema(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL)
    backend = engine.url.get_backend_name()
    if backend.startswith("postgresql"):
        migrations = [
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS team TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS complaint_id TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS section TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS reason TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS active_ms BIGINT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS idle_ms BIGINT DEFAULT 0",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS page TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS session_id TEXT",
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS source TEXT",
        ]
        for sql in migrations:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
        return
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(events)").fetchall()]
    to_add = []
    if "team" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN team TEXT")
    if "complaint_id" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN complaint_id TEXT")
    if "section" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN section TEXT")
    if "reason" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN reason TEXT")
    if "active_ms" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN active_ms BIGINT")
    if "idle_ms" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN idle_ms BIGINT DEFAULT 0")
    if "page" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN page TEXT")
    if "session_id" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN session_id TEXT")
    if "source" not in cols:
        to_add.append("ALTER TABLE events ADD COLUMN source TEXT")
    for sql in to_add:
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
DB_URL = os.getenv("DATABASE_URL")
if DB_URL:
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DB_URL.startswith("postgresql://") and not DB_URL.startswith("postgresql+psycopg://"):
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DB_URL, pool_pre_ping=True)
else:
    DB_PATH = os.getenv("DB_PATH", "events.db")
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
ensure_schema(engine)
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
        "https://mspm7aapps0377.cfrf.medtronic.com",
    ],
    allow_origin_regex=r"https://.*\.medtronic\.com(?::\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
class ClearRequest(BaseModel):
    password: str
class Event(BaseModel):
    ts: str
    email: str
    team: str | None = None
    complaint_id: str | None = None
    source: str | None = None
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
        (ts,email,team,complaint_id,source,section,reason,active_ms,idle_ms,page,session_id)
        VALUES
        (:ts,:email,:team,:complaint_id,:source,:section,:reason,:active_ms,:idle_ms,:page,:session_id)
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "ts": ev.ts,
            "email": ev.email,
            "team": (ev.team or "").strip(),
            "complaint_id": (ev.complaint_id or "").strip(),
            "section": (ev.section or "").strip(),
            "reason": ev.reason,
            "active_ms": int(ev.active_ms),
            "idle_ms": int(ev.idle_ms or 0),
            "page": (ev.page or "").strip(),
            "session_id": ev.session_id,
        })
    return {"ok": True}
@app.get("/sessions")
def sessions():
    sql = """
      SELECT
        session_id, email, team, complaint_id, source,
        MIN(ts) AS start_ts,
        COALESCE(SUM(active_ms),0) AS active_ms,
        COALESCE(SUM(idle_ms),0)   AS idle_ms
      FROM events
      GROUP BY session_id, email, team, complaint_id, source
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
      SELECT email, team, complaint_id, source, section,
        COALESCE(SUM(active_ms),0) AS active_ms
      FROM events
      WHERE TRIM(COALESCE(section,'')) <> ''
      GROUP BY email, team, complaint_id, source, section
      ORDER BY MAX(ts) DESC
    """
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(sql).mappings().all()
    return [dict(r) for r in rows]
@app.get("/events")
def events_for_complaint(complaint_id: str):
    sql = text("""
      SELECT ts, email, team, complaint_id, source, section, reason, active_ms, idle_ms, page, session_id
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
            "SELECT ts, complaint_id, source, section, active_ms FROM events WHERE TRIM(COALESCE(section,'')) <> ''",
            conn
        )
    if df.empty:
        return []
    t = pd.to_datetime(df["ts"], errors="coerce", utc=True)
    df["weekday"] = t.dt.tz_convert("America/Chicago").dt.day_name()
    out = (
        df.groupby(["complaint_id","source","section","weekday"], as_index=False)["active_ms"]
          .sum()
          .sort_values(["weekday","complaint_id","source","section"])
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
        (df[df["section"].astype(str) != ""]
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
        (df[df["section"].astype(str) != ""]
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
    msg.add_attachment(
        xlsx_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="export.xlsx",
    )
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