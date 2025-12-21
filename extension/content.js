(() => {
  if (window.__gchTimerBooted) return;
  window.__gchTimerBooted = true;
  const API_URL   = "https://gch-timer-api.onrender.com/ingest";
  const IDLE_MIN_MS     = 30 * 1000;         // >=30s is "idle"
  const IDLE_IGNORE_MS  = 5  * 60 * 1000;    // >=5m is ignored entirely
  const HEARTBEAT       = 60 * 1000;
  const EMAIL_KEY = "gch_timer_email";
  const TEAM_KEY    = "gch_timer_ou";
  const ALLOWED_TEAMS = ["Aortic","CAS","CRDN","ECT","PVH","SVT","TCT", "CPT", "DS", "PCS & CDS", "PM", "MCS"]
  const DEBUG=true; const log=(...a)=>{ if(DEBUG) console.log("[GCH]",...a); };
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
  function findComplaintId(){ return fromGuideSideNav()||fromUrl()||fromTitle()||fromText()||""; }
  function findSection(){
    if (location.host.includes("mspm7aapps0377.cfrf.medtronic.com")) {
      return "Complaint Wizard";
    }
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
    const now=Date.now();
    const dt=now-lastTick;
    if(!complaintId || !lastActivity){
      lastTick = now;
      return;
    }
    const idleGap=now-lastActivity;
    if (idleGap < IDLE_MIN_MS) {
      activeMs += dt;
    } else if (idleGap < IDLE_IGNORE_MS) {
      idleMs += dt;
    } else {
    }
    lastTick=now;
  }
  function post(body){
    return fetch(API_URL,{method:"POST",headers:{"Content-Type":"application/json"},body});
  }
  function send(reason,sync=false){
    if(!complaintId) return;
    const payload={
      ts:new Date().toISOString(),
      email, team,
      complaint_id:complaintId,
      section,
      reason,
      active_ms:Math.round(activeMs),
      idle_ms:Math.round(idleMs),
      page:location.href,
      session_id:sessionId
    };
    const body=JSON.stringify(payload);
    if(sync && navigator.sendBeacon){
      navigator.sendBeacon(API_URL,new Blob([body],{type:"application/json"}));
      return;
    }
    post(body).catch(()=> setTimeout(()=>post(body).catch(()=>{}),1000));
  }
  function maybeSend(reason){
    if(!complaintId) return;
    if(activeMs>lastSentActiveMs || idleMs>lastSentIdleMs){
      lastSentActiveMs=activeMs; lastSentIdleMs=idleMs; send(reason);
    }
  }
  function refreshKeys(){
    const c=findComplaintId();
    const s=findSection();
    if(started && complaintId && c && c!==complaintId){
      accrue(); maybeSend("switch");
      activeMs=0; idleMs=0; lastSentActiveMs=0; lastSentIdleMs=0;
    }
    if(c && c!==complaintId){ complaintId=c; log("complaint:",c); }
    if(s && s!==section){ section=s; log("section:",s); }
    if(!started && complaintId && email && team && lastActivity){
      lastTick = Date.now();
      started = true;
      send("open");
    }
  }
  let panelRoot=null;
  function showSetupPanel(currEmail,currOu){
    if(panelRoot) return;
    const host=document.createElement("div");
    host.style.all="initial"; host.style.position="fixed"; host.style.right="16px"; host.style.bottom="16px"; host.style.zIndex="2147483647";
    document.documentElement.appendChild(host);
    const root=host.attachShadow({mode:"open"}); panelRoot=host;
    const style=document.createElement("style"); style.textContent=`
      :host{all:initial}
      .card{font:14px system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#fff;border:1px solid #e3e3e3;border-radius:10px;box-shadow:0 6px 16px rgba(0,0,0,.18);padding:14px;min-width:280px}
      .row{display:flex;gap:8px;margin-top:8px}
      label{display:block;font-weight:600;margin-bottom:4px}
      input,select{width:100%;padding:8px;border:1px solid #ccc;border-radius:8px}
      button{padding:8px 12px;border-radius:8px;border:0;background:#0a66c2;color:#fff;font-weight:600;cursor:pointer}
      .hdr{font-weight:700;margin-bottom:8px}
      .x{position:absolute;top:6px;right:8px;cursor:pointer;font-weight:700}
    `;
    const wrap=document.createElement("div");
    wrap.innerHTML=`
      <div class="card">
        <div class="x" title="Close">×</div>
        <div class="hdr">GCH Work Timer – Quick Setup</div>
        <div>
          <label>Email</label>
          <input id="gch-email" type="email" placeholder="you@medtronic.com">
        </div>
        <div class="row">
          <div style="flex:1">
            <label>Operating Unit</label>
            <select id="gch-team">
              <option value="">-- select Team --</option>
              ${ALLOWED_TEAMS.map(o=>`<option value="${o}">${o}</option>`).join("")}
            </select>
          </div>
          <div style="display:flex;align-items:flex-end"><button id="gch-save">Save</button></div>
        </div>
      </div>
    `;
    root.appendChild(style); root.appendChild(wrap);
    const $=sel=>root.querySelector(sel);
    $("#gch-email").value=currEmail||"";
    $("#gch-team").value=ALLOWED_TEAMS.includes(currOu||"")?currOu:"";
    $("#gch-save").addEventListener("click",()=>{
      const e=$("#gch-email").value.trim(); const o=$("#gch-team").value.trim();
      if(!e){ alert("Please enter your work email."); return; }
      if(!ALLOWED_TEAMS.includes(o)){ alert("Please select a valid Team."); return; }
      chrome.storage.sync.set({[EMAIL_KEY]:e,[TEAM_KEY]:o},()=>{
        email=e; team=o; host.remove(); panelRoot=null; refreshKeys();
      });
    });
    wrap.querySelector(".x").addEventListener("click",()=>{ host.remove(); panelRoot=null; });
  }
  chrome.storage.sync.get([EMAIL_KEY,TEAM_KEY],res=>{
    email=(res[EMAIL_KEY]||"").trim(); team=(res[TEAM_KEY]||"").trim();
    if(!email || !ALLOWED_TEAMS.includes(team)) showSetupPanel(email,team);
    const mo=new MutationObserver(refreshKeys);
    if(document.body) mo.observe(document.body,{childList:true,subtree:true});
    setInterval(refreshKeys,1500);
    setInterval(()=>accrue(),1000);
    setInterval(()=>{ accrue(); refreshKeys(); maybeSend("heartbeat"); },HEARTBEAT);
    document.addEventListener("visibilitychange",()=>{ accrue(); maybeSend("visibility"); });
    window.addEventListener("beforeunload",()=>{ accrue(); send("unload",true); });
  });
})();