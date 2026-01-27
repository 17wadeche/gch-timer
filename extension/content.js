(() => {
  try {
    if (window.top !== window) {
      const ref = (document.referrer || "").toLowerCase();
      if (
        ref.includes("mspm7aapps0377.cfrf.medtronic.com") ||
        ref.includes("hcwda30449e.cfrf.medtronic.com")
      ) {
        return;
      }
    }
  } catch (_) {}
  if (window.__gchTimerBooted) return;
  window.__gchTimerBooted = true;
    console.log("[GCH-TIMER] boot", {
    href: location.href,
    host: location.host,
    path: location.pathname,
  });
  const API_URL   = "https://gch-timer-api.onrender.com/ingest";
  const IDLE_MIN_MS     = 30 * 1000;
  const IDLE_IGNORE_MS  = 5  * 60 * 1000;
  const HEARTBEAT       = 60 * 1000;
  const EMAIL_KEY = "gch_timer_email";
  const TEAM_KEY    = "gch_timer_ou";
  const ALLOWED_TEAMS = ["Aortic","CAS","CRDN","ECT","PVH","SVT","TCT", "CPT", "DS", "PCS & CDS", "PM", "MCS"]
  const DEBUG = true;
  const log = (...a) => {
    if (!DEBUG) return;
    console.log(`[GCH-TIMER][${getSource?.() || "?"}]`, ...a);
  };
  const CW_HOSTS = new Set([
    "mspm7aapps0377.cfrf.medtronic.com",
    "hcwda30449e.cfrf.medtronic.com",
  ]);
  const CW_PATH_HINTS = [
    "/intake/index.html",
    "/testprod/index.html",
    "/intakedev/index.html",
  ];
  function isCW() {
    return CW_HOSTS.has(location.host) && CW_PATH_HINTS.some(p => location.pathname.includes(p));
  }
  function isValidComplaintId(v) {
    const s = String(v || "").trim();
    return /^[67]\d{5,11}$/.test(s); 
  }
  function getSource() {
    return isCW() ? "CW" : "GCH";
  }
  function hasVisibleCWIframeOverlay() {
    if (isCW()) return false;
    const iframes = Array.from(document.querySelectorAll("iframe[src]"));
    for (const ifr of iframes) {
      const src = (ifr.getAttribute("src") || "").toLowerCase();
      if (!src) continue;
      const isCwHost =
        src.includes("mspm7aapps0377.cfrf.medtronic.com") ||
        src.includes("hcwda30449e.cfrf.medtronic.com");
      const isCwPath =
        src.includes("/intake/index.html") ||
        src.includes("/testprod/index.html") ||
        src.includes("/intakedev/index.html");
      if (!(isCwHost && isCwPath)) continue;
      const r = ifr.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) return true;
    }
    return false;
  }
  function shouldAccrueNow() {
    if (document.visibilityState !== "visible") return false;
    if (!document.hasFocus()) return false;
    if (!isCW() && hasVisibleCWIframeOverlay()) return false;
    return true;
  }
  function fromCWDom() {
    if (!isCW()) return "";
    try {
      const nodes = document.querySelectorAll("b");
      for (const n of nodes) {
        const t = (n.textContent || "").trim();
        if (/^\d{8,12}$/.test(t)) return t;
      }
    } catch {}
    return "";
  }
  function fromGuideSideNav(){ try{
    const el=document.querySelector("a.GUIDE-sideNav"); const t=el?.textContent?.trim()||"";
    if(/^\d{6,}$/.test(t)) return t;
  }catch{} return ""; }
  function fromUrl(){ try{
    const u=new URL(location.href);
    for(const k of ["OBJECT_ID","object_id","transaction_id","TransactionID","SR","sr"]){
      const v=u.searchParams.get(k); if(v&&/\d{6,}/.test(v)) return v.match(/\d{6,}/)[0];
    }
    if(u.hash){ const m=u.hash.match(/\bSR[:#\s-]*([0-9]{6,})\b/i); if(m) return m[1]; }
  }catch{} return ""; }
  function fromTitle(){ const m=document.title.match(/\bSR[:#\s-]*([0-9]{6,})\b/i); return m?m[1]:""; }
  function fromText(){ const b=document.body?document.body.innerText.slice(0,200000):""; if(!b) return "";
    let m=b.match(/\bSR[:#\s-]*([0-9]{6,})\b/i); if(m) return m[1];
    m=b.match(/\bTransaction\s*ID[:#\s-]*([0-9]{6,})\b/i); if(m) return m[1]; return "";
  }
  function findComplaintId() {
    const id =
      fromCWDom() ||
      fromGuideSideNav() ||
      fromUrl() ||
      fromTitle() ||
      fromText() ||
      "";
    return isValidComplaintId(id) ? id : "";
  }
  function findSection(){
    if (isCW()) return "Complaint Wizard";
    const el=document.querySelector("#bcTitle"); if(!el) return "";
    const raw=(el.getAttribute("title")||el.innerText||"").trim(); if(!raw) return "";
    const first=raw.split(",")[0]; const nameOnly=first.split(":")[0];
    return nameOnly.trim();
  }
  let email="", team="";
  let complaintId="", section="";
  let lastActivity = 0;
  let lastTick = Date.now();
  let activeMs=0, idleMs=0, lastSentActiveMs=0, lastSentIdleMs=0;
  const sessionId=Math.random().toString(36).slice(2);
  let started=false;
  const onAct=()=>{ lastActivity=Date.now(); };
  ["click","keydown","mousemove","wheel","touchstart"].forEach(ev =>
    window.addEventListener(ev,onAct,{passive:true})
  );
  function accrue(){
    const now = Date.now();
    const dt = now - lastTick;
    if (!shouldAccrueNow()) {
      lastTick = now;
      return;
    }
    if(!complaintId){
      lastTick = now;
      return;
    }
    if(!lastActivity){
      lastTick = now;
      return;
    }
    const idleGap = now - lastActivity;
    if (idleGap < IDLE_MIN_MS) {
      activeMs += dt;
    } else if (idleGap < IDLE_IGNORE_MS) {
      idleMs += dt;
    } else {
    }
    lastTick = now;
  }
  function post(body){
    return fetch(API_URL, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body
    }).then(async (res) => {
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        log("INGEST FAILED", res.status, txt);
      } else {
        log("ingest ok");
      }
      return res;
    }).catch((err) => {
      log("INGEST ERROR", err);
      throw err;
    });
  }
  function send(reason, sync = false) {
    if (!complaintId) return;
    const payload = {
      ts: new Date().toISOString(),
      email,
      team,
      complaint_id: complaintId,
      source: getSource(),
      section,
      reason,
      active_ms: Math.round(activeMs),
      idle_ms: Math.round(idleMs),
      page: location.href,
      session_id: sessionId
    };
    log("send", {
      reason,
      complaint_id: complaintId,
      source: getSource(),
      active_ms: Math.round(activeMs),
      idle_ms: Math.round(idleMs)
    });
    const body = JSON.stringify(payload);
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon(API_URL, new Blob([body], { type: "application/json" }));
      return;
    }
    post(body).catch(() => setTimeout(() => post(body).catch(() => {}), 1000));
  }
  function maybeSend(reason){
    if(!complaintId) return;
    if(activeMs>lastSentActiveMs || idleMs>lastSentIdleMs){
      lastSentActiveMs=activeMs; lastSentIdleMs=idleMs; send(reason);
    }
  }
  function refreshKeys(){
    const c = findComplaintId();
    if (!c) {
      const raw =
        fromCWDom() || fromGuideSideNav() || fromUrl() || fromTitle() || fromText() || "";
      if (raw) log("rejected complaint id (not 6/7…):", raw);
    }
    const s = findSection();
    if (c && c !== complaintId) {
      complaintId = c;
      log("complaint detected:", complaintId, "source:", getSource(), "href:", location.href);
    }
    if (s && s !== section) {
      section = s;
      log("section:", section);
    }
    if(!started && complaintId && email && team && (isCW() || lastActivity)){
      lastTick = Date.now();
      started = true;
      log("START session", {
        complaintId,
        source: getSource(),
        email,
        team,
        section,
        startedAt: new Date().toISOString(),
        lastActivity: !!lastActivity
      });
      send("open");
    }
  }
  let panelRoot = null;
  const SETUP_HOST_ID = "gch-timer-setup-host";
  function showSetupPanel(currEmail, currOu) {
    try {
      if (window.top !== window) return;
    } catch (_) {
      return;
    }
    if (panelRoot) return;
    if (document.getElementById(SETUP_HOST_ID)) return;
    const host = document.createElement("div");
    host.id = SETUP_HOST_ID;
    host.style.all = "initial";
    host.style.position = "fixed";
    host.style.right = "16px";
    host.style.bottom = "16px";
    host.style.zIndex = "2147483647";
    document.documentElement.appendChild(host);
    const root = host.attachShadow({ mode: "open" });
    panelRoot = host;
    const style = document.createElement("style");
    style.textContent = `
      :host{all:initial}
      .card{font:14px system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#fff;border:1px solid #e3e3e3;border-radius:10px;box-shadow:0 6px 16px rgba(0,0,0,.18);padding:14px;min-width:280px;position:relative}
      .row{display:flex;gap:8px;margin-top:8px}
      label{display:block;font-weight:600;margin-bottom:4px}
      input,select{width:100%;padding:8px;border:1px solid #ccc;border-radius:8px}
      button{padding:8px 12px;border-radius:8px;border:0;background:#0a66c2;color:#fff;font-weight:600;cursor:pointer}
      .hdr{font-weight:700;margin-bottom:8px}
      .x{position:absolute;top:6px;right:8px;cursor:pointer;font-weight:700}
    `;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="card">
        <div class="x" title="Close">×</div>
        <div class="hdr">GCH/CW Work Timer – Quick Setup</div>
        <div>
          <label>Email</label>
          <input id="gch-email" type="email" placeholder="you@medtronic.com">
        </div>
        <div class="row">
          <div style="flex:1">
            <label>Team</label>
            <select id="gch-team">
              <option value="">-- select Team --</option>
              ${ALLOWED_TEAMS.map(o => `<option value="${o}">${o}</option>`).join("")}
            </select>
          </div>
          <div style="display:flex;align-items:flex-end"><button id="gch-save">Save</button></div>
        </div>
      </div>
    `;
    root.appendChild(style);
    root.appendChild(wrap);
    const $ = (sel) => root.querySelector(sel);
    $("#gch-email").value = currEmail || "";
    $("#gch-team").value = ALLOWED_TEAMS.includes(currOu || "") ? currOu : "";
    $("#gch-save").addEventListener("click", () => {
      const e = $("#gch-email").value.trim();
      const o = $("#gch-team").value.trim();
      if (!e) { alert("Please enter your work email."); return; }
      if (!ALLOWED_TEAMS.includes(o)) { alert("Please select a valid Team."); return; }
      chrome.storage.local.set({ [EMAIL_KEY]: e, [TEAM_KEY]: o }, () => {
        email = e;
        team = o;
        host.remove();
        panelRoot = null;
        refreshKeys();
      });
    });
    wrap.querySelector(".x").addEventListener("click", () => {
      host.remove();
      panelRoot = null;
    });
  }
  chrome.storage.local.get([EMAIL_KEY, TEAM_KEY], res => {
    email = (res[EMAIL_KEY] || "").trim();
    team  = (res[TEAM_KEY] || "").trim();
    if (window.top === window && (!email || !ALLOWED_TEAMS.includes(team))) {
      showSetupPanel(email, team);
    }
    const mo=new MutationObserver(refreshKeys);
    if(document.body) mo.observe(document.body,{childList:true,subtree:true});
    setInterval(refreshKeys,1500);
    setInterval(()=>accrue(),1000);
    setInterval(()=>{ accrue(); refreshKeys(); maybeSend("heartbeat"); },HEARTBEAT);
    document.addEventListener("visibilitychange",()=>{ accrue(); maybeSend("visibility"); });
    window.addEventListener("beforeunload",()=>{ accrue(); send("unload",true); });
  });
})();