import { defineStore } from "pinia";
import { ref } from "vue";
import { request } from "../api/client";
import type { HealthPayload, SettingsPayload } from "../api/types";

// Read-only system snapshot shared by every module view. A refresh keeps the last
// good snapshot visible and only replaces it on success, so a transient failure
// shows an error banner instead of blanking the page.
export const useSystemStore = defineStore("system", () => {
  const health = ref<HealthPayload | null>(null);
  const settings = ref<SettingsPayload | null>(null);
  const loading = ref(false);
  const error = ref("");
  let generation = 0;

  async function refresh(): Promise<void> {
    const turn = ++generation;
    loading.value = true;
    error.value = "";
    try {
      const [nextHealth, nextSettings] = await Promise.all([
        request<HealthPayload>("/api/v1/health"),
        request<SettingsPayload>("/api/v1/settings"),
      ]);
      if (turn !== generation) return;
      health.value = nextHealth;
      settings.value = nextSettings;
    } catch (cause) {
      if (turn === generation) error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      if (turn === generation) loading.value = false;
    }
  }

  return { health, settings, loading, error, refresh };
});
