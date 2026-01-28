const EMAIL_KEY = "gch_timer_email";
const TEAM_KEY = "gch_timer_ou";
function setStatus(msg, kind = "ok") {
  const s = document.getElementById("status");
  s.className = `status ${kind}`;
  s.textContent = msg;
  if (msg) setTimeout(() => (s.textContent = ""), 1400);
}
function isValidEmail(e) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e);
}
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.local.get([EMAIL_KEY, TEAM_KEY], (res) => {
    if (res[EMAIL_KEY]) document.getElementById("email").value = res[EMAIL_KEY];
    if (res[TEAM_KEY]) document.getElementById("team").value = res[TEAM_KEY];
  });
  const save = () => {
    const email = document.getElementById("email").value.trim();
    const team = document.getElementById("team").value.trim();
    if (email && !isValidEmail(email)) {
      setStatus("Please enter a valid email.", "bad");
      return;
    }
    if (!team) {
      setStatus("Pick a team.", "bad");
      return;
    }
    chrome.storage.local.set({ [EMAIL_KEY]: email, [TEAM_KEY]: team }, () => {
      setStatus("Saved ✓", "ok");
    });
  };
  document.getElementById("save").addEventListener("click", save);
  document.getElementById("email").addEventListener("keydown", (e) => {
    if (e.key === "Enter") save();
  });
});