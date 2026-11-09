import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import OverviewView from "./views/OverviewView.vue";
import DirectoryView from "./views/DirectoryView.vue";

// Served by FastAPI at /workspace/*; deep links fall back to the same index.html.
export const WORKSPACE_BASE = "/workspace/";

export const routes = [
  { path: "/", name: "overview", component: OverviewView, meta: { title: "概览" } },
  { path: "/directory", name: "directory", component: DirectoryView, meta: { title: "目录" } },
];

export function createAppRouter(history: RouterHistory = createWebHistory(WORKSPACE_BASE)) {
  return createRouter({ history, routes });
}
