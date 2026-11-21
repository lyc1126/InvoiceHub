<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

interface Result { request_id: string; state: "submitted" | "unknown" | "rejected"; issue_number: number | null; issue_url: string; message: string }
interface Configuration { enabled: boolean; message: string; environment: Record<string, string>; pending: Result | null }
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();
const config = ref<Configuration>();
const kind = ref("feature"), title = ref(""), description = ref("");
const includeEnvironment = ref(false), consent = ref(false);
const loading = ref(false), busy = ref(false), error = ref("");
const result = ref<Result | null>(null);
let turn = 0;
const locked = computed(() => busy.value || result.value?.state === "unknown" || result.value?.state === "submitted");
const valid = computed(() => title.value.trim().length > 0 && title.value.trim().length <= 120 && description.value.trim().length > 0 && description.value.trim().length <= 6000 && consent.value);
const labels: Record<string, string> = { bug: "问题报告", feature: "功能建议", other: "其他反馈" };
const environmentLabels: Record<string, string> = { version: "软件版本", platform: "系统平台", architecture: "系统架构", package_type: "包类型" };
const preview = computed(() => `类型：${labels[kind.value]}\n标题：${title.value.trim()}\n\n${description.value.trim()}${includeEnvironment.value && config.value ? "\n\n环境信息：\n" + Object.entries(config.value.environment).map(([key, value]) => `${environmentLabels[key] || key}：${value}`).join("\n") : ""}`);
const issueUrl = computed(() => {
  const number = result.value?.issue_number;
  // Never navigate to a URL supplied by an upstream response or user description.
  return typeof number === "number" && Number.isSafeInteger(number) && number > 0 ? `https://github.com/lyc1126/InvoiceHub/issues/${number}` : "";
});

async function load(): Promise<void> {
  const current = ++turn;
  loading.value = true; error.value = "";
  try {
    const value = await request<Configuration>("/api/v1/feedback");
    if (current !== turn) return;
    config.value = value;
    if (value.pending) result.value = value.pending;
  } catch (cause) { if (current === turn) error.value = cause instanceof Error ? cause.message : "反馈服务读取失败"; }
  finally { if (current === turn) loading.value = false; }
}
watch(() => props.open, (open) => { if (open) void load(); else { ++turn; loading.value = false; } }, { immediate: true });
onBeforeUnmount(() => { ++turn; });

async function submit(): Promise<void> {
  if (locked.value || !valid.value || !config.value?.enabled) return;
  const requestId = crypto.randomUUID();
  busy.value = true; error.value = "";
  try {
    result.value = await request<Result>("/api/v1/feedback", { method: "POST", timeoutMs: 20_000,
      body: { request_id: requestId, kind: kind.value, title: title.value.trim(), description: description.value.trim(),
        include_environment: includeEnvironment.value, public_consent: consent.value } });
    if (result.value.state === "submitted") toast("反馈已提交，感谢你的建议。");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "提交失败";
    if (!(cause instanceof ApiError) || cause.status === 0 || cause.status >= 500) {
      // An interrupted POST may already have created the issue. Keep its ID and only GET the receipt.
      result.value = { request_id: requestId, state: "unknown", issue_number: null, issue_url: "", message: "提交结果尚未确认，请查询结果，不要重复提交。" };
    }
  } finally { busy.value = false; }
}
async function lookup(): Promise<void> {
  if (!result.value || busy.value) return;
  busy.value = true; error.value = "";
  try { result.value = await request<Result>(`/api/v1/feedback/${encodeURIComponent(result.value.request_id)}`, { timeoutMs: 20_000 }); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "查询失败，请稍后查询同一编号"; }
  finally { busy.value = false; }
}
async function copy(): Promise<void> {
  try { await navigator.clipboard.writeText(preview.value); toast("反馈内容已复制。"); }
  catch { error.value = "无法访问剪贴板，请选中下方预览内容手动复制。"; }
}
function another(): void {
  if (result.value?.state !== "submitted") return;
  result.value = null; title.value = ""; description.value = ""; consent.value = false; error.value = "";
}
</script>

