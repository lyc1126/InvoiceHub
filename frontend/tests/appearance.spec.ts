import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppearanceToggle from "../src/components/AppearanceToggle.vue";
import { setSkinIdentity, skinBypassRequested } from "../src/appearance";

const DARK = { id: "website-dark", stylesheet_url: "/api/v1/skins/website-dark/files/skin.css?v=synthetic" };
const payload = (id = "") => ({ ok: true, enabled_skin_id: id || null, active_skin: id ? { ...DARK, id } : null, skins: [DARK] });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let wrapper: VueWrapper | undefined;
const pendingStyle = () => document.querySelector<HTMLLinkElement>('link[data-workspace-appearance="pending"]')!;
const writes = () => vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");

function mountToggle(recovery = false) {
  wrapper = mount(AppearanceToggle, { props: { recovery }, attachTo: document.body });
  return wrapper;
}

function savedSkin(id: string) {
  const link = document.createElement("link");
  link.id = "activeSkinStylesheet";
  link.dataset.skinId = id;
  document.head.appendChild(link);
  setSkinIdentity(id);
  return link;
}

beforeEach(() => {
  // Happy DOM emits an immediate error for disabled CSS downloads. The component
  // tests control load/error timing; real CSS is checked separately in a browser.
  const append = document.head.appendChild.bind(document.head);
  vi.spyOn(document.head, "appendChild").mockImplementation(<T extends Node>(node: T): T => {
    if (node instanceof HTMLLinkElement) node.removeAttribute("rel");
    return append(node);
  });
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.querySelectorAll('#activeSkinStylesheet, link[data-workspace-appearance="pending"]').forEach((item) => item.remove());
  setSkinIdentity("");
  document.body.innerHTML = "";
  delete document.documentElement.dataset.workspaceIsolatedSkins;
});

