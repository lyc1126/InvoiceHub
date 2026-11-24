import { ref } from "vue";

// Prototype toast: short, self-dismissing confirmation at the bottom centre. Use it only for
// success/neutral feedback; errors that need action stay as in-page banners (WEB_UI standard).
export const toastMessage = ref<{ text: string; tone: "info" | "error"; id: number } | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;

export function toast(text: string, tone: "info" | "error" = "info", ms = 2400): void {
  clearTimeout(timer);
  toastMessage.value = { text, tone, id: ++seq };
  timer = setTimeout(() => { toastMessage.value = null; }, ms);
}
