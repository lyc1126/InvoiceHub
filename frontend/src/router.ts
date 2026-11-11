import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import HomeView from "./views/HomeView.vue";

// Served by FastAPI at /workspace/*; deep links fall back to the same index.html.
export const WORKSPACE_BASE = "/workspace/";

export const routes = [
  { path: "/", name: "home", component: HomeView, meta: { title: "首页" } },
  // Earlier module paths now live in the home sidebar and tabs.
  { path: "/companies", redirect: "/" },
  { path: "/directory", redirect: "/" },
  { path: "/:rest(.*)*", redirect: "/" },
];

export function createAppRouter(history: RouterHistory = createWebHistory(WORKSPACE_BASE)) {
  return createRouter({ history, routes });
}
