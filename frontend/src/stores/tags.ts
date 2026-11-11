import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, request } from "../api/client";
import type { InvoiceTag, InvoiceTagDefinitions } from "../api/types";

// WS-06 tag definitions are app-level (beside the company registry). Saving replaces the whole
// list with the revision this page read; a conflict reloads instead of overwriting.
export const useTagsStore = defineStore("tags", () => {
  const definitions = ref<InvoiceTagDefinitions | null>(null);
  const error = ref("");
  const tags = computed<InvoiceTag[]>(() => definitions.value?.tags ?? []);
  const byId = computed(() => new Map(tags.value.map((tag) => [tag.id, tag])));

  async function load(): Promise<void> {
    try {
      definitions.value = await request<InvoiceTagDefinitions>("/api/v1/invoice-tags");
      error.value = "";
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    }
  }

  async function save(next: Omit<InvoiceTag, "id">[] | InvoiceTag[]): Promise<InvoiceTagDefinitions> {
    try {
      const saved = await request<InvoiceTagDefinitions>("/api/v1/invoice-tags", {
        method: "PUT",
        body: { revision: definitions.value?.revision ?? 0, tags: next },
      });
      definitions.value = saved;
      return saved;
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "INVOICE_TAGS_CONFLICT") await load();
      throw cause;
    }
  }

  return { definitions, error, tags, byId, load, save };
});
