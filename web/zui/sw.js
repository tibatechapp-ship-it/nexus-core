/* Nexus ZUI service worker — v1: app-shell minimal (best-effort offline).
   العقد: لا يخزّن أي استجابة API — فقط الأصول الساكنة للقشرة. */
const CACHE = "nexus-zui-v1";
const SHELL = [
  "/zui/index.html",
  "/zui/css/zui.css",
  "/zui/js/zui.js",
  "/zui/manifest.json",
  "/zui/icon.svg",
];

self.addEventListener("install", (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== "GET" || !url.pathname.startsWith("/zui/") || url.pathname === "/zui/sw.js") {
    return; // لا تتدخل في API ولا خارج /zui
  }
  ev.respondWith(
    caches.match(ev.request).then((hit) => hit || fetch(ev.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(ev.request, copy)).catch(() => {});
      return res;
    }))
  );
});
