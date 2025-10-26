const EMAIL_KEY = "gch_timer_email";
const OU_KEY = "gch_timer_ou";
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get([EMAIL_KEY, OU_KEY], (res) => {
    if (res[EMAIL_KEY]) document.getElementById("email").value = res[EMAIL_KEY];
    if (res[OU_KEY]) document.getElementById("ou").value = res[OU_KEY];
  });
  document.getElementById("save").addEventListener("click", () => {
    const email = document.getElementById("email").value.trim();
    const ou = document.getElementById("ou").value.trim();
    chrome.storage.sync.set({ [EMAIL_KEY]: email, [OU_KEY]: ou }, () => {
      const s = document.getElementById("status");
      s.textContent = "Saved";
      setTimeout(() => (s.textContent = ""), 1200);
    });
  });
});
