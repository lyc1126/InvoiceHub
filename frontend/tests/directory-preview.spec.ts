import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import DirectoryInvoices from "../src/components/DirectoryInvoices.vue";
import SourcePreview from "../src/components/SourcePreview.vue";
import type { Company } from "../src/api/types";

const company = { id: "co_1", monitored: true, monitored_subdir_key: "cost_invoice_dir" } as Company;
const rows = ["PDF", "XML"].map((format, index) => ({
  invoice_key: String(index), source_path: `/合成/甲/${index}.${format.toLowerCase()}`, source_file: `${index}.${format.toLowerCase()}`,
  file_format: format, invoice_type: index ? "增值税普通发票" : "增值税专用发票", business_type: "建筑服务",
  invoice_number: "1".repeat(20), invoice_date: index ? "2026-07-01" : "2026-06-01", seller: "乙", buyer: "甲", amount: "113.00", tags: [],
}));
const identity = { target_id: "t1", items: rows.map(({ invoice_key, source_path }) => ({ invoice_key, source_path })) };
const payload = (order = rows) => ({ ok: true, count: order.length, page: 1, read_only: false,
  directory: { label: "成本发票", target_id: "t1", projection: { summary_exists: true } }, items: order, snapshot: { provisional: false, revision: "r1" } });
const pageFile = (number: number) => ({ file_number: number, name: `${number}.pdf`, preview_type: "pages", page_count: 2,
  reason: "", page_url_template: `/preview/${number}/{page_number}`, text_url: "" });
const textFile = (number: number) => ({ ...pageFile(number), name: `${number}.xml`, preview_type: "text", page_count: 0, text_url: `/text/${number}` });
const job = (files: ReturnType<typeof pageFile>[]) => ({ job_id: "j1", files, idle_timeout_seconds: 900, keep_alive_url: "/keep-alive" });
const response = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.body.innerHTML = "";
});

