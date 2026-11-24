export function skinBypassRequested(value: unknown): boolean {
  // Vue Router keeps repeated query values as an array; Starlette uses the last
  // value. Match it so recovery cannot disappear between the first paint and Vue.
  const effective = Array.isArray(value) ? value.at(-1) : value;
  return ["1", "true", "yes", "on"].includes(String(effective ?? "").trim().toLowerCase());
}

export function setSkinIdentity(id: string): void {
  const body = document.body;
  if (body.dataset.skinClass) body.classList.remove(body.dataset.skinClass);
  delete body.dataset.skinClass;
  delete body.dataset.activeSkin;
  delete document.documentElement.dataset.activeSkin;
  if (id) {
    document.documentElement.dataset.activeSkin = id;
    body.dataset.activeSkin = id;
    const className = `skin-${id.replace(/[^a-z0-9-]/g, "-")}`;
    body.classList.add(className);
    body.dataset.skinClass = className;
  }
}

export function workspaceSkinIsolated(id: string): boolean {
  return (document.documentElement.dataset.workspaceIsolatedSkins ?? "").split(" ").includes(id) && id !== "";
}

export function prepareSkinStylesheet(href: string, signal: AbortSignal): Promise<HTMLLinkElement> {
  return new Promise((resolve, reject) => {
    const url = new URL(href, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/v1/skins/")) {
      reject(new Error("外观资源地址无效，请刷新页面核对。"));
      return;
    }
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.media = "not all";
    link.dataset.workspaceAppearance = "pending";
    const finish = (error?: Error) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      link.onload = link.onerror = null;
      if (error) { link.remove(); reject(error); }
      else resolve(link);
    };
    const abort = () => finish(new Error("外观切换已取消。"));
    const timer = setTimeout(() => finish(new Error("外观资源加载超时，请重试。")), 8000);
    link.onload = () => finish();
    link.onerror = () => finish(new Error("外观资源加载失败，请重试。"));
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) { abort(); return; }
    link.href = url.href;
    document.head.appendChild(link);
  });
}
