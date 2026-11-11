<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ApiError } from "../api/client";
import { errorText } from "../format";
import { useTagsStore } from "../stores/tags";

const emit = defineEmits<{ close: [] }>();
const store = useTagsStore();
interface Draft { id: string; name: string; color: string; meaning: string }
const drafts = ref<Draft[]>([]);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const PALETTE = ["#e5484d", "#f76b15", "#ffc53d", "#30a46c", "#0090ff", "#8e4ec6", "#8b8d98"];

function reset(): void {
  drafts.value = store.tags.map((tag) => ({ ...tag }));
}

function add(): void {
  drafts.value.push({ id: "", name: "", color: PALETTE[drafts.value.length % PALETTE.length]!, meaning: "" });
}

async function save(): Promise<void> {
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    const saved = await store.save(drafts.value.map(({ id, ...rest }) => (id ? { id, ...rest } : rest)) as Draft[]);
    reset();
    notice.value = saved.purge_failed?.length
      ? `已保存。以下公司资料夹暂时不可用，删除的标签会在那里自动隐藏：${saved.purge_failed.join("、")}`
      : "已保存。";
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.code === "INVOICE_TAGS_CONFLICT" ? "标签已在别处修改，已刷新，请重新编辑。" : errorText(cause);
    if (cause instanceof ApiError && cause.code === "INVOICE_TAGS_CONFLICT") reset();
  } finally {
    saving.value = false;
  }
}

watch(() => store.definitions, reset);
onMounted(async () => {
  if (!store.definitions) await store.load();
  reset();
});
</script>

<template>
  <form class="panel" aria-label="发票标签" @submit.prevent="save">
    <h3>发票标签</h3>
    <p class="muted">标签只是个人标记：不改变金额、状态或勾选合计。删除标签会同时移除已打的标记。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <table class="grid">
      <thead><tr><th>颜色</th><th>名称</th><th>意义（悬停时显示）</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(tag, index) in drafts" :key="tag.id || `new-${index}`">
          <td><input v-model="tag.color" type="color" :aria-label="`标签 ${index + 1} 颜色`"></td>
          <td><input v-model="tag.name" maxlength="12" required :aria-label="`标签 ${index + 1} 名称`"></td>
          <td><input v-model="tag.meaning" maxlength="120" :aria-label="`标签 ${index + 1} 意义`"></td>
          <td><button type="button" @click="drafts.splice(index, 1)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <div class="actions">
      <button type="button" :disabled="drafts.length >= 30" @click="add">添加标签</button>
      <button type="submit" class="primary" :disabled="saving" :aria-busy="saving">{{ saving ? "保存中…" : "保存" }}</button>
      <button type="button" @click="emit('close')">关闭</button>
    </div>
  </form>
</template>
