<script setup lang="ts">
import { computed } from "vue";
import { useSystemStore } from "../stores/system";

const system = useSystemStore();
const rows = computed(() => {
  const health = system.health;
  if (!health) return [];
  return [
    ["版本", health.product_version],
    ["平台", health.platform],
    ["后台状态", health.background_status],
    ["当前目录", health.watch_dir],
  ];
});
</script>

<template>
  <section>
    <header class="page-header">
      <h1>概览</h1>
      <button type="button" :disabled="system.loading" :aria-busy="system.loading" @click="system.refresh()">
        {{ system.loading ? "刷新中…" : "刷新" }}
      </button>
    </header>
    <p v-if="!system.health && !system.loading" class="muted">尚未取得本机服务状态。</p>
    <table v-else class="facts">
      <tbody>
        <tr v-for="[label, value] in rows" :key="label">
          <th scope="row">{{ label }}</th>
          <td>{{ value || "—" }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
