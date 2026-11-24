import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ClassicModuleView from "../src/components/ClassicModuleView.vue";
import { frameLocation, MODULE_CHANNEL, workspaceDestination } from "../src/modules";
import { useModulesStore } from "../src/stores/modules";

let cleanup: (() => void)[];
beforeEach(() => {
  vi.useFakeTimers(); setActivePinia(createPinia()); cleanup = [];
  const windows = new WeakMap<HTMLIFrameElement, Window>();
  // happy-dom intentionally disables frame loading. Model distinct browsing
  // contexts here; real document loading/history is covered in browser QA.
  vi.spyOn(HTMLIFrameElement.prototype, "contentWindow", "get").mockImplementation(function (this: HTMLIFrameElement) {
    if (!windows.has(this)) windows.set(this, { postMessage: vi.fn() } as unknown as Window);
    return windows.get(this)!;
  });
});
afterEach(() => { cleanup.forEach((close) => close()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); });
function moduleView() {
  const wrapper = mount(ClassicModuleView, { props: { module: "costs", path: "/costs", label: "成本分析", active: true, recovery: false } });
  cleanup.push(() => wrapper.unmount());
  const frame = () => wrapper.get("iframe").element as HTMLIFrameElement;
  const post = (type: string, extra = {}, origin = location.origin, source = frame().contentWindow) => {
    const token = new URL(frame().src, location.href).searchParams.get("workspace_view");
    window.dispatchEvent(new MessageEvent("message", { origin, source, data: { channel: MODULE_CHANNEL, token, type, ...extra } }));
  };
  return { wrapper, frame, post };
}

describe("cached classic module bridge", () => {
  it("accepts only a matching origin, frame window and live view token", async () => {
    const { wrapper, post } = moduleView();
    post("ready", {}, "https://example.org"); post("ready", {}, location.origin, window); post("ready", { token: "expired" });
    await flushPromises(); expect(wrapper.find('[role="status"]').exists()).toBe(true);
    post("ready"); await flushPromises(); expect(wrapper.find('[role="status"]').exists()).toBe(false);
    post("navigate", { href: "/documents?batch=inbound" });
    expect(wrapper.emitted("navigate")).toEqual([["/documents?batch=inbound"]]);
    post("navigate", { href: "https://example.org/documents" }); expect(wrapper.emitted("navigate")).toHaveLength(1);
  });

  it("preserves the document on rail switches and rejects navigation from hidden views", async () => {
    const { wrapper, frame, post } = moduleView();
    const original = frame(); const send = vi.spyOn(original.contentWindow!, "postMessage");
    await wrapper.setProps({ active: false });
    post("navigate", { href: "/settings" }); expect(wrapper.emitted("navigate")).toBeUndefined();
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ type: "activity", active: false }), location.origin);
    await wrapper.setProps({ active: true }); expect(frame()).toBe(original);
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ type: "activity", active: true }), location.origin);
  });

  it("replaces only the refreshed context and ignores an old document's response", async () => {
    const { wrapper, frame, post } = moduleView();
    const original = frame(); const source = original.contentWindow;
    const token = new URL(original.src, location.href).searchParams.get("workspace_view");
    useModulesStore().reload("documents"); await flushPromises(); expect(frame()).toBe(original);
    useModulesStore().reload("costs"); await flushPromises(); expect(frame()).not.toBe(original);
    expect(new URL(frame().src, location.href).searchParams.get("workspace_view")).not.toBe(token);
    window.dispatchEvent(new MessageEvent("message", { source, origin: location.origin, data: { channel: MODULE_CHANNEL, token, type: "ready" } }));
    await flushPromises(); expect(wrapper.find('[role="status"]').exists()).toBe(true);
    post("ready"); await flushPromises(); expect(wrapper.find('[role="status"]').exists()).toBe(false);
  });

  it("dims the shell only for the active frame's authenticated dialog and clears on reload", async () => {
    const { wrapper, frame, post } = moduleView();
    const modules = useModulesStore();
    post("modal", { open: true }, "https://example.org"); post("modal", { open: true, token: "expired" }); post("modal", { open: "yes" });
    await flushPromises(); expect(modules.modals.costs).toBeFalsy();
    post("modal", { open: true }); await flushPromises();
    expect(modules.modals.costs).toBe(true); expect(frame().classList.contains("module-frame--modal")).toBe(true);
    await wrapper.setProps({ active: false }); expect(modules.modals.costs).toBe(false);
    await wrapper.setProps({ active: true }); expect(modules.modals.costs).toBe(true);
    // A replaced document starts without a dialog; a stuck scrim would block the shell.
    modules.reload("costs"); await flushPromises(); expect(modules.modals.costs).toBe(false);
    post("modal", { open: true }); await flushPromises(); wrapper.unmount(); expect(modules.modals.costs).toBe(false);
  });

  it("reports loading timeout, retries explicitly and syncs recovery without reloading drafts", async () => {
    const { wrapper, frame, post } = moduleView();
    await vi.advanceTimersByTimeAsync(12000); expect(wrapper.get('[role="alert"]').text()).toContain("未能完成加载");
    await wrapper.get('[role="alert"] button').trigger("click"); post("ready"); await flushPromises();
    const original = frame(); const send = vi.spyOn(original.contentWindow!, "postMessage");
    await wrapper.setProps({ recovery: true });
    expect(frame()).toBe(original); expect(send).toHaveBeenCalledWith(expect.objectContaining({ type: "appearance", recovery: true }), location.origin);
    post("appearance-changed"); post("state-changed"); expect(wrapper.emitted("appearance")).toHaveLength(1); expect(wrapper.emitted("stateChanged")).toHaveLength(1);
  });

  it("keeps explicit handoff queries and recovery in the new document", async () => {
    const { frame } = moduleView();
    useModulesStore().open("costs", "/costs?source=test#reference"); await flushPromises();
    const url = new URL(frame().src, location.href);
    expect(url.searchParams.get("source")).toBe("test"); expect(url.searchParams.get("workspace_embed")).toBe("1"); expect(url.hash).toBe("#reference");
  });
});

describe("fixed page allowlists", () => {
  it("allows only local module destinations and strips presentation tokens", () => {
    expect(workspaceDestination("/documents?workspace_embed=1&workspace_view=old&batch=inbound")).toBe("/documents?batch=inbound");
    expect(workspaceDestination("https://example.org/settings")).toBeNull();
    expect(workspaceDestination("/api/v1/settings")).toBeNull();
    expect(frameLocation("/invoices/key?target_id=t", true)).toContain("no_skin=1");
    expect(frameLocation("/skins", false)).toContain("workspace_embed=1");
    expect(() => frameLocation("https://example.org/costs", false)).toThrow();
    expect(() => frameLocation("/website/", false)).toThrow();
  });
});
