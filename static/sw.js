// Service worker: makes the app installable and shows a friendly page offline.
// Pages with financial data are never cached – only design files are.
"use strict";

const CACHE = "finanz-static-v1";
const OFFLINE_URL = "/offline";
const PRECACHE = [
  OFFLINE_URL,
  "/static/style.css",
  "/static/app.js",
  "/static/img/honeycomb.svg",
  "/static/icons/logo.svg",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(staticFile(request, url));
  }
});

async function staticFile(request, url) {
  const cache = await caches.open(CACHE);
  const exact = await cache.match(request);
  if (exact) return exact;
  try {
    const response = await fetch(request);
    if (response.ok) {
      // Drop older versions of the same file (?v=...) before storing the new one.
      for (const old of await cache.keys()) {
        if (new URL(old.url).pathname === url.pathname) await cache.delete(old);
      }
      await cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const fallback = await cache.match(request, { ignoreSearch: true });
    if (fallback) return fallback;
    throw error;
  }
}
