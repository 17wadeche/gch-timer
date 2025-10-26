const EMAIL_KEY = "gch_timer_email";

document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get([EMAIL_KEY], (res) => {
    if (res[EMAIL_KEY]) document.getElementById("email").value = res[EMAIL_KEY];
  });

  document.getElementById("save").addEventListener("click", () => {
    const email = document.getElementById("email").value.trim();
    chrome.storage.sync.set({ [EMAIL_KEY]: email }, () => {
      const s = document.getElementById("status");
      s.textContent = "Saved";
      setTimeout(() => (s.textContent = ""), 1200);
    });
  });
});
