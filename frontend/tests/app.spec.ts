import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import App from "../src/App.vue";
import { createAppRouter } from "../src/router";
import { useSystemStore } from "../src/stores/system";

const HEALTH = { ok: true, product_version: "0.3.0-alpha.2", platform: "macos", background_status: "ready", watch_dir: "/tmp/合成目录", target_id: "t1" };
const SETTINGS = { ok: true, watch_dir: "/tmp/合成目录", active_target_id: "t1" };

function stubBackend(fail = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (fail) return new Response(JSON.stringify({ detail: "服务暂不可用" }), { status: 503 });
      const body = path.endsWith("/health") ? HEALTH : SETTINGS;
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
}

async function mountApp() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createAppRouter(createMemoryHistory());
  await router.push("/");
  const wrapper = mount(App, { global: { plugins: [pinia, router] }, attachTo: document.body });
  await flushPromises();
  return { wrapper, router };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("workspace shell", () => {
  it("renders the backend health snapshot", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    expect(wrapper.text()).toContain("0.3.0-alpha.2");
    expect(wrapper.text()).toContain("/tmp/合成目录");
  });

  it("keeps module views alive across navigation", async () => {
    stubBackend();
    const { wrapper, router } = await mountApp();
    const overviewUid = wrapper.findComponent({ name: "OverviewView" }).vm.$.uid;
    await router.push("/directory");
    await flushPromises();
    expect(wrapper.text()).toContain("活动目录");
    await router.push("/");
    await flushPromises();
    // The same component instance comes back instead of a fresh mount.
    expect(wrapper.findComponent({ name: "OverviewView" }).vm.$.uid).toBe(overviewUid);
  });

  it("keeps the last good snapshot when a refresh fails", async () => {
    stubBackend();
    const { wrapper } = await mountApp();
    stubBackend(true);
    await useSystemStore().refresh();
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("服务暂不可用");
    expect(wrapper.text()).toContain("0.3.0-alpha.2");
  });
});
