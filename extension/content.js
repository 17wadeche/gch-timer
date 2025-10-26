(() => {
  if (window.top !== window.self) return;
  if (window.__gchTimerBooted) return;
  window.__gchTimerBooted = true;
  const API_URL = "https://gch-timer-api.onrender.com/ingest";
  const IDLE_MS = 5 * 60 * 1000, TICK_MS = 1000, HEARTBEAT_MS = 60 * 1000;
  const EMAIL_KEY = "gch_timer_email";
  const OU_KEY   = "gch_timer_ou";
  const ALLOWED_OUS = new Set(["Aortic","CAS","CRDN","ECT","PVH","SVT","TCT"]);
  const DEBUG = false;
  const log = (...a) => { if (DEBUG) console.log("[GCH Timer]", ...a); };
  function fromGuideSideNav() {
    try {
      const el = document.querySelector("a.GUIDE-sideNav");
      const t = el?.textContent?.trim() || "";
      if (/^\d{6,}$/.test(t)) return t;
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
  function findSection() {
    const el = document.querySelector("#bcTitle");
    if (!el) return "";
    const raw = (el.getAttribute("title") || el.innerText || "").trim();
    if (!raw) return "";
    const first = raw.split(",")[0];      // "Product Analysis:..." or "Reportability Decision:..."
    const nameOnly = first.split(":")[0]; // keep left part before colon
    return nameOnly.trim();
  }
  let email = "", ou = "";
  let lastActivity = Date.now(), lastTick = Date.now();
  let activeMs = 0, lastSentActiveMs = 0;
  const sessionId = Math.random().toString(36).slice(2);
  let complaintId = "", section = "", started = false;
  function accrue() {
    const now = Date.now();
    if (complaintId && (now - lastActivity <= IDLE_MS)) {
      activeMs += (now - lastTick);
    }
    lastTick = now;
  }
  const onAct = () => (lastActivity = Date.now());
  ["click","keydown","mousemove","wheel","touchstart"].forEach(ev =>
    window.addEventListener(ev, onAct, { passive: true })
  );
  function post(body) {
    return fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body
    });
  }
  function send(reason, sync=false) {
    if (!complaintId) return; // hard guard: never send without complaint
    const payload = {
      ts: new Date().toISOString(),
      email: email || "",
      ou: ou || "",
      complaint_id: complaintId || "",
      section: section || "",
      reason,
      active_ms: Math.round(activeMs),
      page: location.href,
      session_id: sessionId
    };
    const body = JSON.stringify(payload);
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon(API_URL, new Blob([body], { type: "application/json" }));
      return;
    }
    post(body).catch(() => {
      setTimeout(() => post(body).catch(() => {}), 1000);
    });
  }
  function maybeSend(reason) {
    if (!complaintId) return;
    if (activeMs > lastSentActiveMs) {
      lastSentActiveMs = activeMs;
      send(reason);
    }
  }
  function refreshKeysAndMaybeStart() {
    const newC = findComplaintId();
    const newS = findSection();
    if (started && complaintId && newC && newC !== complaintId) {
      accrue();
      maybeSend("switch");
      activeMs = 0;
      lastSentActiveMs = 0;
    }
    if (newC && newC !== complaintId) { complaintId = newC; log("complaint:", complaintId); }
    if (newS && newS !== section)     { section     = newS; log("section:", section); }
    if (!started && complaintId && email && ou) {
      lastTick = Date.now();
      started = true;
      send("open"); // first record now that we have a complaint_id
    }
  }
  chrome.storage.sync.get([EMAIL_KEY, OU_KEY], (res) => {
    email = (res[EMAIL_KEY] || "").trim();
    ou = (res[OU_KEY] || "").trim();
    if (!ALLOWED_OUS.has(ou)) {
      try { chrome.runtime.openOptionsPage(); } catch {}
      alert("Please set your Operating Unit (OU) in the GCH Work Timer options.");
    }
    if (!email) {
      const e = prompt("Enter your work email for GCH Timer:");
      if (e) {
        email = e.trim();
        chrome.storage.sync.set({ [EMAIL_KEY]: email });
      }
    }
    const mo = new MutationObserver(refreshKeysAndMaybeStart);
    if (document.body) mo.observe(document.body, { childList: true, subtree: true });
    setInterval(refreshKeysAndMaybeStart, 1500);
    setInterval(() => accrue(), 1000);t
    setInterval(() => { accrue(); refreshKeysAndMaybeStart(); maybeSend("heartbeat"); }, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", () => { accrue(); maybeSend("visibility"); });
    window.addEventListener("beforeunload", () => { accrue(); send("unload", true); });
  });
})();