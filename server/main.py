import os, io
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import pandas as pd
DB_URL = os.getenv("DATABASE_URL")
if DB_URL:
    if "://" in DB_URL and "+" not in DB_URL.split("://", 1)[0]:
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(DB_URL, pool_pre_ping=True)
else:
    DB_PATH = os.getenv("DB_PATH", "events.db")          # local/dev
    engine = create_engine(f"sqlite:///{DB_PATH}", pool_pre_ping=True)
app = FastAPI(title="GCH Timer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://crm.medtronic.com"],
    allow_origin_regex=r"https://.*\.medtronic\.com",
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
@app.get("/export.xlsx")
def export_xlsx():
    import pandas as pd
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