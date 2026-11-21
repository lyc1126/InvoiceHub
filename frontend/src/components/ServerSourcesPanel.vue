<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText } from "../format";
import { useCompaniesStore } from "../stores/companies";

interface Source {
  id: string; name: string; protocol: "mounted" | "sftp"; root: string; revision: number;
  connection: string; sync: string; error: string; task_id: string; fingerprints: string[]; fingerprint?: string;
  generation: string; snapshot: string; last_complete_at: string; last_verified_at?: string; coverage: string;
  entry_count: number; cached_count: number; cache_budget: number; binding?: { company_id: string; role: string } | null;
  progress?: { phase: string; completed?: number; total?: number; enumerated?: number; bytes?: number; total_bytes?: number; downloaded?: number };
}
interface Entry { id: string; name: string; relative: string; kind: "file" | "directory"; size: number }
interface Listing { source: Source; items: Entry[]; count: number; page: number; breadcrumbs: { id: string; name: string }[]; scope: { files: number; bytes: number; readable_files?: number } }
interface Summary { available: boolean; count?: number; stale?: boolean; last_complete_at?: string; scope?: string;
  ledger?: { totals: { input: { count: number; total: string; pretax: string; tax: string } } };
  items?: { entry_id: string; relative: string; invoice_number: string; amount: string }[]; stats?: { parsed: number; reused: number } }
