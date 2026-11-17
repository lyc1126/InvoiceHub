const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const script = fs.readFileSync(path.join(__dirname, "../web/static/js/workspace-embed.js"), "utf8");

function setup() {
  const messages = [], sources = [], applied = [];
  const parent = { postMessage: (data, origin) => messages.push({ data, origin }) };
  const location = new URL("http://127.0.0.1:8766/costs?workspace_embed=1&workspace_view=view");
  class Source extends EventTarget {
    constructor(url) { super(); this.url = url; this.readyState = 1; this.closed = false; sources.push(this); }
    close() { this.closed = true; this.readyState = 2; }
  }
  const document = new EventTarget(); document.documentElement = { dataset: {} };
  const backdrops = [], observers = [];
  document.querySelectorAll = (selector) => selector === ".modal-backdrop" ? backdrops : [];
  class MutationObserver { constructor(callback) { observers.push(callback); } observe() {} }
  const frames = [];
  const mutate = () => { observers.forEach((callback) => callback([])); frames.splice(0).forEach((callback) => callback()); };
  const window = new EventTarget(); window.parent = parent; window.EventSource = Source;
  window.app = { api: async () => ({ id: "skin" }), clearSkin: () => applied.push("clear"), applySkinPayload: (data) => applied.push(data), skinBypassRequested: () => false };
  const context = vm.createContext({ window, parent, location, document, history: { state: null, replaceState(_state, _title, url) { location.href = new URL(url, location).href; } }, URL, URLSearchParams, EventTarget, Event, MessageEvent, MutationObserver, requestAnimationFrame: (callback) => frames.push(callback), getComputedStyle: (node) => ({ display: node.display ?? "grid" }) });
  vm.runInContext(script, context);
  function send(type, extra = {}, origin = location.origin, source = parent) {
    const event = new Event("message"); Object.assign(event, { origin, source, data: { channel: "invoicehub.workspace.v1", token: "view", type, ...extra } });
    window.dispatchEvent(event);
  }
  return { window, document, parent, location, messages, sources, applied, send, backdrops, mutate };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));

test("hidden modules pause SSE while listeners and reconnect revalidation survive", () => {
  const { window, sources, send } = setup();
  const stream = new window.EventSource("/api/v1/events/stream");
  let opened = 0, updates = 0;
  stream.onopen = () => opened++;
  stream.addEventListener("invoice.changed", () => updates++);
  sources[0].dispatchEvent(new Event("open"));
  sources[0].dispatchEvent(new MessageEvent("invoice.changed", { data: "{}" }));
  assert.equal(opened, 1); assert.equal(updates, 1);
  send("activity", { active: false }); assert.equal(sources[0].closed, true);
  sources[0].dispatchEvent(new MessageEvent("invoice.changed", { data: "late" })); assert.equal(updates, 1);
  send("activity", { active: true }); assert.equal(sources.length, 2);
  sources[1].dispatchEvent(new Event("open")); sources[1].dispatchEvent(new MessageEvent("invoice.changed", { data: "{}" }));
  assert.equal(opened, 2); assert.equal(updates, 2);
  stream.close(); send("activity", { active: false }); send("activity", { active: true }); assert.equal(sources.length, 2);
});

test("cross-origin, other-window and expired messages cannot change activity or recovery", () => {
  const { window, sources, send, applied } = setup();
  new window.EventSource("/api/v1/events/stream");
  send("activity", { active: false }, "https://example.org");
  send("activity", { active: false }, "http://127.0.0.1:8766", {});
  send("activity", { active: false, token: "expired" }); send("appearance", { recovery: true, token: "expired" });
  assert.equal(sources[0].closed, false); assert.equal(applied.length, 0);
});

test("a late saved-skin response cannot override a newer recovery request", async () => {
  const { window, send, applied, location } = setup();
  let resolve;
  window.app.api = () => new Promise((done) => { resolve = done; });
  send("appearance", { recovery: false }); send("appearance", { recovery: true });
  resolve({ id: "old-dark" }); await settle();
  assert.deepEqual(applied, ["clear"]); assert.equal(location.searchParams.get("no_skin"), "1");
});

test("appearance failures are diagnosable and a later explicit sync can recover", async () => {
  const { window, send, messages, applied } = setup();
  window.app.api = async () => { throw new Error("offline"); };
  send("appearance", { recovery: false }); await settle();
  assert.equal(messages.at(-1).data.type, "notice"); assert.equal(applied.length, 0);
  window.app.api = async () => ({ id: "current" }); send("appearance", { recovery: false }); await settle();
  assert.equal(applied[0].id, "current");
});

test("module links hand off to the shell while invoice details keep the view token", () => {
  const { document, messages, location } = setup();
  function click(href) {
    const link = { href: new URL(href, location).href, hasAttribute: () => false, target: "" };
    const event = new Event("click", { cancelable: true });
    Object.defineProperty(event, "target", { value: { closest: () => link } }); Object.defineProperty(event, "button", { value: 0 });
    document.dispatchEvent(event); return { link, event };
  }
  const module = click("/documents?workspace_embed=1&workspace_view=view&batch=inbound");
  assert.equal(module.event.defaultPrevented, true); assert.equal(messages.at(-1).data.href, "/documents?batch=inbound");
  const detail = click("/invoices/item?target_id=t"); assert.match(detail.link.href, /workspace_view=view/);
  const external = click("https://example.org/costs"); assert.equal(external.event.defaultPrevented, false);
});

test("dialog visibility is reported once per change and closed on pagehide", () => {
  const { window, messages, backdrops, mutate } = setup();
  const modal = () => messages.filter((item) => item.data.type === "modal").map((item) => item.data.open);
  const dialog = { hidden: true }; backdrops.push(dialog);
  mutate(); assert.deepEqual(modal(), []);
  dialog.hidden = false; mutate(); mutate(); assert.deepEqual(modal(), [true]);
  assert.equal(messages.at(-1).origin, "http://127.0.0.1:8766"); assert.equal(messages.at(-1).data.token, "view");
  dialog.display = "none"; mutate(); assert.deepEqual(modal(), [true, false]);
  dialog.display = "grid"; mutate(); window.dispatchEvent(new Event("pagehide")); assert.deepEqual(modal(), [true, false, true, false]);
});
