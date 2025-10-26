(() => {
  const API_URL = "https://gch-timer-api.onrender.com/ingest";
  const IDLE_MS = 5 * 60 * 1000, TICK_MS = 1000, HEARTBEAT_MS = 60 * 1000;
  const EMAIL_KEY = "gch_timer_email";
  const DEBUG = true;
  const log = (...a) => DEBUG && console.log("[GCH Timer]", ...a);
  function fromGuideSideNav() {
    try {
      const el = document.querySelector("a.GUIDE-sideNav");
      const t = el?.textContent?.trim() || "";
      if (/^\d{6,}$/.test(t)) return t;           // numeric id like 608623294
    } catch {}
    return "";
  }
  function fromUrl() {
    try {
      const u = new URL(location.href);
      for (const k of ["OBJECT_ID","object_id","transaction_id","TransactionID","SR","sr"]) {
        const v = u.searchParams.get(k);
        if (v && /\d{6,}/.test(v)) return v.match(/\d{6,}/)[0];
      }
      if (u.hash) {
        const m = u.hash.match(/\bSR[:#\s-]*([0-9]{6,})\b/i);
        if (m) return m[1];
      }
    } catch {}
    return "";
  }
  function fromTitle() {
    const m = document.title.match(/\bSR[:#\s-]*([0-9]{6,})\b/i);
    return m ? m[1] : "";
  }
  function fromText() {
    const body = document.body ? document.body.innerText.slice(0, 200000) : "";
    if (!body) return "";
    let m = body.match(/\bSR[:#\s-]*([0-9]{6,})\b/i);
    if (m) return m[1];
    m = body.match(/\bTransaction\s*ID[:#\s-]*([0-9]{6,})\b/i);
    if (m) return m[1];
    return "";
  }
  function findComplaintId() {
    return fromGuideSideNav() || fromUrl() || fromTitle() || fromText() || "";
  }
  let email;
  let lastActivity = Date.now(), lastTick = Date.now(), activeMs = 0;
  const sessionId = Math.random().toString(36).slice(2);
  let complaintId = "";
  function refreshComplaintId() {
    const found = findComplaintId();
    if (found && found !== complaintId) {
      complaintId = found;
      log("Detected ID:", complaintId);
    }
  }
  const onAct = () => (lastActivity = Date.now());
  ["click","keydown","mousemove","wheel","touchstart"].forEach(ev =>
    window.addEventListener(ev, onAct, { passive: true })
  );
  function accrue() {
    const now = Date.now();
    if (now - lastActivity <= IDLE_MS) activeMs += (now - lastTick);
    lastTick = now;
  }
  function send(reason, sync=false) {
    const payload = {
      ts: new Date().toISOString(),
      email: email || "",
      complaint_id: complaintId || "",
      reason,
      active_ms: Math.round(activeMs),
      page: location.href,
      session_id: sessionId
    };
    const body = JSON.stringify(payload);
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon(API_URL, new Blob([body], { type: "application/json" }));
    } else {
      fetch(API_URL, { method:"POST", headers:{ "Content-Type":"application/json" }, body })
        .then(() => log("Sent", reason, payload))
        .catch(err => log("Send error", err));
    }
  }
  chrome.storage.sync.get([EMAIL_KEY], (res) => {
    email = res[EMAIL_KEY];
    if (!email) {
      email = prompt("Enter your work email for GCH Timer:");
      if (email) chrome.storage.sync.set({ [EMAIL_KEY]: email });
    }
    refreshComplaintId();
    const mo = new MutationObserver(() => refreshComplaintId());
    if (document.body) mo.observe(document.body, { childList:true, subtree:true });
    setInterval(refreshComplaintId, 2000);
    lastTick = Date.now();
    send("open");
    setInterval(() => accrue(), TICK_MS);
    setInterval(() => { accrue(); refreshComplaintId(); send("heartbeat"); }, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", () => { accrue(); send("visibility"); });
    window.addEventListener("beforeunload", () => { accrue(); send("unload", true); });
  });
})();