describe("directory invoice list and shared source preview", () => {
  it("sorts through the backend, preserves selection, and previews every selected format", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.includes("/invoices?")) return response(payload(url.includes("date_sort=desc") ? [...rows].reverse() : rows));
      if (url.endsWith("/preview-jobs")) return response(job([pageFile(1), textFile(2)]));
      if (url === "/api/v1/invoice-tags") return response({ revision: 0, tags: [] });
      return response({});
    }));
    const wrapper = mount(DirectoryInvoices, { props: { company, dirKey: "cost_invoice_dir" }, global: { plugins: [createPinia()] } });
    await flushPromises();
    expect(wrapper.get(".invoice-type--special").text()).toBe("增值税专用发票");
    expect(wrapper.get(".invoice-type--ordinary").text()).toBe("增值税普通发票");
    expect(wrapper.find(".format-badge--pdf").exists()).toBe(true);
    expect(wrapper.find(".format-badge--xml").exists()).toBe(true);
    expect(wrapper.text()).toContain("业务：建筑服务");
    await wrapper.get('[aria-label="勾选本页"]').setValue(true);
    await wrapper.get('[aria-label="按开票时间正序排序"]').trigger("click");
    await flushPromises();
    expect(calls.some(({ url }) => url.endsWith("date_sort=asc"))).toBe(true);
    expect(wrapper.get('th[aria-sort="ascending"]').text()).toContain("开票时间");
    await wrapper.get('[aria-label="按开票时间倒序排序"]').trigger("click");
    await flushPromises();
    expect(wrapper.findAll("tbody tr")[0]!.text()).toContain("2026-07-01");
    expect((wrapper.get('[aria-label="勾选本页"]').element as HTMLInputElement).checked).toBe(true);
    await wrapper.get('[aria-label="已勾选发票"]').findAll("button").find((button) => button.text() === "预览")!.trigger("click");
    await flushPromises();
    expect(calls.find(({ url }) => url.endsWith("/preview-jobs"))!.body).toEqual(identity);
    expect(wrapper.get('[role="dialog"]').text()).toContain("2 个源文件");
    await wrapper.get('[aria-label="关闭原票"]').trigger("click");
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the complete queue beyond 100 names and renders XML as text", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const files = Array.from({ length: 101 }, (_, index) => index === 100 ? textFile(101) : pageFile(index + 1));
    const fetcher = vi.fn(async (url: string) => url === "/text/101"
      ? new Response('<script>alert("synthetic")</script>') : response(job(files)));
    vi.stubGlobal("fetch", fetcher);
    const wrapper = mount(SourcePreview, { props: { label: "已勾选发票", preview: identity } });
    await flushPromises();
    expect(wrapper.findAll('[aria-label="源文件列表"] button')).toHaveLength(100);
    await wrapper.get('[aria-label="源文件序号"]').setValue(101);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.findAll('[aria-label="源文件列表"] button')).toHaveLength(1);
    expect(wrapper.text()).toContain("第 101 / 101 个源文件");
    expect(wrapper.get("pre").text()).toContain('<script>alert("synthetic")</script>');
    expect(wrapper.find("script").exists()).toBe(false);
    // Focus can fall to body after the last-page button is disabled; Escape still closes.
    vi.spyOn(wrapper.element, "getClientRects").mockReturnValue({ length: 1 } as DOMRectList);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(wrapper.emitted("close")).toHaveLength(1);
    wrapper.unmount();
    const count = fetcher.mock.calls.length;
    vi.advanceTimersByTime(240_000);
    await flushPromises();
    expect(fetcher.mock.calls).toHaveLength(count); // unmount stops the job heartbeat
  });

  it("discards a slow previous XML body after selecting another file", async () => {
    let finishOld!: (text: string) => void;
    const oldBody = new Promise<string>((resolve) => { finishOld = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/text/1") return { ok: true, status: 200, text: () => oldBody };
      if (url === "/text/2") return new Response("new synthetic XML");
      return response(job([textFile(1), textFile(2)]));
    }));
    const wrapper = mount(SourcePreview, { props: { label: "原文", preview: identity } });
    await flushPromises();
    await wrapper.get('[aria-label="源文件列表"]').findAll("button")[1]!.trigger("click");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("new synthetic XML");
    finishOld("old synthetic XML");
    await flushPromises();
    expect(wrapper.get("pre").text()).toBe("new synthetic XML");
    wrapper.unmount();
  });

  it("bounds immediate XML recovery when even the rebuilt job has expired", async () => {
    let creates = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/text/1") return new Response("expired", { status: 410 });
      creates += 1;
      return response(job([textFile(1)]));
    }));
    const wrapper = mount(SourcePreview, { props: { label: "原文", preview: identity } });
    await flushPromises();
    expect(creates).toBe(2);
    expect(wrapper.get('[role="alert"]').text()).toContain("原文预览已失效");
    wrapper.unmount();
  });

  it("rejects late sorted responses and drops actions when this folder stops being monitored", async () => {
    let finishAsc!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishAsc = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("date_sort=asc")) return pending;
      if (url.includes("/invoices?")) return response(payload([...rows].reverse()));
      return response({ revision: 0, tags: [] });
    }));
    const wrapper = mount(DirectoryInvoices, { props: { company, dirKey: "cost_invoice_dir" }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="勾选本页"]').setValue(true);
    await wrapper.get('[aria-label="按开票时间正序排序"]').trigger("click");
    await wrapper.get('[aria-label="按开票时间倒序排序"]').trigger("click");
    await flushPromises();
    finishAsc(response(payload(rows)));
    await flushPromises();
    expect(wrapper.findAll("tbody tr")[0]!.text()).toContain("2026-07-01");
    // A monitor change refreshes this tab without treating a mere company-object refresh as a change.
    vi.stubGlobal("fetch", vi.fn(async () => response({ ...payload(), read_only: true })));
    await wrapper.setProps({ company: { ...company, monitored: false, monitored_subdir_key: null } });
    await flushPromises();
    expect(wrapper.find('[aria-label="已勾选发票"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="勾选本页"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="批量标签"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("tags a nonmonitored selection across pages without exposing source actions", async () => {
    const tag = { id: "tag_12345678", name: "待审", color: "#123456", meaning: "" };
    const saves: unknown[] = [];
    const other = { ...rows[1]!, invoice_key: "other", invoice_number: "2".repeat(20) };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url === "/api/v1/invoice-tags") return response({ revision: 1, tags: [tag] });
      if (url.endsWith("/invoice-tags")) {
        if (init.method === "PUT") saves.push(JSON.parse(String(init.body)));
        return response({ revision: 4, invoices: { [rows[0]!.invoice_number]: [tag.id] } });
      }
      const items = url.includes("page=2") ? [other] : rows;
      return response({ ...payload(items), read_only: true, count: 51, page: url.includes("page=2") ? 2 : 1 });
    }));
    const wrapper = mount(DirectoryInvoices, { props: { company: { ...company, monitored: false }, dirKey: "cost_invoice_dir" }, global: { plugins: [createPinia()] } });
    await flushPromises();
    await wrapper.get('[aria-label="勾选本页"]').setValue(true);
    await wrapper.findAll("button").find((b) => b.text() === "下一页")!.trigger("click");
    await flushPromises();
    await wrapper.get('[aria-label="勾选本页"]').setValue(true);
    expect(wrapper.get('[aria-label="批量标签"]').text()).toContain("已勾选 3 张");
    expect(wrapper.find('[aria-label="已勾选发票"]').exists()).toBe(false);
    const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 200, height: 180 } as DOMRect);
    await wrapper.get("tbody tr").trigger("contextmenu", { clientX: window.innerWidth, clientY: window.innerHeight });
    await flushPromises();
    expect((wrapper.get('[role="menu"]').element as HTMLElement).style.left).toBe(`${window.innerWidth - 208}px`);
    expect((wrapper.get('[role="menu"]').element as HTMLElement).style.top).toBe(`${window.innerHeight - 188}px`);
    rect.mockRestore();
    expect(wrapper.get('[role="menuitemcheckbox"]').attributes("aria-checked")).toBe("mixed");
    await wrapper.get('[role="menuitemcheckbox"] input').setValue(true);
    await flushPromises();
    expect(saves).toEqual([{ revision: 4, changes: { [other.invoice_number]: [tag.id] } }]);
    wrapper.unmount();
  });

  it("hides and restores columns per directory type, keeps at least one visible column, and persists via localStorage", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/invoices?")) return response(payload());
      if (url === "/api/v1/invoice-tags") return response({ revision: 0, tags: [] });
      return response({});
    }));
    const pinia = createPinia();
    const wrapper = mount(DirectoryInvoices, {
      attachTo: document.body,
      props: { company, dirKey: "cost_invoice_dir" },
      global: { plugins: [pinia] },
    });
    await flushPromises();

    // All columns visible initially; seller/buyer carry capped ellipsis spans with full title.
    expect(wrapper.findAll("thead th").map((th) => th.text())).toContain("销售方");
    expect(wrapper.findAll("thead th").map((th) => th.text())).toContain("购买方");
    expect(wrapper.find(".invoice-party__text").attributes("title")).toBe("乙");

    // Open column picker and hide 购买方 & 税率.
    await wrapper.get('.col-picker > button').trigger("click");
    const menu = wrapper.get('[aria-label="自定义发票列表显示列"]');
    const checkboxFor = (label: string) =>
      menu.findAll("label").find((el) => el.text().trim() === label)!.get("input");
    await checkboxFor("购买方").setValue(false);
    await checkboxFor("税率").setValue(false);
    await flushPromises();

    const headersAfterHide = wrapper.findAll("thead th").map((th) => th.text());
    expect(headersAfterHide).not.toContain("购买方");
    expect(headersAfterHide).not.toContain("税率");
    expect(headersAfterHide).toContain("销售方");
    expect(wrapper.get(".col-picker__badge").text()).toContain("已隐藏 2");

    // Try hiding every remaining column: the last remaining column checkbox becomes disabled.
    for (const label of ["格式", "发票号码", "项目", "发票分类与业务", "开票金额", "开票时间", "状态"]) {
      await checkboxFor(label).setValue(false);
    }
    await flushPromises();
    expect(wrapper.findAll("thead th").map((th) => th.text())).toContain("销售方");
    expect((checkboxFor("销售方").element as HTMLInputElement).disabled).toBe(true);

    // Escape closes the column menu.
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();
    expect(wrapper.find('[aria-label="自定义发票列表显示列"]').exists()).toBe(false);

    // Right-clicking the table header opens the same column menu.
    await wrapper.get("thead tr").trigger("contextmenu", { clientX: 120, clientY: 160 });
    await flushPromises();
    expect(wrapper.find('[aria-label="自定义发票列表显示列"]').exists()).toBe(true);

    // Restore all columns via the quick action button.
    await wrapper.findAll("button").find((btn) => btn.text() === "恢复全部列")!.trigger("click");
    await flushPromises();
    expect(wrapper.findAll("thead th").map((th) => th.text())).toContain("购买方");
    expect(wrapper.findAll("thead th").map((th) => th.text())).toContain("税率");
    expect(wrapper.find(".col-picker__badge").exists()).toBe(false);

    // Hide 购买方 in cost_invoice_dir and confirm it persists to localStorage without affecting issued_invoice_dir.
    await wrapper.get('[aria-label="自定义发票列表显示列"]').findAll("label").find((el) => el.text().trim() === "购买方")!.get("input").setValue(false);
    await flushPromises();
    const saved = JSON.parse(localStorage.getItem("invoicehub.workspace.v1") ?? "{}");
    expect(saved.hiddenInvoiceColumns).toEqual({ cost_invoice_dir: ["buyer"] });
    wrapper.unmount();

    const issuedWrapper = mount(DirectoryInvoices, {
      props: { company, dirKey: "issued_invoice_dir" },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(issuedWrapper.findAll("thead th").map((th) => th.text())).toContain("购买方");
    issuedWrapper.unmount();

    const reloadedCost = mount(DirectoryInvoices, {
      props: { company, dirKey: "cost_invoice_dir" },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(reloadedCost.findAll("thead th").map((th) => th.text())).not.toContain("购买方");
    reloadedCost.unmount();
  });

  it("centers directory invoice columns, caps party column width, and keeps tag dots crisp and compact in CSS", () => {
    const stylesCss = readFileSync(resolve(__dirname, "../src/styles.css"), "utf-8");
    const protoCss = readFileSync(resolve(__dirname, "../src/prototype.css"), "utf-8");
    expect(protoCss).toMatch(/\.directory-invoices-table\s+:is\(th,\s*td\)\s*\{[^}]*text-align:\s*center/);
    expect(protoCss).toMatch(/\.directory-invoices-table\s+\.num\s*\{[^}]*text-align:\s*center/);
    expect(protoCss).toMatch(/\.directory-invoices-table\s+\.tag-cell\s*\{[^}]*width:\s*1%/);
    expect(protoCss).toMatch(/\.directory-toolbar\s+button:first-of-type\s*\{\s*margin-left:\s*auto/);
    expect(stylesCss).toMatch(/\.tag-cell\s+\.tag-dot\s*\{[^}]*width:\s*14px[^}]*height:\s*14px/);
    expect(stylesCss).toMatch(/\.directory-invoices-table\s+\.invoice-party__text\s*\{[^}]*max-width:\s*196px/);
    expect(stylesCss).toMatch(/\.directory-invoices-table\s+\.invoice-party__text\s*\{[^}]*text-overflow:\s*ellipsis/);
  });
});
