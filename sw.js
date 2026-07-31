/* sw.js — minimal offline cache for chronicaria.github.io */
"use strict";

const VERSION = "broadsheet-v5";

const PRECACHE = [
  "/",
  "/index.html",
  "/assets/styles.css",
  "/assets/daily.css",
  "/assets/site.js",
  "/assets/daily.js",
  "/assets/ui.js",
  "/daily/index.html"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(PRECACHE))
      .catch(() => { /* best effort — never block install */ })
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;

  /* Anything that carries the current numbers goes to the network first, so a
     published correction is visible on the next load rather than whenever the
     cache name next changes.  `/data/` alone missed `/valorant/data.js`, which
     is a payload despite living beside the code that reads it. */
  const networkFirst =
    req.mode === "navigate" ||
    url.pathname.includes("/data/") ||
    url.pathname.endsWith("data.js") ||
    url.pathname.endsWith("daily.xml");

  if (networkFirst) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(VERSION).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  /* Everything else is stale-while-revalidate rather than cache-first.
     Cache-first never re-checked, so a cached asset was pinned until VERSION
     changed by hand -- miss that bump and the site serves the previous build
     forever, which is exactly how a shipped update stayed invisible. Serving
     the cached copy keeps it fast and keeps it working offline; the background
     refresh means the next load is current without anyone remembering. */
  event.respondWith(
    caches.match(req).then((cached) => {
      const fresh = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(VERSION).then((cache) => cache.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
