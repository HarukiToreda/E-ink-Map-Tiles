const CACHE = "eink-map-source-v1";
const SOURCE_HOSTS = new Set([
  "tiles.openfreemap.org",
  "basemap.nationalmap.gov",
  "s3.amazonaws.com",
]);

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || !SOURCE_HOSTS.has(url.hostname)) return;
  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE),
        cached = await cache.match(event.request);
      const network = fetch(event.request).then((response) => {
        if (response.ok || response.type === "opaque") {
          void cache.put(event.request, response.clone()).catch(() => undefined);
        }
        return response;
      });
      if (cached) {
        event.waitUntil(network.catch(() => undefined));
        return cached;
      }
      return network;
    })(),
  );
});
