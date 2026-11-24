<script setup lang="ts">
import { WORKSPACE_ICONS } from "../icons";
defineProps<{ name: string }>();
</script>

<template>
  <!-- Only bundled paths from the approved prototype enter this SVG; never API or file content. -->
  <svg class="hub-icon" viewBox="0 0 24 24" aria-hidden="true" v-html="WORKSPACE_ICONS[name] ?? WORKSPACE_ICONS.folder" />
</template>
