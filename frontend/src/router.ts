import { createRouter, createWebHistory, type RouteLocation, type RouterHistory } from "vue-router";
import HomeView from "./views/HomeView.vue";
import TemporaryRecognitionView from "./views/TemporaryRecognitionView.vue";
import ClassicModuleView from "./components/ClassicModuleView.vue";
import { MODULES } from "./modules";

// Served by FastAPI at /workspace/*; deep links fall back to the same index.html.
export const WORKSPACE_BASE = "/workspace/";
// Recovery must survive legacy and unknown deep links; dropping its query would
// let a broken saved skin load again on the next classic-page navigation.
const home = (to: RouteLocation) => ({ path: "/", query: to.query });

export const routes = [
  { path: "/", name: "home", component: HomeView, meta: { title: "首页" } },
  { path: "/temporary", name: "temporary", component: TemporaryRecognitionView, meta: { title: "临时识别" } },
  ...MODULES.map((item) => ({ path: item.path, name: item.id, component: ClassicModuleView, meta: { title: item.label } })),
  // Earlier module paths now live in the home sidebar and tabs.
  { path: "/companies", redirect: home },
  { path: "/directory", redirect: home },
  { path: "/:rest(.*)*", redirect: home },
];

export function createAppRouter(history: RouterHistory = createWebHistory(WORKSPACE_BASE)) {
  return createRouter({ history, routes });
}