describe("workspace appearance", () => {
  it.each(["ink-pulse", "animal-island"])("isolates %s without writing preferences or loading its CSS on read-back", async (id) => {
    document.documentElement.dataset.workspaceIsolatedSkins = "animal-island ink-pulse";
    const original = savedSkin(id);
    vi.stubGlobal("fetch", vi.fn(async () => response(payload(id))));
    const view = mountToggle();
    expect(original.isConnected).toBe(false);
    expect(document.documentElement.dataset.activeSkin).toBeUndefined();
    await (view.vm as unknown as { syncFromServer: () => Promise<void> }).syncFromServer();
    expect(pendingStyle()).toBeNull();
    expect(writes()).toHaveLength(0);
    expect(view.get(".appearance-toggle").attributes("disabled")).toBeUndefined();
    expect(view.get(".appearance-toggle").attributes("aria-pressed")).toBe("false");
  });

  it("loads inactive CSS before saving and replaces a saved custom skin only after confirmation", async () => {
    const original = savedSkin("ink-pulse");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => response(payload(url.endsWith("/enable") ? DARK.id : "ink-pulse"))));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    await flushPromises();
    expect(pendingStyle().media).toBe("not all");
    expect(writes()).toHaveLength(0);
    expect(original.isConnected).toBe(true);
    expect(view.get(".appearance-toggle").attributes("aria-busy")).toBe("true");
    await view.get(".appearance-toggle").trigger("click");
    pendingStyle().dispatchEvent(new Event("load"));
    await flushPromises();
    expect(writes()).toHaveLength(1);
    expect(writes()[0]![1]?.body).toBe("{}");
    expect(original.isConnected).toBe(false);
    expect(document.getElementById("activeSkinStylesheet")?.getAttribute("media")).toBe("all");
    expect(document.documentElement.dataset.activeSkin).toBe(DARK.id);
    expect(document.body.classList.contains("skin-website-dark")).toBe(true);
    expect(document.body.classList.contains("skin-ink-pulse")).toBe(false);
    expect(view.get(".appearance-toggle").attributes("aria-pressed")).toBe("true");
  });

  it("resets the shared preference before removing the current dark stylesheet", async () => {
    const original = savedSkin(DARK.id);
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    expect(original.isConnected).toBe(true);
    expect(writes()[0]![0]).toBe("/api/v1/skins/reset");
    finish(response(payload()));
    await flushPromises();
    expect(original.isConnected).toBe(false);
    expect(document.documentElement.dataset.activeSkin).toBeUndefined();
    expect(view.get(".appearance-toggle").attributes("aria-pressed")).toBe("false");
  });

  it.each(["error", "timeout"])("keeps the current skin and never saves on a stylesheet %s", async (failure) => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const original = savedSkin("animal-island");
    vi.stubGlobal("fetch", vi.fn(async () => response(payload("animal-island"))));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    await flushPromises();
    if (failure === "error") pendingStyle().dispatchEvent(new Event("error"));
    else await vi.advanceTimersByTimeAsync(8001);
    await flushPromises();
    expect(writes()).toHaveLength(0);
    expect(original.isConnected).toBe(true);
    expect(pendingStyle()).toBeNull();
    expect(view.get('[role="alert"]').text()).toContain(failure === "error" ? "加载失败" : "加载超时");
    expect(view.get(".appearance-toggle").attributes("disabled")).toBeUndefined();
  });

  it.each(["lost", "mismatch"])("retains the live style without replaying a %s save response", async (failure) => {
    const original = savedSkin("ink-pulse");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/enable")) {
        if (failure === "lost") throw new Error("synthetic disconnect");
        return response(payload("animal-island"));
      }
      return response(payload("ink-pulse"));
    }));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    await flushPromises();
    pendingStyle().dispatchEvent(new Event("load"));
    await flushPromises();
    expect(writes()).toHaveLength(1);
    expect(original.isConnected).toBe(true);
    expect(document.documentElement.dataset.activeSkin).toBe("ink-pulse");
    expect(view.get('[role="alert"]').text()).toContain("刷新页面核对");
    expect(pendingStyle()).toBeNull();
  });

  it("rejects an external stylesheet without persisting a preference", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...payload(), skins: [{ ...DARK, stylesheet_url: "https://invalid.example/skin.css" }] })));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    await flushPromises();
    expect(writes()).toHaveLength(0);
    expect(pendingStyle()).toBeNull();
    expect(view.get('[role="alert"]').text()).toContain("资源地址无效");
  });

  it("cancels pending CSS on unmount without writing or accepting a late load", async () => {
    const original = savedSkin("ink-pulse");
    vi.stubGlobal("fetch", vi.fn(async () => response(payload("ink-pulse"))));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    await flushPromises();
    const link = pendingStyle();
    view.unmount();
    wrapper = undefined;
    link.dispatchEvent(new Event("load"));
    await flushPromises();
    expect(link.isConnected).toBe(false);
    expect(original.isConnected).toBe(true);
    expect(writes()).toHaveLength(0);
  });

  it("does not apply a save response after unmount", async () => {
    const original = savedSkin(DARK.id);
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const view = mountToggle();
    await view.get(".appearance-toggle").trigger("click");
    view.unmount();
    wrapper = undefined;
    finish(response(payload()));
    await flushPromises();
    expect(original.isConnected).toBe(true);
    expect(document.documentElement.dataset.activeSkin).toBe(DARK.id);
    expect(writes()).toHaveLength(1);
  });

  it("stays light and makes no requests in recovery mode", async () => {
    savedSkin(DARK.id);
    vi.stubGlobal("fetch", vi.fn());
    const view = mountToggle(true);
    await view.get(".appearance-toggle").trigger("click");
    expect(document.getElementById("activeSkinStylesheet")).toBeNull();
    expect(document.documentElement.dataset.activeSkin).toBeUndefined();
    expect(view.get(".appearance-toggle").attributes("disabled")).toBeDefined();
    expect(view.get(".appearance-toggle").attributes("aria-busy")).toBe("false");
    expect(fetch).not.toHaveBeenCalled();
    for (const value of ["1", "true", "YES", " on "]) expect(skinBypassRequested(value)).toBe(true);
    for (const value of [undefined, "0", "false"]) expect(skinBypassRequested(value)).toBe(false);
    expect(skinBypassRequested(["0", "YES"])).toBe(true);
    expect(skinBypassRequested(["YES", "0"])).toBe(false);
  });
});
