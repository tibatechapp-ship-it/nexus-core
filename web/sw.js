/* nexus-core service worker (v2.0 PWA).
 *
 * Strategy:
 *  - App shell (the chat UI) is precached → the app opens offline.
 *  - Same-origin GET /api/* is network-first with a cache fallback so the last
 *    known conversations / genome / health survive a network drop.
 *  - Same-origin static GETs (icons, manifest) are cache-first.
 *  - Failed POSTs are NOT queued here — the page enqueues them (IndexedDB) and
 *    replays on 'online', which keeps streaming semantics intact.
 */
const CACHE = "nexus-shell-v2";
const SHELL = [
  "/", "/manifest.json", "/offline.html",
  "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png",
  "/vendor/highlight.min.js", "/vendor/github-dark.min.css"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;      // let CDNs pass through
  if (req.method !== "GET") return;                     // POSTs are page-handled

  // Navigations → network first, then cached shell, then offline page.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/").then((r) => r || caches.match("/offline.html")))
    );
    return;
  }

  // API GETs → network first, cache fallback.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || new Response(
          JSON.stringify({ offline: true }), { headers: { "Content-Type": "application/json" } }
        )))
    );
    return;
  }

  // Static same-origin → cache first, refresh in the background.
  event.respondWith(
    caches.match(req).then((cached) => {
      const net = fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
