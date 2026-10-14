<template>
  <div class="topbar">
    <h2>诊断</h2>
    <div><button class="small" @click="download">下载脱敏诊断包</button></div>
  </div>
  <p class="muted">诊断包仅包含配置数量、订阅域名主机部分等统计信息，不含订阅 token、节点服务器地址和面板密码。</p>
  <div class="card">
    <div style="margin-bottom:8px"><button class="small ghost" @click="load">刷新</button></div>
    <pre class="code">{{ text }}</pre>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get } from '../api.js'

const toast = inject('toast')
const text = ref('(加载中…)')

async function load() {
  try { text.value = JSON.stringify(await get('/api/diagnostics'), null, 2) }
  catch (e) { text.value = e.message }
}
async function download() {
  try {
    const r = await fetch('/api/diagnostics')
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'openbox-diagnostics.json'
    a.click()
  } catch (e) { toast(e.message) }
}

onMounted(load)
</script>
