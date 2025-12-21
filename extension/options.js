const EMAIL_KEY = "gch_timer_email";
const TEAM_KEY = "gch_timer_ou";
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get([EMAIL_KEY, TEAM_KEY], (res) => {
    if (res[EMAIL_KEY]) document.getElementById("email").value = res[EMAIL_KEY];
    if (res[TEAM_KEY]) document.getElementById("team").value = res[TEAM_KEY];
  });
  document.getElementById("save").addEventListener("click", () => {
    const email = document.getElementById("email").value.trim();
    const team = document.getElementById("team").value.trim();
    chrome.storage.sync.set({ [EMAIL_KEY]: email, [TEAM_KEY]: team }, () => {
      const s = document.getElementById("status");
      s.textContent = "Saved";
      setTimeout(() => (s.textContent = ""), 1200);
    });
  });
});
