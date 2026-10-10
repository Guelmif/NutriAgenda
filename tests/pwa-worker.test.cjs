const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const origin = "https://clinica.example";
const worker = fs.readFileSync(
  path.join(__dirname, "../agenda/static/agenda/pwa/worker.js"),
  "utf8",
);

function environment() {
  const listeners = {};
  const storage = new Map();
  const requests = [];
  let offline = false;
  const config = {
    cacheName: "clinicaunopar-public-current",
    offlineUrl: "/static/agenda/pwa/offline.html",
    publicAssets: [
      "/static/agenda/pwa/offline.html",
      "/static/agenda/pwa/icon-192.png",
    ],
  };
  const caches = {
    async open(name) {
      if (!storage.has(name)) storage.set(name, new Map());
      const data = storage.get(name);
      return {
        async put(url, response) {
          data.set(url, response.clone());
        },
        async match(url) {
          return data.get(url)?.clone();
        },
      };
    },
    async keys() {
      return [...storage.keys()];
    },
    async delete(name) {
      return storage.delete(name);
    },
  };
  const context = {
    URL,
    Response,
    caches,
    self: {
      location: { origin },
      PWA_CONFIG: config,
      addEventListener(name, handler) {
        listeners[name] = handler;
      },
      async skipWaiting() {},
      clients: { async claim() {} },
    },
    async fetch(request, options) {
      const url = typeof request === "string" ? request : request.url;
      requests.push({ url, options });
      if (offline) throw new TypeError("Network unavailable");
      const isIcon = url.endsWith(".png");
      const publicPage = url.endsWith("offline.html");
      return new Response(
        publicPage ? "Generic offline page" : "Private session data",
        {
          headers: { "Content-Type": isIcon ? "image/png" : "text/html" },
        },
      );
    },
  };
  vm.runInNewContext(worker, context);
  return {
    config,
    storage,
    requests,
    async lifecycle(name) {
      let pending;
      listeners[name]({
        waitUntil(value) {
          pending = value;
        },
      });
      await pending;
    },
    async request(pathname, { method = "GET", mode = "navigate" } = {}) {
      let response;
      listeners.fetch({
        request: { url: new URL(pathname, origin).href, method, mode },
        respondWith(value) {
          response = value;
        },
      });
      return await response;
    },
    setOffline(value) {
      offline = value;
    },
  };
}

test("installation caches only explicit public assets without session credentials", async () => {
  const app = environment();
  await app.lifecycle("install");
  assert.equal(app.storage.get(app.config.cacheName).size, 2);
  assert.ok(
    app.requests.every(({ options }) => options.credentials === "omit"),
  );
});

test("patient pages always use the network and never enter offline storage", async () => {
  const app = environment();
  await app.lifecycle("install");
  const response = await app.request("/clientes/42/");
  assert.equal(await response.text(), "Private session data");
  assert.equal(app.requests.at(-1).options.cache, "no-store");
  const entries = app.storage.get(app.config.cacheName);
  assert.equal(entries.size, 2);
  assert.ok(
    [...entries.keys()].every((url) => url.includes("/static/agenda/pwa/")),
  );
  app.setOffline(true);
  assert.equal(
    await (await app.request("/clientes/42/")).text(),
    "Generic offline page",
  );
  app.setOffline(false);
  assert.equal(
    await (await app.request("/clientes/42/")).text(),
    "Private session data",
  );
});

test("API calls, submissions, and external requests are not intercepted or queued", async () => {
  const app = environment();
  for (const [url, options] of [
    ["/api/agendamentos/?data=2026-10-10", { mode: "cors" }],
    ["/agendamentos/42/situacao/cancelar/", { method: "POST" }],
    ["/agendar/formulario/", { method: "POST" }],
    ["https://external.example/", {}],
  ]) {
    assert.equal(await app.request(url, options), undefined);
  }
  assert.equal(app.requests.length, 0);
  assert.equal(app.storage.size, 0);
});

test("a new version removes only obsolete ClínicaUnopar public caches", async () => {
  const app = environment();
  app.storage.set("clinicaunopar-public-old", new Map());
  app.storage.set(app.config.cacheName, new Map());
  app.storage.set("other-application", new Map());
  await app.lifecycle("activate");
  assert.deepEqual(
    [...app.storage.keys()],
    [app.config.cacheName, "other-application"],
  );
});

test("offline navigation without a cached fallback fails clearly", async () => {
  const app = environment();
  app.setOffline(true);
  const response = await app.request("/");
  assert.equal(response.status, 503);
  assert.match(await response.text(), /Sem conexão/);
});
