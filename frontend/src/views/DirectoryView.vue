<script setup lang="ts">
import { useSystemStore } from "../stores/system";

const system = useSystemStore();
</script>

<template>
  <section>
    <header class="page-header">
      <h1>目录</h1>
    </header>
    <p class="muted">多公司工作区的侧栏会在这里接入；当前只读显示单活动监控目录。</p>
    <table class="facts">
      <tbody>
        <tr>
          <th scope="row">活动目录</th>
          <td>{{ system.settings?.watch_dir || "—" }}</td>
        </tr>
        <tr>
          <th scope="row">目标档案</th>
          <td>{{ system.settings?.active_target_id || "—" }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
