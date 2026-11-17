import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "../src/api/client";
import { TEMPORARY_API as API, useTemporaryRecognition, type TemporarySession } from "../src/temporary";
import TemporaryPreview from "../src/components/TemporaryPreview.vue";

vi.mock("../src/api/client", () => ({ request: vi.fn() }));
const rpc = vi.mocked(request);
const ready = (id: string): TemporarySession => ({ id, title: id, status: "ready", count: 1, completed: 1, created_at: "2026-11-14T08:00:00Z", unavailable: [],
  items: [{ id: `${id}-file`, name: `${id}.xml`, status: "ready", result: { seller: "合成\t销售方", amount: "113.00" } }] });
let records: TemporarySession[];
let cleanup: (() => void)[];

function harness() {
  const active = ref(true);
  let state!: ReturnType<typeof useTemporaryRecognition>;
  const wrapper = mount(defineComponent({ setup() { state = useTemporaryRecognition(active); return () => h("div"); } }));
  cleanup.push(() => wrapper.unmount());
  return { state, active };
}

beforeEach(() => {
  vi.useFakeTimers(); cleanup = []; records = [ready("old")];
  rpc.mockReset();
  rpc.mockImplementation(async (path) => {
    if (path === `${API}/settings`) return { settings: { batch_limit: 20, auto_open: true } };
    if (path === `${API}/sessions`) return { sessions: records };
    return { session: records.find((item) => path.endsWith(`/${item.id}`)) };
  });
});
afterEach(() => { cleanup.forEach((close) => close()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("temporary workspace source and request boundaries", () => {
  it("revalidates displayed history even while a different worker is running", async () => {
    records.push({ ...ready("worker"), status: "running", completed: 0 });
    const { state } = harness(); await flushPromises();
    await state.show("old");
    expect(state.result.value?.id).toBe("old");
    records[0] = { ...ready("old"), unavailable: ["old.xml"], items: undefined };
    await vi.advanceTimersByTimeAsync(850);
    expect(state.running.value).toBe("worker");
    expect(state.result.value).toBeNull();
    expect(state.message.value).toContain("old.xml");
    expect(rpc).toHaveBeenCalledWith(`${API}/sessions/worker`);
  });

  it("keeps valid history visible when the other worker loses a source", async () => {
    records.push({ ...ready("worker"), status: "running", unavailable: ["worker.xml"] });
    const { state } = harness(); await flushPromises(); await state.show("old");
    await vi.advanceTimersByTimeAsync(850);
    expect(state.result.value?.id).toBe("old");
    expect(state.selected.value).toBe("old");
  });

  it("drops a late picker after leaving and preserves the queue/settings draft on return", async () => {
    const { state, active } = harness(); await flushPromises();
    state.files.value = [{ id: "existing", name: "原队列.xml" }];
    state.settingsDraft.batch_limit = 7; state.settingsDirty.value = true;
    let resolve!: (value: unknown) => void;
    rpc.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const pick = state.pick(); active.value = false; await flushPromises();
    resolve({ files: [{ id: "late", name: "迟到.xml" }] }); await pick;
    active.value = true; await flushPromises();
    expect(state.files.value.map((file) => file.id)).toEqual(["existing"]);
    expect(state.settingsDraft.batch_limit).toBe(7);
  });

  it("ignores an old history response after a newer selection or hiding", async () => {
    const { state, active } = harness(); await flushPromises();
    let resolve!: (value: unknown) => void;
    rpc.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const old = state.show("old");
    records.push(ready("new")); await state.show("new");
    resolve({ session: ready("old") }); await old;
    expect(state.result.value?.id).toBe("new");
    active.value = false; await flushPromises();
    await vi.advanceTimersByTimeAsync(10000);
    expect(state.result.value).toBeNull();
  });

  it("submits queue order once and resolves uncertain creation only through history", async () => {
    const { state } = harness(); await flushPromises();
    state.files.value = [{ id: "a", name: "a.xml" }, { id: "b", name: "b.pdf" }]; state.move(0, 1);
    rpc.mockRejectedValueOnce(new Error("响应丢失"));
    await state.start(); await vi.advanceTimersByTimeAsync(10000);
    const creates = rpc.mock.calls.filter(([, options]) => options?.method === "POST");
    expect(creates).toEqual([[`${API}/sessions`, { method: "POST", body: { ids: ["b", "a"] } }]]);
    expect(state.message.value).toContain("查看历史");
    state.switchView("history"); await flushPromises();
    expect(state.sessions.value[0]?.id).toBe("old");
  });

  it("rechecks sources before copying, excludes actions, and clears invalid fields", async () => {
    const clipboard = { writeText: vi.fn(async (_value: string) => {}) }; vi.stubGlobal("navigator", { clipboard });
    const { state } = harness(); await flushPromises(); await state.show("old"); await state.copy();
    const tsv = clipboard.writeText.mock.calls[0]![0];
    expect(tsv).toContain("113.00"); expect(tsv).toContain("合成 销售方"); expect(tsv).not.toContain("预览");
    records[0] = { ...ready("old"), unavailable: ["old.xml"], items: undefined };
    await state.copy(); expect(clipboard.writeText).toHaveBeenCalledTimes(1); expect(state.result.value).toBeNull();
  });

  it("keeps auto-open disabled and never interrupts a different history being viewed", async () => {
    records.push({ ...ready("worker"), status: "running" });
    const { state } = harness(); await flushPromises();
    state.settings.value.auto_open = false; records[1] = ready("worker");
    await vi.advanceTimersByTimeAsync(850);
    expect(state.view.value).toBe("draft"); expect(state.running.value).toBeNull();
    records[1] = { ...ready("worker"), status: "running" }; await state.history(); await state.show("old");
    state.settings.value.auto_open = true; records[1] = ready("worker");
    await vi.advanceTimersByTimeAsync(850);
    expect(state.result.value?.id).toBe("old");
  });
});

describe("temporary native-content preview", () => {
  it("renders XML as text, drops late pages, clears invalid content and stops hidden checks", async () => {
    let resolve!: (value: unknown) => void;
    rpc.mockImplementation(async (path) => path.endsWith("/text") ? new Promise((done) => { resolve = done; }) : { type: "text", pages: 0 });
    const wrapper = mount(TemporaryPreview, { props: { file: { id: "one", name: "one.xml" }, active: true } }); cleanup.push(() => wrapper.unmount());
    await flushPromises();
    const late = resolve;
    await wrapper.setProps({ file: { id: "two", name: "two.xml" } }); await flushPromises();
    resolve({ text: "<script>unsafe()</script>" }); await flushPromises();
    late({ text: "旧正文" }); await flushPromises();
    expect(wrapper.get("pre").text()).toBe("<script>unsafe()</script>"); expect(wrapper.find("script").exists()).toBe(false);
    rpc.mockRejectedValueOnce(new Error("原文件失效")); await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.find("pre").exists()).toBe(false); expect(wrapper.text()).toContain("原文件失效");
    await wrapper.setProps({ active: false }); const count = rpc.mock.calls.length; await vi.advanceTimersByTimeAsync(10000);
    expect(rpc).toHaveBeenCalledTimes(count);
  });
});
