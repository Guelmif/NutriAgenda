/* Only these public assets can enter Cache Storage. Never cache patient pages,
   API responses, submissions, or session-dependent content. */
const { cacheName, offlineUrl, publicAssets } = self.PWA_CONFIG;
const absolute = (url) => new URL(url, self.location.origin).href;
const offlinePage = absolute(offlineUrl);
const allowedAssets = new Set(publicAssets.map(absolute));

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(cacheName);
      for (const url of allowedAssets) {
        const response = await fetch(url, {
          credentials: "omit",
          cache: "reload",
        });
        const expectedType = url === offlinePage ? "text/html" : "image/png";
        if (
          !response.ok ||
          response.redirected ||
          !response.headers.get("Content-Type")?.includes(expectedType)
        ) {
          throw new Error("Arquivo público do aplicativo indisponível.");
        }
        await cache.put(url, response);
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter(
            (name) =>
              name.startsWith("clinicaunopar-public-") && name !== cacheName,
          )
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (
    request.method !== "GET" ||
    new URL(request.url).origin !== self.location.origin
  ) {
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, { cache: "no-store" }).catch(async () => {
        const cache = await caches.open(cacheName);
        return (
          (await cache.match(offlinePage)) ||
          new Response("Sem conexão. Conecte-se e tente novamente.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          })
        );
      }),
    );
  } else if (allowedAssets.has(request.url)) {
    event.respondWith(
      caches.open(cacheName).then(async (cache) => {
        return (await cache.match(request.url)) || fetch(request);
      }),
    );
  }
});
