from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import sqlite3, os, io
DB_PATH = os.getenv("DB_PATH", "events.db")
app = FastAPI(title="GCH Timer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Streamlit/extension origins if desired
    allow_methods=["*"],
    allow_headers=["*"],
)
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
      CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY,
        received_at TEXT,
        ts TEXT,
        email TEXT,
        complaint_id TEXT,
        reason TEXT,
        active_ms INTEGER,
        page TEXT,
        session_id TEXT
      );
    """)
    con.commit()
    con.close()
init_db()
@app.get("/")
def root():
    return {"ok": True, "message": "GCH Timer API"}
@app.post("/ingest")
async def ingest(req: Request):
    try:
        j = await req.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    fields = (
        j.get("ts",""),
        j.get("email",""),
        j.get("complaint_id",""),
        j.get("reason",""),
        int(j.get("active_ms",0)),
        j.get("page",""),
        j.get("session_id",""),
    )
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO events
           (received_at, ts, email, complaint_id, reason, active_ms, page, session_id)
           VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
        fields
    )
    con.commit()
    con.close()
    return {"ok": True}
@app.get("/sessions")
def sessions():
    q = """
      SELECT session_id, email, complaint_id, MAX(active_ms) AS active_ms
      FROM events
      GROUP BY session_id, email, complaint_id
      ORDER BY MAX(rowid) DESC
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(q)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    con.close()
    return rows
@app.get("/export.xlsx")
def export_xlsx():
    import pandas as pd
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM events ORDER BY id DESC", con)
    con.close()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="events")
    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=events.xlsx"}
    )
