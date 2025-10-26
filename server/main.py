# server/main.py
import os, sqlite3, io
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from datetime import datetime
DB_PATH = os.getenv("DB_PATH", "events.db")
app = FastAPI(title="GCH Timer API")
class Event(BaseModel):
    ts: str
    email: str
    complaint_id: str | None = None
    section: str | None = None
    reason: str
    active_ms: int
    page: str | None = None
    session_id: str
def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)
def init_db():
    con = _conn()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events(
            ts TEXT,
            email TEXT,
            complaint_id TEXT,
            section TEXT,
            reason TEXT,
            active_ms INTEGER,
            page TEXT,
            session_id TEXT
        )
    """)
    try:
        cur.execute("ALTER TABLE events ADD COLUMN section TEXT")
    except sqlite3.OperationalError:
        pass
    con.commit(); con.close()
init_db()
@app.get("/")
def root():
    return {"ok": True, "message": "GCH Timer API"}
@app.post("/ingest")
def ingest(ev: Event):
    con = _conn(); cur = con.cursor()
    cur.execute("""
        INSERT INTO events (ts,email,complaint_id,section,reason,active_ms,page,session_id)
        VALUES (?,?,?,?,?,?,?,?)
    """, (ev.ts, ev.email, ev.complaint_id or "", ev.section or "", ev.reason,
          ev.active_ms, ev.page or "", ev.session_id))
    con.commit(); con.close()
    return {"ok": True}
@app.get("/sessions")
def sessions():
    """Aggregate per session (kept for compatibility)."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
        SELECT session_id, email, complaint_id, SUM(active_ms) AS active_ms
        FROM events
        GROUP BY session_id, email, complaint_id
        ORDER BY MAX(ts) DESC
    """)
    rows = cur.fetchall(); con.close()
    return [{"session_id": r[0], "email": r[1], "complaint_id": r[2], "active_ms": r[3] or 0} for r in rows]
@app.get("/sessions_by_section")
def sessions_by_section():
    """Aggregate by complaint + section (for dashboard chart)."""
    con = _conn(); cur = con.cursor()
    cur.execute("""
        SELECT email, complaint_id, section, SUM(active_ms) AS active_ms
        FROM events
        GROUP BY email, complaint_id, section
        HAVING section <> ''
        ORDER BY MAX(ts) DESC
    """)
    rows = cur.fetchall(); con.close()
    return [{"email": r[0], "complaint_id": r[1], "section": r[2], "active_ms": r[3] or 0} for r in rows]
@app.get("/export.xlsx")
def export_xlsx():
    import pandas as pd
    con = _conn()
    df = pd.read_sql_query("SELECT * FROM events", con)
    con.close()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="events")
        (df.groupby(["email","complaint_id"], as_index=False)["active_ms"].sum()
           .to_excel(w, index=False, sheet_name="by_complaint"))
        (df[df["section"].astype(str)!=""]
           .groupby(["complaint_id","section"], as_index=False)["active_ms"].sum()
           .to_excel(w, index=False, sheet_name="by_section"))
    out.seek(0)
    return StreamingResponse(out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="export.xlsx"'})