<template>
  <div class="topbar"><h2>规则调试</h2><span class="sub">路由穿透 + 真实请求测试</span></div>

  <div class="card">
    <h3>域名穿透</h3>
    <form @submit.prevent="penetrate" class="form-row">
      <div><input v-model="target" placeholder="example.com" required></div>
      <div style="flex:0"><button>穿透</button></div>
    </form>
    <div v-if="pen">
      <p><b>命中站点集链：</b></p>
      <div v-for="(c, i) in pen.chain" :key="i" style="margin-bottom:4px">
        <span class="pill">{{ c.level }}</span> {{ c.name }}
        <span v-if="c.action" class="muted">→ {{ c.action }}</span>
        <span v-if="i < pen.chain.length - 1"> → </span>
      </div>
      <p v-if="pen.node" class="muted">当前节点：{{ pen.node.tag }}（{{ pen.node.protocol }} {{ pen.node.server }}:{{ pen.node.port }}）</p>
      <p v-if="!pen.kernel" class="muted">内核未运行，节点解析不可用</p>
    </div>
  </div>

  <div class="card">
    <h3>真实路由测试 <span class="muted">真实 HTTPS 请求（经内核 HTTP 代理）</span></h3>
    <form @submit.prevent="test" class="form-row">
      <div><input v-model="url" placeholder="https://example.com" required></div>
      <div style="flex:0"><button :disabled="busy">{{ busy ? '测试中…' : '测试' }}</button></div>
    </form>
    <div v-if="result">
      <dl class="kv">
        <dt>URL</dt><dd>{{ result.url }}</dd>
        <dt>命中</dt><dd>{{ result.preview?.site_set }}（{{ result.preview?.action }}）</dd>
        <dt>状态码</dt><dd>{{ result.status }}</dd>
        <dt>最终 URL</dt><dd class="muted">{{ result.final_url }}</dd>
        <dt>耗时</dt><dd>{{ result.elapsed_ms }} ms</dd>
      </dl>
      <p v-if="result.error" class="danger-text">{{ result.error }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, inject } from 'vue'
import { post } from '../api.js'

const toast = inject('toast')
const target = ref(''), url = ref('')
const pen = ref(null), result = ref(null)
const busy = ref(false)

async function penetrate() {
  try { pen.value = await post('/api/route/penetrate', { target: target.value }) }
  catch (e) { toast(e.message) }
}
async function test() {
  busy.value = true; result.value = null
  try { result.value = await post('/api/route/test', { url: url.value }) }
  catch (e) { toast(e.message) }
  busy.value = false
}
</script>
