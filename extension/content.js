(() => {
  const API_URL = "https://gch-timer-api.onrender.com/ingest";
  const IDLE_MS = 5 * 60 * 1000, TICK_MS = 1000, HEARTBEAT_MS = 60 * 1000;
  const EMAIL_KEY = "gch_timer_email";
  const DEBUG = false; // turn off console noise
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
    const first = raw.split(",")[0];          // "Product Analysis:8317..." or "Reportability Decision:8283..."
    const nameOnly = first.split(":")[0];     // keep left part before colon
    return nameOnly.trim();
  }
  let email;
  let lastActivity = Date.now(), lastTick = Date.now(), activeMs = 0;
  const sessionId = Math.random().toString(36).slice(2);
  let complaintId = "", section = "";
  function refreshKeys() {
    const c = findComplaintId();
    const s = findSection();
    if (c && c !== complaintId) { complaintId = c; log("complaint:", c); }
    if (s && s !== section)     { section = s; log("section:", s); }
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
      section: section || "",
      reason,
      active_ms: Math.round(activeMs),
      page: location.href,
      session_id: sessionId
    };
    const body = JSON.stringify(payload);
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon(API_URL, new Blob([body], { type: "application/json" }));
    } else {
      fetch(API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body })
        .catch(() => {});
    }
  }
  chrome.storage.sync.get(["gch_timer_email"], (res) => {
    email = res["gch_timer_email"];
    if (!email) {
      email = prompt("Enter your work email for GCH Timer:");
      if (email) chrome.storage.sync.set({ gch_timer_email: email });
    }
    refreshKeys();
    const mo = new MutationObserver(refreshKeys);
    if (document.body) mo.observe(document.body, { childList: true, subtree: true });
    setInterval(refreshKeys, 2000);
    lastTick = Date.now();
    send("open");
    setInterval(() => accrue(), 1000);
    setInterval(() => { accrue(); refreshKeys(); send("heartbeat"); }, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", () => { accrue(); send("visibility"); });
    window.addEventListener("beforeunload", () => { accrue(); send("unload", true); });
  });
})();