<template>
  <WsModal :open="open" title="建议与反馈" subtitle="你的建议会帮助 InvoiceHub 变得更好。" :closable="!busy" @close="emit('close')">
    <div class="feedback-form">
      <p class="overview-notice">反馈将公开发布到 GitHub。请勿填写真实发票、公司税号、银行账号、联系方式或本机路径。本页不读取或上传发票、配置、日志和附件。</p>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }} <button v-if="!config && !busy" type="button" @click="load">重新读取</button></p>
      <p v-if="loading" class="muted" role="status">正在读取反馈服务…</p>
      <p v-if="config && !config.enabled" class="overview-notice overview-notice--warn" role="status">{{ config.message }}</p>
      <form @submit.prevent="submit">
        <fieldset :disabled="locked || loading">
          <label class="field">反馈类型<select v-model="kind"><option value="feature">功能建议</option><option value="bug">问题报告</option><option value="other">其他反馈</option></select></label>
          <label class="field">标题 <span class="muted">（必填，最多 120 字）</span><input v-model="title" maxlength="120" required placeholder="用一句话说明你的建议或遇到的问题"></label>
          <label class="field">详细描述 <span class="muted">（必填，最多 6000 字）</span><textarea v-model="description" rows="7" maxlength="6000" required placeholder="你希望解决什么问题？期望如何改进？如遇到故障，请说明操作步骤、实际结果和期望结果。"></textarea></label>
          <label class="checkline"><input v-model="includeEnvironment" type="checkbox">附带下方列出的软件版本与运行环境</label>
          <dl v-if="includeEnvironment && config" class="feedback-environment"><template v-for="(value, key) in config.environment" :key="key"><dt>{{ environmentLabels[key] || key }}</dt><dd>{{ value }}</dd></template></dl>
          <label class="checkline"><input v-model="consent" type="checkbox">我已检查内容，确认不含敏感信息，并同意公开到 GitHub。</label>
        </fieldset>
        <details class="feedback-preview"><summary>预览将发送的内容 / 手动复制</summary><pre>{{ preview }}</pre></details>
        <div v-if="result" class="overview-notice" role="status" aria-live="polite">
          <p>{{ result.message }}</p><p class="feedback-id">反馈编号：{{ result.request_id }}</p>
          <a v-if="issueUrl" :href="issueUrl" target="_blank" rel="noopener noreferrer">查看 GitHub Issue #{{ result.issue_number }}（需能访问 GitHub）</a>
          <button v-if="result.state === 'unknown'" type="button" :disabled="busy" :aria-busy="busy" @click="lookup">{{ busy ? '查询中…' : '查询提交结果' }}</button>
        </div>
        <div class="actions feedback-actions">
          <button type="button" :disabled="busy" @click="copy">复制反馈</button>
          <button v-if="result?.state === 'submitted'" type="button" @click="another">继续反馈</button>
          <button v-else class="primary" type="submit" :disabled="locked || loading || !valid || !config?.enabled" :aria-busy="busy">{{ busy ? '处理中…' : '确认公开并提交' }}</button>
        </div>
      </form>
    </div>
  </WsModal>
</template>

<style scoped>
.feedback-form, .feedback-form form, .feedback-form fieldset { display: grid; gap: 16px; }
.feedback-form fieldset { padding: 0; border: 0; margin: 0; min-width: 0; }
.feedback-form .field { display: grid; gap: 6px; }
.feedback-form textarea { width: 100%; resize: vertical; min-height: 130px; }
.feedback-environment { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; margin: 0; padding: 12px; background: var(--surface-2); }
.feedback-environment dt { color: var(--muted); }
.feedback-environment dd { margin: 0; overflow-wrap: anywhere; }
.feedback-preview pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; padding: 12px; background: var(--surface-2); font: inherit; }
.feedback-preview summary { cursor: pointer; color: var(--muted); }
.feedback-id { font-size: 12px; overflow-wrap: anywhere; }
.feedback-actions { justify-content: flex-end; flex-wrap: wrap; }
</style>
