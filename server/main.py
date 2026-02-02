# server/main.py
import os
import io
import smtplib
import secrets
from datetime import datetime
from email.message import EmailMessage
import re
import pytz
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
import base64
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
from pathlib import Path
import tempfile
from fastapi import Query
SUBSCRIBERS_TOKEN = os.getenv("SUBSCRIBERS_TOKEN", "1234")
def _active_subscriber_emails() -> list[str]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT email
            FROM subscribers
            WHERE is_active = 1
            ORDER BY created_ts DESC
        """)).fetchall()
    return [r[0] for r in rows]
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
DDL_SUBSCRIBERS = """
CREATE TABLE IF NOT EXISTS subscribers (
  email      TEXT PRIMARY KEY,
  team       TEXT,
  is_active  INTEGER DEFAULT 1,
  created_ts TEXT
);
"""
SUBSCRIBERS_CSV_PATH = os.getenv(
    "SUBSCRIBERS_CSV_PATH",
    str(Path(__file__).with_name("subscribers.csv")) 
)
def _get_subscribers_df() -> pd.DataFrame:
    with engine.begin() as conn:
        return pd.read_sql_query(
            "SELECT email, team, is_active, created_ts FROM subscribers ORDER BY created_ts DESC",
            conn
        )
def _write_subscribers_csv() -> None:
    p = Path(SUBSCRIBERS_CSV_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    df = _get_subscribers_df()
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(p.parent), newline="", encoding="utf-8") as tmp:
        df.to_csv(tmp.name, index=False)
        tmp_path = Path(tmp.name)
    tmp_path.replace(p)
def ensure_schema(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL)
        conn.exec_driver_sql(DDL_SUBSCRIBERS)
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
try:
    _write_subscribers_csv()
except Exception as e:
    print(f"[subscribers.csv] initial write failed: {e}")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "chey.wade@medtronic.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "cwade1755@gmail.com")
SMTP_TO = "chey.wade@medtronic.com"
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
        "https://hcwda30449e.cfrf.medtronic.com",
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
class SendNowRequest(BaseModel):
    password: str
    recipients: list[str] | None = None
    clear_after: bool = False
    subject_prefix: str | None = None
class SubscribeRequest(BaseModel):
    email: str
    team: str | None = None

class UnsubscribeRequest(BaseModel):
    email: str
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
def _norm_email(e: str) -> str:
    return (e or "").strip().lower()
def _validate_email(e: str) -> str:
    e = _norm_email(e)
    if not EMAIL_RE.match(e):
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if not e.endswith("@medtronic.com"):
        raise HTTPException(status_code=400, detail="Use your @medtronic.com email.")
    return e
@app.post("/subscribe")
def subscribe(req: SubscribeRequest):
    email = _validate_email(req.email)
    team = (req.team or "").strip()
    now = datetime.now(TZ).isoformat()
    sql = text("""
        INSERT INTO subscribers (email, team, is_active, created_ts)
        VALUES (:email, :team, 1, :created_ts)
        ON CONFLICT(email) DO UPDATE SET
            team = excluded.team,
            is_active = 1
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"email": email, "team": team, "created_ts": now})
    _write_subscribers_csv() 
    return {"ok": True, "email": email, "team": team, "is_active": True}
@app.post("/unsubscribe")
def unsubscribe(req: UnsubscribeRequest):
    email = _validate_email(req.email)
    sql = text("UPDATE subscribers SET is_active = 0 WHERE email = :email")
    with engine.begin() as conn:
        conn.execute(sql, {"email": email})
    _write_subscribers_csv()  
    return {"ok": True, "email": email, "is_active": False}
@app.get("/subscribers")
def list_subscribers(password: str):
    if not secrets.compare_digest((password or "").strip(), ADMIN_CLEAR_PASSWORD):
        raise HTTPException(status_code=403, detail="Invalid admin password.")
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT email, team, is_active, created_ts
            FROM subscribers
            ORDER BY created_ts DESC
        """)).mappings().all()
    return [dict(r) for r in rows]
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
        cid = (ev.complaint_id or "").strip()
        if cid and not re.match(r"^[67]\d{5,11}$", cid):
            raise HTTPException(status_code=400, detail="complaint_id must be 6–12 digits starting with 6 or 7")
        conn.execute(sql, {
            "ts": ev.ts,
            "email": ev.email,
            "team": (ev.team or "").strip(),
            "complaint_id": cid,
            "source": (ev.source or "").strip(),
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
      HAVING (COALESCE(SUM(active_ms),0) + COALESCE(SUM(idle_ms),0)) >= 1000
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
@app.get("/active_subscribers")
def active_subscribers(token: str = Query(default="")):
    if not SUBSCRIBERS_TOKEN or not secrets.compare_digest(token, SUBSCRIBERS_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _active_subscriber_emails()
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
@app.post("/send_now")
def send_now(req: SendNowRequest):
    if not ADMIN_CLEAR_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Send endpoint is disabled (ADMIN_CLEAR_PASSWORD not set)."
        )
    if not secrets.compare_digest((req.password or "").strip(), ADMIN_CLEAR_PASSWORD):
        raise HTTPException(status_code=403, detail="Invalid admin password.")
    try:
        recipients = ["chey.wade@medtronic.com"]
        if not recipients:
            raise HTTPException(status_code=400, detail="No recipients configured/provided.")
        xlsx = _export_bytes()
        now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
        prefix = (req.subject_prefix or "GCH Export")
        subject = f"{prefix} – {now}"
        _send_email(xlsx, subject, recipients)
        if req.clear_after:
            with engine.begin() as conn:
                conn.exec_driver_sql("DELETE FROM events")
        return {"ok": True, "sent_to": recipients, "cleared": bool(req.clear_after)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
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
    api_key = os.getenv("SENDGRID_API_KEY", "")
    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY not set.")
    if not (SMTP_FROM and recipients):
        raise RuntimeError("From address or recipients missing.")
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
    import base64
    message = Mail(
        from_email=SMTP_FROM,
        to_emails=recipients,
        subject=subject,
        html_content="Weekly GCH timer export attached."
    )
    encoded = base64.b64encode(xlsx_bytes).decode("utf-8")
    attachment = Attachment(
        FileContent(encoded),
        FileName("export.xlsx"),
        FileType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        Disposition("attachment"),
    )
    message.attachment = attachment
    sg = SendGridAPIClient(api_key)
    resp = sg.send(message)
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid failed: {resp.status_code} {resp.body}")
def weekly_rollup_job():
    try:
        recipients = ["chey.wade@medtronic.com"]
        xlsx = _export_bytes()
        now = datetime.now(TZ).strftime("%Y-%m-%d")
        _send_email(xlsx, f"GCH/CW Weekly Data Export – {now}", recipients)
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM events")
        print("[weekly] Sent and cleared successfully.")
    except Exception as e:
        print(f"[weekly] ERROR: {e}")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.add_job(weekly_rollup_job, "cron", day_of_week="mon", hour=9, minute=20)
scheduler.start()