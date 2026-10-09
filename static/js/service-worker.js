const CACHE_VERSION = "gohmotech-static-v2";
const OFFLINE_URL = "/static/pwa/offline.html";
const APP_SHELL = [
  OFFLINE_URL,
  "/static/images/pwa/icon-192.png",
  "/static/images/pwa/icon-512.png"
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_VERSION).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_VERSION).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Dynamic HTML and APIs are never cached. If navigation fails, return one
  // static page containing no user, session, transaction, or CSRF data.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, { cache: "no-store" })
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // Only same-origin collected static assets may enter the cache. Private
  // media and every dynamic route remain network-only.
  if (!url.pathname.startsWith("/static/")) return;
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok && response.type === "basic") {
        const copy = response.clone();
        caches.open(CACHE_VERSION).then(cache => cache.put(request, copy));
      }
      return response;
    }))
  );
});
