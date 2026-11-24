<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText } from "../format";

// Period folders (WS-05 stage 2) of the 进项抵扣 / 银行流水 subfolder. The backend reads each file's
// period from its content and compares it with the folder name, which is only a hint. Moving a
// misfiled file is a plan the user confirms; a lost confirm response only reads the journal.
interface CheckItem {
  file: string; name: string; folder: string; folder_period: string; content_period: string;
  status: "ok" | "mismatch" | "outside" | "unknown"; target: string; target_exists: boolean;
}
interface CheckPayload { folders: { name: string; period: string }[]; items: CheckItem[]; mismatched: number }
interface MoveFile { file: string; target: string; new_folder: boolean; status: string; message: string }
interface MoveJob { job_id: string; state: string; moved_count: number; files: MoveFile[] }

const props = defineProps<{ company: Company; dirKey: string }>();
const STATUS: Record<CheckItem["status"], string> = { ok: "所在文件夹相符", mismatch: "可能放错", outside: "未放在属期文件夹", unknown: "内容里没有单一属期" };
const FILE_STATUS: Record<string, string> = { pending: "未移动", moving: "结果待核对", moved: "已移动", failed: "未完成", unknown: "结果待核对" };
const base = computed(() => `/api/v1/companies/${encodeURIComponent(props.company.id)}/period-folders`);
const check = ref<CheckPayload | null>(null);
const error = ref("");
const loading = ref(false);
const busy = ref(false);
const chosen = reactive<Record<string, string>>({});
const plan = ref<MoveJob | null>(null);
const result = ref<MoveJob | null>(null);
const showAll = ref(false);

const shown = computed(() => (check.value?.items ?? []).filter((item) => showAll.value || item.status === "mismatch" || item.status === "outside"));
const targetsFor = (item: CheckItem) => {
  const names = (check.value?.folders ?? []).map((folder) => folder.name).filter((name) => name !== item.folder);
  return item.content_period && !names.includes(item.content_period) && !item.target_exists ? [...names, item.content_period] : names;
};
const selected = computed(() => Object.entries(chosen).filter(([, target]) => target).map(([file, target]) => ({ file, target })));

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    check.value = await request<CheckPayload>(`${base.value}?key=${encodeURIComponent(props.dirKey)}`, { timeoutMs: 120_000 });
    for (const key of Object.keys(chosen)) delete chosen[key];
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    loading.value = false;
  }
}

async function prepare(): Promise<void> {
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    plan.value = await request<MoveJob>(`${base.value}/moves`, { method: "POST", body: { key: props.dirKey, items: selected.value } });
  } catch (cause) {
    error.value = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function confirmMove(): Promise<void> {
  if (!plan.value) return;
  busy.value = true;
  error.value = "";
  const url = `${base.value}/moves/${plan.value.job_id}`;
  try {
    result.value = await request<MoveJob>(`${url}/confirm`, { method: "POST", body: { confirmed: true } });
  } catch (cause) {
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      error.value = errorText(cause);
    } else {
      // The response was lost: read what the journal recorded, never confirm a second time.
      try {
        result.value = await request<MoveJob>(url);
      } catch (inner) {
        error.value = `移动结果未知：${errorText(inner)}。请刷新核对结果，不会自动重试。`;
      }
    }
  } finally {
    plan.value = null;
    busy.value = false;
    await load();
  }
}

watch(() => `${props.company.id}/${props.dirKey}`, () => {
  check.value = null;
  plan.value = null;
  result.value = null;
  void load();
}, { immediate: true });
</script>

<template>
  <section class="panel" aria-label="属期文件夹核对">
    <h3>属期文件夹核对</h3>
    <p class="muted">按文件内容（抵扣清单的税款所属期、对账单的起止日期）核对它所在的属期文件夹；文件夹名只用来提示，不参与任何计算。</p>
    <div class="toolbar">
      <button type="button" :disabled="loading" :aria-busy="loading" @click="load">{{ loading ? "核对中…" : "重新核对" }}</button>
      <label class="nowrap"><input v-model="showAll" type="checkbox"> 显示全部文件</label>
      <button type="button" class="primary" :disabled="busy || !selected.length" @click="prepare">移动所选…（{{ selected.length }}）</button>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <template v-if="check">
      <p :class="{ 'check--failed': check.mismatched }" role="status">
        {{ check.mismatched ? `${check.mismatched} 个文件可能放错了属期文件夹` : "没有发现放错属期文件夹的文件" }}
        <span class="muted">（属期文件夹：{{ check.folders.map((folder) => folder.name).join("、") || "没有" }}）</span>
      </p>
      <table v-if="shown.length" class="grid" aria-label="属期文件">
        <thead><tr><th>文件</th><th>所在文件夹</th><th>内容属期</th><th>核对</th><th>移到</th></tr></thead>
        <tbody>
          <tr v-for="item in shown" :key="item.file" :class="{ 'row--failed': item.status === 'mismatch' }">
            <td>{{ item.file }}</td>
            <td>{{ item.folder || "（根目录）" }}<span v-if="item.folder_period" class="muted"> · {{ item.folder_period }}</span></td>
            <td class="nowrap">{{ item.content_period || "—" }}</td>
            <td class="nowrap">{{ STATUS[item.status] }}</td>
            <td>
              <select v-if="item.content_period" v-model="chosen[item.file]" :aria-label="`${item.file} 移到`">
                <option value="">不移动</option>
                <option v-for="name in targetsFor(item)" :key="name" :value="name">
                  {{ name }}{{ name === item.target ? "（建议）" : "" }}{{ (check.folders ?? []).some((folder) => folder.name === name) ? "" : "（新建）" }}
                </option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </template>
    <div v-if="plan" class="panel" role="alertdialog" aria-label="确认移动文件">
      <p>将移动 {{ plan.files.length }} 个文件（不覆盖同名文件；不能自动撤回，需要时可再移回）：</p>
      <ul class="selection-bar__files">
        <li v-for="file in plan.files" :key="file.file">{{ file.file }} → {{ file.target }}/<span v-if="file.new_folder" class="muted">（新建文件夹）</span></li>
      </ul>
      <div class="toolbar">
        <button type="button" class="primary" :disabled="busy" :aria-busy="busy" @click="confirmMove">确认移动</button>
        <button type="button" :disabled="busy" @click="plan = null">取消</button>
      </div>
    </div>
    <div v-if="result" class="panel" role="status" aria-label="移动结果">
      <p>已移动 {{ result.moved_count }} / {{ result.files.length }} 个文件<template v-if="result.state !== 'completed'">；其余未确认完成，请核对文件夹，不会自动重复移动</template>。</p>
      <ul v-if="result.state !== 'completed'" class="selection-bar__files">
        <li v-for="file in result.files" :key="file.file">{{ file.file }} <small class="muted">{{ file.message || FILE_STATUS[file.status] || "" }}</small></li>
      </ul>
    </div>
  </section>
</template>
