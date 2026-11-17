<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import WorkspaceIcon from "./WorkspaceIcon.vue";
// `marked` months carry the prototype green dot ("有资料或凭证"); `only` restricts the choice to them.
const props = defineProps<{ modelValue: string; label: string; min?: string; max?: string; marked?: string[]; only?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const root = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
const open = ref(false);
const year = ref(new Date().getFullYear());
const position = ref({ left: "0px", top: "0px" });
const text = computed(() => /^\d{4}-\d{2}$/.test(props.modelValue) ? `${props.modelValue.slice(0, 4)} 年 ${Number(props.modelValue.slice(5))} 月` : "选择年月");
const thisMonth = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}`;
function valueOf(month: number): string { return `${year.value}-${String(month).padStart(2, "0")}`; }
function disabled(month: number): boolean { const value = valueOf(month); return !!((props.min && value < props.min) || (props.max && value > props.max) || (props.only && !props.marked?.includes(value))); }
async function toggle(): Promise<void> {
  open.value = !open.value;
  if (!open.value) return;
  year.value = Number(props.modelValue.slice(0, 4)) || new Date().getFullYear();
  const box = trigger.value!.getBoundingClientRect();
  const top = box.bottom + 6 + 240 <= window.innerHeight ? box.bottom + 6 : Math.max(8, box.top - 246);
  position.value = { left: `${Math.max(8, Math.min(box.left, window.innerWidth - 280))}px`, top: `${top}px` };
  await nextTick();
  root.value?.querySelector<HTMLButtonElement>(".month-picker__months button[aria-pressed='true']:not(:disabled)")?.focus();
}
function choose(month: number): void {
  if (disabled(month)) return;
  emit("update:modelValue", valueOf(month));
  open.value = false;
  trigger.value?.focus();
}
function close(event: Event): void {
  if (event.type === "keydown" && (event as KeyboardEvent).key !== "Escape") return;
  if (event.type === "pointerdown" && root.value?.contains(event.target as Node)) return;
  if (open.value) { open.value = false; if (event.type === "keydown") { event.preventDefault(); trigger.value?.focus(); } }
}
onMounted(() => { document.addEventListener("pointerdown", close); document.addEventListener("keydown", close); });
onBeforeUnmount(() => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); });
</script>

<template>
  <span ref="root" class="month-picker">
    <button ref="trigger" type="button" :aria-label="label" aria-haspopup="dialog" :aria-expanded="open" @click="toggle"><WorkspaceIcon name="cal" />{{ text }} ▾</button>
    <input class="month-picker__native" type="month" :aria-label="label" :value="modelValue" :min="min" :max="max" tabindex="-1" @change="emit('update:modelValue', ($event.target as HTMLInputElement).value)">
    <span v-if="open" class="month-picker__popover" :style="position" role="dialog" :aria-label="label">
      <span class="month-picker__year"><button type="button" aria-label="上一年" :disabled="!!min && year <= Number(min.slice(0, 4))" @click="year--">‹</button><strong>{{ year }} 年</strong><button type="button" aria-label="下一年" :disabled="!!max && year >= Number(max.slice(0, 4))" @click="year++">›</button></span>
      <span class="month-picker__months"><button v-for="month in 12" :key="month" type="button" :class="{ 'has-data': marked?.includes(valueOf(month)) }" :aria-pressed="modelValue === valueOf(month)" :disabled="disabled(month)" @click="choose(month)">{{ month }} 月</button></span>
      <span class="month-picker__foot"><span><i v-if="marked" class="month-picker__dot" />{{ marked ? "有凭证草稿" : "选择所属年月" }}</span><button type="button" :disabled="(!!min && thisMonth < min) || (!!max && thisMonth > max)" @click="year = Number(thisMonth.slice(0, 4)); choose(Number(thisMonth.slice(5)))">本月</button></span>
    </span>
  </span>
</template>
