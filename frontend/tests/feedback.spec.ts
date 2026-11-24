import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FeedbackDialog from "../src/components/FeedbackDialog.vue";
import { ApiError, request } from "../src/api/client";

vi.mock("../src/api/client", async (original) => ({ ...await original<typeof import("../src/api/client")>(), request: vi.fn() }));
const api = vi.mocked(request);
const configuration = { enabled: true, message: "", environment: { version: "0.3.0-alpha.2", platform: "macos", architecture: "arm64", package_type: "source" }, pending: null };
let wrapper: VueWrapper | undefined;
beforeEach(() => { api.mockReset(); api.mockResolvedValue(configuration); });
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = ""; vi.restoreAllMocks(); });
async function setup() {
  wrapper = mount(FeedbackDialog, { props: { open: true }, attachTo: document.body, global: { stubs: { Teleport: true } } });
  await flushPromises();
  return wrapper;
}
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')!;
const button = (label: string) => [...dialog().querySelectorAll("button")].find((item) => item.textContent === label)!;
async function fill(view: VueWrapper) {
  await view.get('input[maxlength="120"]').setValue("合成建议");
  await view.get("textarea").setValue("合成描述");
  await view.findAll('input[type="checkbox"]')[1]!.setValue(true);
}

describe("opt-in public feedback", () => {
  it("requires title, description and public consent, and excludes environment by default", async () => {
    const view = await setup();
    expect(button("确认公开并提交").disabled).toBe(true);
    await fill(view);
    expect(view.findAll('input[type="checkbox"]')[0]!.element).toHaveProperty("checked", false);
    api.mockResolvedValueOnce({ request_id: "job", state: "submitted", issue_number: 5, message: "已提交" });
    await view.get("form").trigger("submit"); await flushPromises();
    expect(api).toHaveBeenCalledWith("/api/v1/feedback", expect.objectContaining({ method: "POST", body: expect.objectContaining({ title: "合成建议", description: "合成描述", public_consent: true, include_environment: false }) }));
    expect(dialog().querySelector("a")?.getAttribute("href")).toBe("https://github.com/lyc1126/InvoiceHub/issues/5");
  });

  it("keeps an unknown write locked and only queries its existing receipt", async () => {
    const view = await setup(); await fill(view);
    api.mockRejectedValueOnce(new ApiError("timeout", 0));
    await view.get("form").trigger("submit"); await flushPromises();
    const post = api.mock.calls.find(([, options]) => options?.method === "POST")!;
    const requestId = (post[1]!.body as { request_id: string }).request_id;
    expect(button("确认公开并提交").disabled).toBe(true);
    api.mockResolvedValueOnce({ request_id: requestId, state: "submitted", issue_number: 8, message: "已提交" });
    button("查询提交结果").click(); await flushPromises();
    expect(api).toHaveBeenLastCalledWith(`/api/v1/feedback/${requestId}`, expect.objectContaining({ timeoutMs: 20_000 }));
    expect(api.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  });

  it("restores unresolved receipt after reopening and preserves an unsent draft", async () => {
    const view = await setup(); await fill(view);
    await view.setProps({ open: false });
    api.mockResolvedValueOnce({ ...configuration, pending: { request_id: "old-job", state: "unknown", message: "结果未知", issue_number: null } });
    await view.setProps({ open: true }); await flushPromises();
    expect(view.get("textarea").element).toHaveProperty("value", "合成描述");
    expect(button("确认公开并提交").disabled).toBe(true);
    expect(dialog().textContent).toContain("old-job");
  });

  it("shows missing configuration with GitHub Issue fallback and safely renders arbitrary markup as text", async () => {
    api.mockResolvedValueOnce({ ...configuration, enabled: false, message: "当前版本未部署在线直连反馈中转，可一键复制脱敏内容后前往 GitHub Issue 提交。" });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const view = await setup(); await fill(view);
    await view.get("textarea").setValue('<img src=x onerror="alert(1)">');
    expect(button("确认公开并提交").disabled).toBe(true);
    expect(dialog().textContent).toContain("GitHub Issue");
    expect(dialog().querySelector("img")).toBeNull();
    const issueLink = dialog().querySelector<HTMLAnchorElement>('a[href="https://github.com/lyc1126/InvoiceHub/issues/new"]');
    expect(issueLink).not.toBeNull();
    button("复制脱敏信息并打开 GitHub Issue").click(); await flushPromises();
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("系统架构：arm64"));
    expect(openSpy).toHaveBeenCalledWith("https://github.com/lyc1126/InvoiceHub/issues/new", "_blank", "noopener,noreferrer");
    await view.findAll('input[type="checkbox"]')[0]!.setValue(true);
    expect(dialog().textContent).toContain("系统架构");
    expect(dialog().querySelector("pre")?.textContent).toContain("arm64");
  });

  it("keeps drafts editable after a definitive rejection", async () => {
    const view = await setup(); await fill(view);
    api.mockResolvedValueOnce({ request_id: "rejected", state: "rejected", issue_number: null, message: "未被接收" });
    await view.get("form").trigger("submit"); await flushPromises();
    expect(view.get("fieldset").attributes("disabled")).toBeUndefined();
    expect(button("确认公开并提交").disabled).toBe(false);
  });
});
