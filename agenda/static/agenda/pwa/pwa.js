(() => {
  const script = document.currentScript;
  if (window.isSecureContext && "serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker
        .register(script.dataset.worker, { updateViaCache: "none" })
        .catch(() => {
          // The online calendar remains usable if registration fails.
        });
    });
  }

  const banner = document.getElementById("install-banner");
  if (!banner || !window.isSecureContext) return;

  const entry = document.getElementById("install-entry");
  const confirm = document.getElementById("install-confirm");
  const feedback = document.getElementById("install-feedback");
  const help = document.getElementById("install-dialog");
  const standalone = window.matchMedia("(display-mode: standalone)");
  const isApple =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const dismissKey = "clinicaunopar-install-dismissed";
  const sevenDays = 7 * 24 * 60 * 60 * 1000;
  let promptEvent = null;
  let installed = false;

  const isInstalled = () =>
    installed || standalone.matches || navigator.standalone === true;

  function recentlyDismissed() {
    try {
      const value = Number(localStorage.getItem(dismissKey));
      return value > 0 && Date.now() - value < sevenDays;
    } catch {
      return false;
    }
  }

  function updateOffer() {
    const available = !isInstalled() && (isApple || promptEvent !== null);
    banner.hidden = !available || recentlyDismissed();
    entry.hidden = !available || !banner.hidden;
    if (!available && help.open) help.close();
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    promptEvent = event;
    confirm.hidden = false;
    updateOffer();
  });
  window.addEventListener("appinstalled", () => {
    installed = true;
    promptEvent = null;
    updateOffer();
  });
  standalone.addEventListener?.("change", updateOffer);

  document.getElementById("install-dismiss").addEventListener("click", () => {
    try {
      localStorage.setItem(dismissKey, String(Date.now()));
    } catch {
      // Dismissal still works for this page when storage is unavailable.
    }
    banner.hidden = true;
    entry.hidden = false;
  });
  document.getElementById("install-open").addEventListener("click", install);
  confirm.addEventListener("click", install);

  async function install() {
    if (isInstalled()) return;
    if (isApple) {
      help.showModal();
      return;
    }
    if (!promptEvent || confirm.disabled) return;
    const currentPrompt = promptEvent;
    promptEvent = null;
    confirm.disabled = true;
    feedback.hidden = true;
    try {
      await currentPrompt.prompt();
      const choice = await currentPrompt.userChoice;
      if (choice.outcome === "accepted") installed = true;
      updateOffer();
    } catch {
      feedback.textContent =
        "Não foi possível abrir a instalação. Tente pelo menu do navegador ou recarregue a página.";
      feedback.hidden = false;
      entry.hidden = true;
      banner.hidden = false;
      confirm.hidden = true;
    } finally {
      confirm.disabled = false;
    }
  }

  for (const id of ["install-close", "install-done"]) {
    document.getElementById(id).addEventListener("click", () => help.close());
  }
  help.addEventListener("click", (event) => {
    if (event.target !== help) return;
    const bounds = help.getBoundingClientRect();
    if (
      event.clientX < bounds.left ||
      event.clientX > bounds.right ||
      event.clientY < bounds.top ||
      event.clientY > bounds.bottom
    ) {
      help.close();
    }
  });
  updateOffer();
})();
