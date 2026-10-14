<template>
  <div class="topbar">
    <h2>配置</h2>
    <div>
      <select v-model="mode" style="max-width:140px">
        <option value="auto">自动</option><option value="hot">热应用</option><option value="full">完整重启</option>
      </select>
      <button @click="apply" :disabled="applying" style="margin-left:8px">
        {{ applying ? '应用中…' : '应用到内核' }}</button>
    </div>
  </div>
  <div v-if="result" :class="['alert', result.ok ? 'ok' : 'danger']">{{ result.msg }}</div>
  <div class="card">
    <div style="margin-bottom:8px"><button class="small ghost" @click="load">刷新预览</button></div>
    <pre class="code">{{ text }}</pre>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post } from '../api.js'

const toast = inject('toast')
const text = ref('(加载中…)')
const mode = ref('auto'), applying = ref(false), result = ref(null)

async function load() {
  try { text.value = JSON.stringify(await get('/api/config'), null, 2) }
  catch (e) { text.value = e.message }
}
async function apply() {
  applying.value = true; result.value = null
  try {
    const r = await post('/api/config/apply?mode=' + mode.value, {})
    result.value = { ok: true,
      msg: `已应用（${r.mode === 'hot' ? '热应用' : '完整重启'}）：${r.outbounds} 出站 / ${r.route_rules} 路由规则` }
  } catch (e) { result.value = { ok: false, msg: e.message } }
  applying.value = false
}

onMounted(load)
</script>
