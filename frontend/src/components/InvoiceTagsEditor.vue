<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ApiError } from "../api/client";
import { errorText } from "../format";
import { useTagsStore } from "../stores/tags";
import WorkspaceIcon from "./WorkspaceIcon.vue";

const store = useTagsStore();
interface Draft { id: string; name: string; color: string; meaning: string }
const drafts = ref<Draft[]>([]);
const saving = ref(false);
const error = ref("");
const notice = ref("");
// Named prototype colours. A tag saved earlier with another colour keeps it as "自定义".
const PALETTE: [string, string][] = [["#ef4444", "红色"], ["#f97316", "橙色"], ["#eab308", "黄色"], ["#22c55e", "绿色"], ["#3b82f6", "蓝色"], ["#a855f7", "紫色"], ["#6b7280", "灰色"]];
const named = (color: string) => PALETTE.some(([value]) => value === color.toLowerCase());

function reset(): void {
  drafts.value = store.tags.map((tag) => ({ ...tag }));
}

function add(): void {
  const used = new Set(drafts.value.map(tag => tag.color.toLowerCase()));
  drafts.value.push({ id: "", name: "", color: (PALETTE.find(([value]) => !used.has(value)) ?? PALETTE[0]!)[0], meaning: "" });
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

watch(() => store.definitions, (next, previous) => {
  // Menu refreshes must preserve unsaved editor rows. Only unchanged drafts follow them.
  if (!previous || JSON.stringify(drafts.value) === JSON.stringify(previous.tags)) reset();
});
onMounted(async () => {
  await store.load(true);
  reset();
});
</script>

<template>
  <form class="panel invoice-tags" aria-label="发票标签" @submit.prevent="save">
    <div class="overview-section__head">
      <div><h3>标签</h3><p>在发票列表里右键一行即可打标签；鼠标停在标签圆点上，会显示这里写的意义。标签只是你的备注，不改变金额、状态或任何汇总；删除标签会同时移除已打的标记。</p></div>
      <div class="actions">
        <button type="button" @click="store.load(true)">更新使用计数</button>
        <button type="button" :disabled="drafts.length >= 30" @click="add"><WorkspaceIcon name="plus" />新增标签</button>
        <button type="submit" class="primary" :disabled="saving" :aria-busy="saving">{{ saving ? "保存中…" : "保存" }}</button>
      </div>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <p v-if="store.definitions?.usage_unavailable?.length" class="banner banner--note" role="status">计数未完整：{{ store.definitions.usage_unavailable.map(c => c.name).join("、") }} 资料夹不可用；下列仅为已知数量。</p>
    <div class="overview-table-wrap"><table class="grid tag-table">
      <thead><tr><th style="width:150px">颜色</th><th style="width:200px">名称</th><th>意义（自己填写，悬停时显示）</th><th class="num" style="width:90px">使用中</th><th style="width:70px"></th></tr></thead>
      <tbody>
        <tr v-for="(tag, index) in drafts" :key="tag.id || `new-${index}`">
          <td><span class="swatch" :style="{ background: tag.color }" /><select v-model="tag.color" :aria-label="`标签 ${index + 1} 颜色`">
            <option v-if="!named(tag.color)" :value="tag.color">自定义</option>
            <option v-for="[value, name] in PALETTE" :key="value" :value="value">{{ name }}</option>
          </select></td>
          <td><input v-model="tag.name" maxlength="12" required :aria-label="`标签 ${index + 1} 名称`"></td>
          <td><input v-model="tag.meaning" maxlength="120" placeholder="例如：金额有疑问，待找供应商核实" :aria-label="`标签 ${index + 1} 意义`"></td>
          <td class="num">{{ !tag.id ? "—" : store.definitions?.usage?.[tag.id] === undefined ? "待核对" : `${store.definitions.usage_complete === false ? "已知 " : ""}${store.definitions.usage[tag.id]} 张` }}</td>
          <td><button type="button" class="ghost" @click="drafts.splice(index, 1)">删除</button></td>
        </tr>
        <tr v-if="!drafts.length"><td colspan="5" class="overview-empty">还没有标签，点“新增标签”添加。</td></tr>
      </tbody>
    </table></div>
  </form>
</template>
