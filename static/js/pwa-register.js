(() => {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  let reloadingForUpdate = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloadingForUpdate) return;
    reloadingForUpdate = true;
    window.location.reload();
  });
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
      .then(registration => registration.update())
      .catch(() => {
        // Installation is optional; a worker failure must never break the site.
      });
  });
})();
