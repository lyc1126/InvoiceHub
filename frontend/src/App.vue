<script setup lang="ts">
import { onMounted } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { useCompaniesStore } from "./stores/companies";
import { useSystemStore } from "./stores/system";
import { useWorkspaceStore } from "./stores/workspace";

// Module rail (WS-01). 首页 is the Vue workspace; modules not migrated yet open their classic
// page, which keeps its own state (WEB_UI: one implementation per business rule).
const CLASSIC_MODULES = [
  { href: "/costs", label: "成本分析", icon: "↗" },
  { href: "/documents", label: "单据", icon: "▤" },
  { href: "/bookkeeping", label: "做账", icon: "▥" },
  { href: "/ocr", label: "OCR", icon: "⌗" },
  { href: "/consistency", label: "一致性", icon: "✓" },
  { href: "/settings", label: "设置", icon: "⚙" },
];

const system = useSystemStore();
const companies = useCompaniesStore();
const workspace = useWorkspaceStore();
const route = useRoute();
onMounted(() => system.refresh());

// Double click on "hi." refreshes this page only: the active home tab is rebuilt (its scroll,
// filters, selections and comparison focus are dropped) and data is read again. Other tabs and
// anything already saved are untouched.
function refreshPage(): void {
  void system.refresh();
  if (route.name === "home") {
    workspace.refreshActive();
    void companies.load();
  }
}
</script>

<template>
  <div class="shell">
    <nav class="rail" aria-label="模块">
      <span class="brand" title="双击：只刷新本页" @dblclick="refreshPage">hi.</span>
      <RouterLink to="/" class="rail-link"><span class="rail-icon" aria-hidden="true">⌂</span>首页</RouterLink>
      <a v-for="item in CLASSIC_MODULES" :key="item.href" class="rail-link rail-link--classic-module" :href="item.href" :title="`${item.label}（经典界面）`">
        <span class="rail-icon" aria-hidden="true">{{ item.icon }}</span>{{ item.label }}
      </a>
      <a class="rail-link rail-link--update" href="/settings" title="设置 › 关于与更新"><span class="rail-icon" aria-hidden="true">↑</span>更新</a>
      <a class="rail-link rail-link--classic" href="/" title="返回经典界面">经典界面</a>
    </nav>
    <main class="content" :class="{ 'content--home': route.name === 'home' }">
      <p v-if="system.error" class="banner banner--error" role="alert">{{ system.error }}</p>
      <!-- KeepAlive keeps each module's object, filters and scroll state when switching
           modules, which the workspace redesign requires instead of re-rendering pages. -->
      <RouterView v-slot="{ Component }">
        <KeepAlive>
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>
