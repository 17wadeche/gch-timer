// GCH Work Timer - content script
(() => {
  // ======= CONFIG =======
  const API_URL = "https://YOUR-RENDER-APP.onrender.com/ingest"; // <- CHANGE THIS
  const IDLE_MS = 5 * 60 * 1000;   // idle after 5 minutes without input
  const TICK_MS = 1000;            // accrual resolution
  const HEARTBEAT_MS = 60 * 1000;  // send every minute
  const EMAIL_KEY = "gch_timer_email";
  const CID_RE = /\/complaints\/([A-Za-z0-9_-]+)/;

  // ======= STATE =======
  let email;
  let lastActivity = Date.now();
  let lastTick = Date.now();
  let activeMs = 0;
  const sessionId = Math.random().toString(36).slice(2);
  const complaintId = (location.pathname.match(CID_RE) || [])[1] || "";

  // ======= HELPERS =======
  const onAct = () => (lastActivity = Date.now());

  ["click", "keydown", "mousemove", "wheel", "touchstart"].forEach(ev =>
    window.addEventListener(ev, onAct, { passive: true })
  );

  function accrue() {
    const now = Date.now();
    if (now - lastActivity <= IDLE_MS) activeMs += (now - lastTick);
    lastTick = now;
  }

  function send(reason, sync = false) {
    const payload = {
      ts: new Date().toISOString(),
      email: email || "",
      complaint_id: complaintId,
      reason,
      active_ms: Math.round(activeMs),
      page: location.href,
      session_id: sessionId
    };
    const body = JSON.stringify(payload);
    if (sync && navigator.sendBeacon) {
      navigator.sendBeacon(API_URL, new Blob([body], { type: "application/json" }));
    } else {
      fetch(API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body }).catch(() => {});
    }
  }

  // ======= START =======
  chrome.storage.sync.get([EMAIL_KEY], (res) => {
    email = res[EMAIL_KEY];
    if (!email) {
      email = prompt("Enter your work email for GCH Timer:");
      if (email) chrome.storage.sync.set({ [EMAIL_KEY]: email });
    }

    lastTick = Date.now();
    send("open");
    setInterval(() => accrue(), TICK_MS);
    setInterval(() => { accrue(); send("heartbeat"); }, HEARTBEAT_MS);
    document.addEventListener("visibilitychange", () => { accrue(); send("visibility"); });
    window.addEventListener("beforeunload", () => { accrue(); send("unload", true); });
  });
})();
