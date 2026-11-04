/*
 * NovaMind Platform — service worker (PWA offline shell).
 *
 * Policy, in plain terms:
 *   * The static shell (HTML/CSS/JS/icons/manifest) is served cache-first:
 *     instant loads and full offline start. The cache is versioned, and on
 *     activate every older cache is deleted — stale shells cannot survive
 *     an update.
 *   * API calls (anything under /api/) are NEVER cached: agent runs, council
 *     deliberations and metrics are per-request state; caching them would
 *     show the user yesterday's answer. They go straight to the network.
 *   * Non-GET is passed through untouched.
 *   * A failed network fetch for a non-cached request degrades to an honest
 *     offline response (503 + JSON body) instead of an opaque browser error.
 *
 * Bump CACHE_VERSION on any change to the cached shell so clients pick it up.
 */
'use strict';

const CACHE_VERSION = 'novamind-shell-v1';
const SHELL_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') {
    return; // writes are never intercepted
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return; // third-party: browser handles it
  }
  if (url.pathname.startsWith('/api/') || url.pathname.includes('/api/')) {
    return; // never cache API state — the shell is cacheable, the data is not
  }

  event.respondWith(
    caches.match(request, { ignoreSearch: url.pathname.endsWith('/index.html') }).then(
      (cached) => {
        if (cached) {
          return cached;
        }
        return fetch(request)
          .then((response) => {
            if (response && response.ok && response.type === 'basic') {
              const copy = response.clone();
              caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() =>
            new Response(
              JSON.stringify({ ok: false, offline: true, error: 'offline: the shell is available, but this resource needs the network' }),
              { status: 503, headers: { 'Content-Type': 'application/json; charset=utf-8' } }
            )
          );
      }
    )
  );
});
