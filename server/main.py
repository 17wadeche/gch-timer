from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import sqlite3, os, io, json
DB_PATH = os.getenv("DB_PATH", "events.db")
app = FastAPI(title="GCH Timer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],             # tighten later if you want
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
    import xlsxwriter
    con = sqlite3.connect(DB_PATH)
    cur = con.execute("SELECT * FROM events ORDER BY id DESC")
    cols = [c[0] for c in cur.description]
    data = cur.fetchall()
    con.close()
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {'in_memory': True})
    ws = wb.add_worksheet('events')
    header_fmt = wb.add_format({'bold': True})
    for j, name in enumerate(cols):
        ws.write(0, j, name, header_fmt)
    for i, row in enumerate(data, start=1):
        for j, val in enumerate(row):
            ws.write(i, j, val)
    wb.close()
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=events.xlsx"}
    )