interface Preview { job_id: string; preview_type: string; page_count: number; reason: string; stale: boolean; verified_at: string; entry_id: string }
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();
const companies = useCompaniesStore();
const sources = ref<Source[]>([]), selected = ref("");
const source = computed(() => sources.value.find(s => s.id === selected.value));
const expanded = ref(false), adding = ref(false), busy = ref(false), error = ref("");
const form = ref({ protocol: "mounted", name: "", root: "", host: "", port: 22, username: "" });
const parent = ref(""), keyword = ref(""), page = ref(1), listing = ref<Listing>();
const summary = ref<Summary>(), preview = ref<Preview>(), text = ref(""), previewPage = ref(1);
const tabs = ref<Entry[]>([]), pendingPreview = ref(""), company = ref(""), role = ref("cost_invoice_dir"), budget = ref(1024);
const running = computed(() => source.value && ["connecting", "scanning", "downloading", "parsing", "publishing"].includes(source.value.sync));
const progress = computed(() => source.value?.progress);
const phase: Record<string, string> = { connecting: "正在连接", scanning: "正在核对目录", downloading: "正在校验下载", parsing: "正在解析", publishing: "正在发布", idle: "就绪", failed: "失败", cancelled: "已取消" };
const connection: Record<string, string> = { online: "已连接", offline: "离线", connecting: "连接中", auth_required: "需要认证", host_key_changed: "主机指纹变化", root_changed: "根目录身份变化" };
const bytes = (value: number) => value < 1024**2 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1024**2).toFixed(1)} MiB`;
let timer: ReturnType<typeof setTimeout> | undefined, turn = 0, previewTurn = 0;
function update(value: Source): void { const index = sources.value.findIndex(s => s.id === value.id); if (index < 0) sources.value.push(value); else sources.value[index] = value; }
async function action<T>(fn: () => Promise<T>): Promise<T | undefined> {
  error.value = ""; busy.value = true;
  try { return await fn(); } catch (e) { error.value = errorText(e); } finally { busy.value = false; }
}
async function load(): Promise<void> {
  await action(async () => { const data = await request<{ sources: Source[]; error?: string }>("/api/v1/sources"); sources.value = data.sources; if (data.error) error.value = data.error;
    const id = sources.value.find(s => s.id === selected.value)?.id ?? sources.value[0]?.id;
    // Rehydrate the saved binding/budget before exposing Save after reopening.
    if (id) await select(id);
    else { selected.value = ""; listing.value = undefined; summary.value = undefined; adding.value = true; }
  });
}
async function refresh(): Promise<void> {
  clearTimeout(timer);
  if (!selected.value || !props.open) return;
  const id = selected.value, epoch = ++turn;
  try {
    const [data, totals] = await Promise.all([
      request<Listing>(`/api/v1/sources/${id}/entries?parent_id=${parent.value}&page=${page.value}&keyword=${encodeURIComponent(keyword.value)}`),
      request<Summary>(`/api/v1/sources/${id}/summary?parent_id=${parent.value}`),
    ]);
    if (id !== selected.value || epoch !== turn) return;
    listing.value = data; update(data.source); summary.value = totals;
    if (!running.value && pendingPreview.value) {
      const entryId = pendingPreview.value; pendingPreview.value = "";
      if (!data.source.error && data.source.connection === "online") await showPreview(entryId, false);
    }
  } catch (e) { if (epoch === turn) error.value = errorText(e); }
  if (props.open && running.value) timer = setTimeout(() => void refresh(), 700);
}
async function select(id: string): Promise<void> {
  const epoch = ++turn;
  await closePreview();
  if (epoch !== turn) return;
  selected.value = id; parent.value = ""; page.value = 1; keyword.value = ""; preview.value = undefined; pendingPreview.value = ""; tabs.value = [];
  const s = source.value; company.value = s?.binding?.company_id ?? ""; role.value = s?.binding?.role ?? "cost_invoice_dir"; budget.value = (s?.cache_budget ?? 1024**3) / 1024**2;
  await refresh();
}
async function add(): Promise<void> { await action(async () => {
  const result = await request<{ source: Source }>("/api/v1/sources", { method: "POST", body: form.value });
  update(result.source); adding.value = false; await select(result.source.id);
}); }
async function pick(): Promise<void> { await action(async () => {
  const result = await request<{ path?: string; selected_path?: string }>("/api/v1/sources/pick", { method: "POST", body: {} });
  if (result.path || result.selected_path) form.value.root = result.path ?? result.selected_path ?? "";
}); }
async function start(kind: string, extra: object = {}): Promise<void> { await action(async () => {
  const result = await request<{ source: Source }>(`/api/v1/sources/${selected.value}/tasks`, { method: "POST", body: { kind, ...extra } });
  update(result.source); await refresh();
}); }
async function confirmFingerprint(fingerprint: string): Promise<void> { await action(async () => {
  const result = await request<{ source: Source }>(`/api/v1/sources/${selected.value}/fingerprint`, { method: "POST", body: { revision: source.value?.revision, fingerprint } });
  update(result.source);
}); }
async function stop(disconnect = false): Promise<void> { await action(async () => {
  const result = await request<{ source: Source }>(`/api/v1/sources/${selected.value}/${disconnect ? "disconnect" : "cancel"}`, { method: "POST", body: {} });
  update(result.source); pendingPreview.value = ""; await refresh();
}); }
async function directory(id: string): Promise<void> { await closePreview(); parent.value = id; page.value = 1; keyword.value = ""; await refresh(); }
async function openEntry(entry: Entry): Promise<void> {
  if (entry.kind === "directory") { await directory(entry.id); return; }
  if (!tabs.value.some(t => t.id === entry.id)) tabs.value.push(entry);
  if (source.value?.connection === "online") { pendingPreview.value = entry.id; await start("download", { entry_id: entry.id }); }
  else await showPreview(entry.id, true);
}
async function showPreview(id: string, stale: boolean): Promise<void> { await action(async () => {
  const sid = selected.value;
  await closePreview();
  const epoch = previewTurn;
  const result = await request<Preview>(`/api/v1/sources/${sid}/previews`, { method: "POST", body: { entry_id: id, allow_stale: stale } });
  // Closing or switching while rendering invalidates the request and its server lease.
  if (sid !== selected.value || epoch !== previewTurn || !props.open) {
    await request(`/api/v1/sources/${sid}/previews/${result.job_id}`, { method: "DELETE" }).catch(() => undefined); return;
  }
  preview.value = result; previewPage.value = 1; text.value = "";
  if (result.preview_type === "text") { const content = await request<{ text: string }>(`/api/v1/sources/${selected.value}/previews/${result.job_id}/text`); if (sid === selected.value && preview.value?.job_id === result.job_id) text.value = content.text; }
}); }
async function saveSettings(): Promise<void> { await action(async () => {
  const result = await request<{ source: Source }>(`/api/v1/sources/${selected.value}`, { method: "PATCH", body: { revision: source.value?.revision,
    cache_budget: Math.round(budget.value * 1024**2), binding: company.value ? { company_id: company.value, role: role.value } : null } });
  update(result.source); await closePreview(); await refresh();
}); }
async function closePreview(): Promise<void> {
  ++previewTurn;
  const old = preview.value, sid = selected.value; preview.value = undefined;
  if (old) await request(`/api/v1/sources/${sid}/previews/${old.job_id}`, { method: "DELETE" }).catch(() => undefined);
}
async function forget(): Promise<void> {
  if (!source.value || !window.confirm("移除此来源收藏和本机缓存？服务器文件不会改动。")) return;
  await action(async () => { await closePreview(); await request(`/api/v1/sources/${selected.value}?revision=${source.value?.revision}`, { method: "DELETE" }); selected.value = ""; listing.value = undefined; await load(); });
}
async function clearCache(): Promise<void> { await action(async () => { await request(`/api/v1/sources/${selected.value}/cache`, { method: "DELETE" }); await refresh(); }); }
watch(() => props.open, open => { if (open) void load(); else { ++turn; clearTimeout(timer); void closePreview(); } }, { immediate: true });
onBeforeUnmount(() => { ++turn; clearTimeout(timer); void closePreview(); });
</script>

<template>
  <aside v-if="open" class="server-panel" :class="{ 'server-panel--wide': expanded }" aria-label="服务器文件" @keydown.esc.stop="preview ? closePreview() : emit('close')">
    <header><strong>服务器链接 <small>试验版 · 只读</small></strong><span class="spacer" />
      <button type="button" :aria-label="expanded ? '还原文件面板' : '放大文件面板'" @click="expanded = !expanded">{{ expanded ? '还原' : '放大' }}</button>
      <button type="button" aria-label="收起服务器文件" @click="emit('close')">收起</button></header>
    <div class="server-body">
      <p class="muted">SMB 请先在系统挂载共享；SFTP 仅使用本机 OpenSSH 与 SSH Agent。连接不会更换监控目录。</p>
      <div class="source-picker"><label>收藏来源 <select :value="selected" aria-label="收藏来源" @change="select(($event.target as HTMLSelectElement).value)"><option value="">选择来源</option><option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option></select></label><button type="button" @click="adding = !adding">添加</button></div>
      <form v-if="adding" class="source-form" @submit.prevent="add">
        <label>协议<select v-model="form.protocol"><option value="mounted">已挂载 SMB / 共享目录</option><option value="sftp">SSH / SFTP</option></select></label>
        <label>收藏名称<input v-model="form.name" required maxlength="100"></label>
        <template v-if="form.protocol === 'sftp'"><label>主机<input v-model="form.host" required placeholder="服务器主机名，不含 sftp://"></label><label>端口<input v-model.number="form.port" type="number" min="1" max="65535" required></label><label>用户名<input v-model="form.username" required autocomplete="off"></label><p class="muted">认证：SSH Agent；不保存密码或私钥。跳板机暂未接入。</p></template>
        <label>{{ form.protocol === 'mounted' ? '系统挂载目录' : '服务器根目录' }}<input v-model="form.root" required :placeholder="form.protocol === 'mounted' ? '已挂载的绝对路径' : '/invoices'"></label>
        <div class="actions"><button v-if="form.protocol === 'mounted'" type="button" @click="pick">选择目录</button><button type="submit" :disabled="busy">保存来源</button><button type="button" @click="adding = false">取消</button></div>
      </form>
      <p v-if="error" class="server-error" role="alert">{{ error }}</p>
      <template v-if="source">
        <p class="source-state" role="status">{{ connection[source.connection] ?? source.connection }} · {{ phase[source.sync] ?? source.sync }}<span v-if="source.snapshot !== 'none'"> · 清单截至 {{ source.last_complete_at }}</span></p>
        <p class="source-path">服务器源目录：{{ source.root }}</p><p class="muted">本机汇总位置：应用私有运行目录 / server-sources / 本来源。共 {{ source.entry_count }} 项，已缓存 {{ source.cached_count }} 个文件。</p>
        <p v-if="source.error" class="server-error" role="alert">{{ source.error }}</p>
        <div class="actions"><button v-if="source.protocol === 'sftp'" type="button" :disabled="!!running || busy" @click="start('probe')">读取主机指纹</button><button type="button" :disabled="!!running || busy" @click="start('scan')">连接 / 刷新目录</button><button type="button" @click="stop(true)">断开</button><button type="button" :disabled="!!running || busy" @click="forget">移除收藏</button></div>
        <div v-if="source.fingerprints.length" class="fingerprints"><p>请通过管理员提供的独立渠道核对指纹；确认后方可连接。</p><div v-for="fp in source.fingerprints" :key="fp"><code>{{ fp }}</code><button type="button" :disabled="source.fingerprint === fp || !!running || busy" @click="confirmFingerprint(fp)">{{ source.fingerprint === fp ? '已确认' : '已核对，信任此指纹' }}</button></div></div>
        <details><summary>公司归属与缓存设置</summary><p class="muted">归属仅作来源标注；公司、做账、税费等模块尚未接入，不计入其统计。</p><label>公司<select v-model="company"><option value="">未归属</option><option v-for="c in companies.companies" :key="c.id" :value="c.id">{{ c.name }}</option></select></label><label>角色<select v-model="role"><option value="cost_invoice_dir">进项发票</option><option value="issued_invoice_dir">销项发票</option></select></label><label>副本预算（MiB）<input v-model.number="budget" type="number" min="64" max="10240"></label><div class="actions"><button type="button" :disabled="!!running || busy" @click="saveSettings">保存设置</button><button type="button" :disabled="!!running || busy" @click="clearCache">清除离线副本</button></div></details>
        <nav v-if="listing" class="breadcrumbs" aria-label="服务器目录路径"><button v-for="crumb in listing.breadcrumbs" :key="crumb.id" type="button" @click="directory(crumb.id)">{{ crumb.name }} /</button></nav>
        <div class="directory-tab"><strong>{{ listing?.breadcrumbs.at(-1)?.name ?? source.name }}</strong><label>子目录<select aria-label="切换服务器目录" :value="''" @change="directory(($event.target as HTMLSelectElement).value)"><option value="" disabled>选择直接子目录</option><option v-for="dir in listing?.items.filter(e => e.kind === 'directory')" :key="dir.id" :value="dir.id">{{ dir.name }}</option></select></label></div>
        <div v-if="running" class="source-progress" role="status"><span>{{ phase[progress?.phase ?? source.sync] }}<template v-if="progress?.total !== undefined"> {{ progress.completed ?? 0 }} / {{ progress.total }}</template><template v-else-if="progress?.enumerated !== undefined"> · 已枚举 {{ progress.enumerated }} 项</template><template v-if="progress?.bytes !== undefined"> · {{ bytes(progress.bytes) }} / {{ bytes(progress.total_bytes ?? 0) }}</template></span><progress :value="progress?.total ? progress.completed : undefined" :max="progress?.total ?? 1" /><button type="button" @click="stop()">取消任务</button></div>
        <form class="filter" @submit.prevent="page = 1; refresh()"><input v-model="keyword" aria-label="筛选服务器文件" placeholder="筛选当前目录文件"><button type="submit">筛选</button></form>
        <p v-if="listing" class="muted">当前目录（含子目录）：{{ listing.scope.files }} 个文件 · {{ bytes(listing.scope.bytes) }}</p>
        <ul class="server-files"><li v-for="entry in listing?.items" :key="entry.id"><button type="button" :disabled="!!running && entry.kind === 'file'" @click="openEntry(entry)"><span>{{ entry.kind === 'directory' ? '▸' : '·' }} {{ entry.name }}</span><small>{{ entry.kind === 'file' ? `${source.connection === 'online' ? '' : '查看离线副本 · '}${bytes(entry.size)}` : '文件夹' }}</small></button></li></ul>
        <p v-if="!source.generation" class="muted">尚无完整缓存，请连接并刷新目录。</p><p v-else-if="listing && !source.error && (keyword ? !listing.items.length : listing.scope.readable_files === 0 || !listing.items.length)" class="muted">{{ keyword ? '没有匹配的文件' : '无可读取的文件' }}</p>
        <div v-if="listing && listing.count > 200" class="actions"><button type="button" :disabled="page === 1" @click="--page; refresh()">上一页</button><span>{{ page }} / {{ Math.ceil(listing.count / 200) }}</span><button type="button" :disabled="page * 200 >= listing.count" @click="++page; refresh()">下一页</button></div>
        <div class="actions"><button type="button" :disabled="!!running || source.connection !== 'online' || busy" @click="start('summary')">增量汇总</button><button type="button" :disabled="!!running || source.connection !== 'online' || busy" @click="start('summary', { verify: true })">校验全部内容</button><button type="button" :disabled="!!running || source.connection !== 'online' || busy" @click="start('summary', { full: true })">完整重建</button></div>
        <p class="muted">标准 SMB / SFTP 每次完整核对元数据；SFTP 无稳定文件 ID，不能保证远程原子快照。未变文件复用解析，每日或显式核验内容。</p>
        <section v-if="summary?.available" class="source-summary"><strong>目录票面汇总 · {{ summary.ledger?.totals.input.count }} 张（同票去重）</strong><p>不含税 {{ summary.ledger?.totals.input.pretax }} · 税额 {{ summary.ledger?.totals.input.tax }} · 价税合计 {{ summary.ledger?.totals.input.total }}</p><p class="muted">{{ summary.stale ? '上次完整结果，当前未核验' : '完整结果' }} · {{ summary.last_complete_at }} · 解析 {{ summary.stats?.parsed }} / 复用 {{ summary.stats?.reused }}</p><p class="muted">{{ summary.scope }}</p><table><thead><tr><th>来源</th><th>发票号</th><th>价税合计</th></tr></thead><tbody><tr v-for="item in summary.items" :key="item.entry_id"><td>{{ item.relative }}</td><td>{{ item.invoice_number || '待核对' }}</td><td>{{ item.amount || '未识别' }}</td></tr></tbody></table></section>
        <nav v-if="tabs.length" class="file-tabs" aria-label="服务器文件标签"><button v-for="tab in tabs" :key="tab.id" type="button" :class="{ active: preview?.entry_id === tab.id }" @click="openEntry(tab)">{{ source.connection === 'online' ? '' : '查看离线副本 · ' }}{{ tab.name }}</button></nav>
        <section v-if="preview" class="source-preview" aria-label="服务器文件预览"><p role="status">{{ preview.stale ? '离线副本（可能过期）' : '已校验副本' }} · 最后核验 {{ preview.verified_at }}</p><button type="button" @click="closePreview">关闭预览</button><pre v-if="preview.preview_type === 'text'">{{ text }}</pre><template v-else-if="preview.preview_type === 'pages'"><div class="actions"><button type="button" :disabled="previewPage <= 1" @click="--previewPage">上一页</button><span>{{ previewPage }} / {{ preview.page_count }}</span><button type="button" :disabled="previewPage >= preview.page_count" @click="++previewPage">下一页</button></div><img :src="`/api/v1/sources/${selected}/previews/${preview.job_id}/pages/${previewPage}`" alt="服务器文件预览" @error="error = '预览授权过期或文件变化，请重新打开。'"></template><p v-else>{{ preview.reason }}</p></section>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.server-panel { position:absolute; z-index:35; inset:0 0 0 auto; width:min(560px,100%); max-width:100%; background:var(--surface, #fff); border-left:1px solid var(--line, #ddd); box-shadow:-8px 0 24px #0001; display:flex; flex-direction:column; color:var(--ink); }
.server-panel--wide { width:100%; }
header { display:flex; align-items:center; gap:8px; padding:14px; border-bottom:1px solid var(--line); flex:none; }
.spacer { flex:1; } small,.muted { color:var(--muted); font-size:12px; } .muted { line-height:1.6; margin:8px 0; }
.server-body { overflow:auto; padding:16px; min-width:0; } button,input,select { font:inherit; max-width:100%; } button { cursor:pointer; } button:disabled { cursor:default; opacity:.5; }
label { display:flex; flex-direction:column; gap:5px; margin:8px 0; min-width:0; } input,select { padding:7px 9px; color:inherit; background:var(--surface); border:1px solid var(--line); border-radius:6px; }
.source-picker,.actions,.filter { display:flex; gap:8px; align-items:center; flex-wrap:wrap; } .source-picker label,.filter input { flex:1; } .actions { margin:10px 0; } button { padding:5px 8px; background:var(--surface); color:inherit; border:1px solid var(--line); border-radius:5px; }
.source-form,.fingerprints,details,.source-summary { padding:10px; margin:12px 0; border:1px solid var(--line); border-radius:8px; } .source-path,code { overflow-wrap:anywhere; font-size:12px; } .source-state { font-size:12px; } .server-error { color:var(--red, #b42318); font-size:13px; }
.breadcrumbs,.file-tabs { display:flex; gap:4px; overflow:auto; margin:12px 0; } .breadcrumbs button { white-space:nowrap; border:0; } .directory-tab { display:flex; gap:10px; justify-content:space-between; align-items:center; border-bottom:1px solid var(--line); } .directory-tab label { font-size:12px; }
.source-progress { display:flex; flex-wrap:wrap; gap:6px; font-size:12px; color:var(--blue,#287bd1); margin:8px 0; } progress { width:100%; accent-color:#287bd1; height:4px; }
.server-files { list-style:none; padding:0; margin:0; } .server-files button { width:100%; display:flex; justify-content:space-between; align-items:center; gap:10px; border:0; border-bottom:1px solid var(--line); border-radius:0; padding:9px 2px; text-align:left; } .server-files span { overflow-wrap:anywhere; min-width:0; } .server-files small { white-space:nowrap; }
.file-tabs button { white-space:nowrap; } .file-tabs .active { color:var(--blue,#287bd1); } .source-preview img { max-width:100%; } pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; } table { border-collapse:collapse; width:100%; font-size:12px; } th,td { text-align:left; border-bottom:1px solid var(--line); padding:7px 4px; overflow-wrap:anywhere; max-width:180px; }
@media (prefers-reduced-motion:reduce) { * { animation:none!important; transition:none!important; } }
</style>
