import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import ServerSourcesPanel from "../src/components/ServerSourcesPanel.vue";

const sid = "a".repeat(32), folder = "b".repeat(32), file = "c".repeat(32);
function setup(online = true, unsupported = false) {
  const source = { id: sid, name: "合成服务器", protocol: "mounted", root: "/synthetic/share", revision: 1,
    connection: online ? "online" : "offline", sync: "idle", error: "", fingerprints: [], generation: "g1", snapshot: "current",
    last_complete_at: "2026-11-19T00:00:00Z", cached_count: 1, entry_count: 2, cache_budget: 256 * 1024**2,
    binding: { company_id: "saved-company", role: "issued_invoice_dir" } };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url); let body: unknown = { ok: true };
    if (path === "/api/v1/sources") body = { sources: [source] };
    else if (path.includes("/entries")) {
      const inside = new URL(path, "http://localhost").searchParams.get("parent_id") === folder;
      body = { source, items: inside ? [{ id: file, name: unsupported ? "说明.txt" : "合成.xml", relative: "子目录/合成.xml", kind: "file", size: 42 }] : [{ id: folder, name: "子目录", relative: "子目录", kind: "directory", size: 0 }],
        count: 1, page: 1, scope: { files: 1, bytes: 42, readable_files: unsupported ? 0 : 1 }, breadcrumbs: [{ id: "", name: source.name }, ...(inside ? [{ id: folder, name: "子目录" }] : [])] };
    } else if (path.includes("/summary")) body = { available: false };
    else if (path.endsWith("/tasks")) body = { source };
    else if (path.endsWith("/previews") && init?.method === "POST") body = { job_id: "opaque-job", preview_type: "text", page_count: 0, stale: !online, verified_at: "2026-11-19", entry_id: file };
    else if (path.endsWith("/text")) body = { text: "<Invoice>合成</Invoice>" };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => vi.unstubAllGlobals());

describe("服务器只读来源面板", () => {
  it("按不透明目录与文件标识浏览，并在主区内切换放大和收起", async () => {
    const fetch = setup();
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder); await flushPromises();
    expect(wrapper.text()).toContain("合成.xml");
    const open = wrapper.findAll(".server-files button")[0]!;
    await open.trigger("click"); await flushPromises();
    expect(wrapper.get("pre").text()).toContain("<Invoice>合成</Invoice>");
    const download = fetch.mock.calls.find(([url]) => url.endsWith("/tasks"));
    expect(JSON.parse(String(download?.[1]?.body))).toEqual({ kind: "download", entry_id: file });
    expect(fetch.mock.calls.some(([url]) => url.includes(`/entries?parent_id=${folder}`))).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes("/invoices/"))).toBe(false);
    await wrapper.get('[aria-label="放大文件面板"]').trigger("click");
    expect(wrapper.get(".server-panel").classes()).toContain("server-panel--wide");
    await wrapper.get('[aria-label="收起服务器文件"]').trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(1);
    expect(wrapper.text()).toContain("公司、做账、税费等模块尚未接入");
    wrapper.unmount();
  });

  it("离线副本明确标记，身份和服务器认证不使用浏览器密码输入", async () => {
    const fetch = setup(false);
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder); await flushPromises();
    expect(wrapper.get(".server-files button").text()).toContain("查看离线副本");
    await wrapper.get(".server-files button").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("离线副本（可能过期）");
    const preview = fetch.mock.calls.find(([url]) => url.endsWith("/previews"));
    expect(JSON.parse(String(preview?.[1]?.body)).allow_stale).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.endsWith("/tasks"))).toBe(false);
    await wrapper.findAll("button").find(b => b.text() === "添加")!.trigger("click");
    await wrapper.get(".source-form select").setValue("sftp");
    expect(wrapper.text()).toContain("SSH Agent");
    expect(wrapper.find('input[type="password"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("收起面板释放预览租约", async () => {
    const fetch = setup(false);
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder); await flushPromises();
    await wrapper.get('.server-files button').trigger('click'); await flushPromises();
    await wrapper.setProps({ open: false }); await flushPromises();
    expect(fetch.mock.calls.some(([url, init]) => url.endsWith('/previews/opaque-job') && init?.method === 'DELETE')).toBe(true);
    wrapper.unmount();
  });

  it("只有不支持格式仍可查元信息，空内容与筛选无匹配分开提示", async () => {
    setup(true, true);
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="切换服务器目录"]').setValue(folder); await flushPromises();
    expect(wrapper.text()).toContain("说明.txt");
    expect(wrapper.text()).toContain("无可读取的文件");
    await wrapper.get('[aria-label="筛选服务器文件"]').setValue("说明");
    expect(wrapper.text()).not.toContain("没有匹配的文件");
    expect(wrapper.text()).not.toContain("无可读取的文件");
    wrapper.unmount();
  });

  it("首次打开和重开都恢复已保存缓存预算与角色", async () => {
    setup();
    const wrapper = mount(ServerSourcesPanel, { props: { open: true }, global: { plugins: [createPinia()] } });
    await flushPromises();
    expect((wrapper.get('details input[type="number"]').element as HTMLInputElement).value).toBe("256");
    expect((wrapper.findAll("details select")[1]!.element as HTMLSelectElement).value).toBe("issued_invoice_dir");
    await wrapper.get('details input[type="number"]').setValue("512");
    await wrapper.setProps({ open: false }); await wrapper.setProps({ open: true }); await flushPromises();
    expect((wrapper.get('details input[type="number"]').element as HTMLInputElement).value).toBe("256");
    wrapper.unmount();
  });
});
