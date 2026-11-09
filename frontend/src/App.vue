<script setup lang="ts">
import { onMounted } from "vue";
import { RouterLink, RouterView } from "vue-router";
import { routes } from "./router";
import { useSystemStore } from "./stores/system";

const system = useSystemStore();
onMounted(() => system.refresh());
</script>

<template>
  <div class="shell">
    <nav class="rail" aria-label="模块">
      <span class="brand">hi.</span>
      <RouterLink v-for="route in routes" :key="route.name" :to="route.path" class="rail-link">
        {{ route.meta.title }}
      </RouterLink>
      <a class="rail-link rail-link--classic" href="/">返回经典界面</a>
    </nav>
    <main class="content">
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
