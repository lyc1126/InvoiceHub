<script setup lang="ts">
import { ref } from "vue";
import { request } from "../api/client";
import type { InvoiceRow } from "../api/types";
import { errorText } from "../format";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

// Manual invoice field editor for the active monitored directory (WS-12).
// Writes protected overrides via PATCH /api/v1/invoices/{invoice_key}/manual-fields so
// subsequent incremental rebuilds keep the user's edited values.
const props = defineProps<{ row: InvoiceRow; companyId: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();

const seller = ref(props.row.seller || "");
const buyer = ref(props.row.buyer || "");
const amount = ref(props.row.amount || "");
const invoiceNumber = ref(props.row.invoice_number || "");
const invoiceDate = ref(props.row.invoice_date || "");
const taxRate = ref(props.row.tax_rate || "");
const saving = ref(false);
const error = ref("");

async function submit(): Promise<void> {
  if (saving.value) return;
  saving.value = true;
  error.value = "";
  const fields: Record<string, string> = {};
  if (seller.value.trim() !== (props.row.seller || "").trim()) fields["销售方"] = seller.value.trim();
  if (buyer.value.trim() !== (props.row.buyer || "").trim()) fields["购买方"] = buyer.value.trim();
  if (amount.value.trim() !== (props.row.amount || "").trim()) fields["开票金额"] = amount.value.trim();
  if (invoiceNumber.value.trim() !== (props.row.invoice_number || "").trim()) fields["发票号码"] = invoiceNumber.value.trim();
  if (invoiceDate.value.trim() !== (props.row.invoice_date || "").trim()) fields["开票时间"] = invoiceDate.value.trim();
  if (taxRate.value.trim() !== (props.row.tax_rate || "").trim()) fields["税率"] = taxRate.value.trim();

  if (!Object.keys(fields).length) {
    emit("close");
    return;
  }
  try {
    await request(`/api/v1/invoices/${encodeURIComponent(props.row.invoice_key)}/manual-fields`, {
      method: "PATCH",
      body: { fields },
    });
    toast(`已保存手改字段（${Object.keys(fields).join("、")}），后续重新汇总会自动保留。`, "info", 4000);
    window.dispatchEvent(new CustomEvent("workspace:company-refreshed", { detail: { companyId: props.companyId } }));
    emit("saved");
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <WsModal
    title="编辑手改字段"
    :subtitle="`源文件：${row.source_file}（仅修改汇总与受保护手改记录，不改动源发票文件）`"
    @close="$emit('close')"
  >
    <form class="manual-edit-form" @submit.prevent="submit">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
      <div class="manual-edit-grid">
        <label>
          <span>销售方</span>
          <input v-model="seller" type="text" maxlength="160" aria-label="手改销售方">
        </label>
        <label>
          <span>购买方</span>
          <input v-model="buyer" type="text" maxlength="160" aria-label="手改购买方">
        </label>
        <label>
          <span>开票金额</span>
          <input v-model="amount" type="text" inputmode="decimal" maxlength="32" aria-label="手改开票金额" placeholder="如 1234.56">
        </label>
        <label>
          <span>发票号码</span>
          <input v-model="invoiceNumber" type="text" maxlength="64" aria-label="手改发票号码">
        </label>
        <label>
          <span>开票时间</span>
          <input v-model="invoiceDate" type="text" maxlength="32" aria-label="手改开票时间" placeholder="YYYY-MM-DD">
        </label>
        <label>
          <span>税率</span>
          <input v-model="taxRate" type="text" maxlength="24" aria-label="手改税率" placeholder="如 13% 或 免税">
        </label>
      </div>
      <div class="actions">
        <button type="submit" class="primary" :disabled="saving" :aria-busy="saving">
          {{ saving ? "保存中…" : "保存手改字段" }}
        </button>
        <button type="button" :disabled="saving" @click="$emit('close')">取消</button>
      </div>
    </form>
  </WsModal>
</template>

<style scoped>
.manual-edit-form { display: grid; gap: 12px; }
.manual-edit-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px 14px; }
.manual-edit-grid label { display: grid; gap: 4px; font-size: 13px; }
</style>
