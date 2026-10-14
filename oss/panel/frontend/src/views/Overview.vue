<template>
  <div class="topbar"><h2>概览</h2><span class="sub">运行状态总览</span></div>

  <div v-if="stale" class="alert">
    配置已更改，尚未应用到内核。<router-link to="/config">去应用 →</router-link>
  </div>

  <div class="grid c4">
    <div class="card stat"><div class="num">{{ nodes.length }}</div><div class="lbl">节点</div></div>
    <div class="card stat"><div class="num">{{ sites.length }}</div><div class="lbl">站点集</div></div>
    <div class="card stat"><div class="num">{{ healthOk }} / {{ health.length }}</div><div class="lbl">健康检查通过</div></div>
    <div class="card stat"><div class="num">{{ svc.running ? '运行中' : '已停止' }}</div><div class="lbl">内核服务</div></div>
  </div>

  <div class="card">
    <h3>内核服务 <span :class="['pill', svc.running ? 'ok' : '']">{{ svc.running ? '运行中' : '已停止' }}</span></h3>
    <p class="muted">版本 {{ svc.version || '—' }} · PID {{ svc.pid || '—' }} ·
      运行 {{ svc.uptime_s != null ? Math.round(svc.uptime_s) + 's' : '—' }} ·
      二进制 {{ svc.bin_path }}</p>
    <div>
      <button class="small" @click="svcAct('/api/service/start', '启动')">启动</button>
      <button class="small ghost" @click="svcAct('/api/service/stop', '停止')">停止</button>
      <button class="small ghost" @click="svcAct('/api/service/restart', '重启')">重启</button>
      <button class="small" @click="apply">应用配置</button>
      <button class="small ghost" @click="toggleLog">查看日志</button>
    </div>
    <pre v-if="showLog" class="code">{{ logText }}</pre>
  </div>

  <div class="card">
    <h3>站点延迟 <span class="muted">经内核回环代理测速</span></h3>
    <div v-if="slSites.length" class="grid c4">
      <div v-for="s in slSites" :key="s.id" class="card stat" style="margin:0">
        <div class="num">{{ latestLat(s.id) }}</div>
        <div class="lbl">{{ s.name }}</div>
        <div class="muted" style="font-size:11px">{{ s.url }}</div>
      </div>
    </div>
    <p v-else class="muted">尚未配置测试站点。</p>
    <div style="margin-top:8px">
      <button class="small ghost" @click="checkSites" :disabled="checking">{{ checking ? '测速中…' : '立即测速' }}</button>
      <button class="small ghost" @click="showSiteForm = !showSiteForm">管理站点</button>
    </div>
    <form v-if="showSiteForm" @submit.prevent="saveSites" style="margin-top:10px">
      <label>站点（每行：名称|URL）</label>
      <textarea v-model="siteText" rows="4"></textarea>
      <div style="margin-top:8px"><button class="small">保存</button></div>
    </form>
  </div>

  <div class="card">
    <h3>节点健康</h3>
    <table v-if="health.length">
      <tr><th>节点</th><th>状态</th><th>延迟</th><th>检查时间</th></tr>
      <tr v-for="h in health" :key="h.tag">
        <td>{{ h.tag }}</td>
        <td><span :class="['pill', h.ok ? 'ok' : 'bad']">{{ h.ok ? '正常' : '异常' }}</span></td>
        <td class="muted">{{ h.latency_ms != null ? Math.round(h.latency_ms) + ' ms' : '—' }}</td>
        <td class="muted">{{ h.checked_at }}</td>
      </tr>
    </table>
    <p v-else class="muted">暂无数据，去「代理」页执行健康检查。</p>
  </div>

  <p class="muted">面板版本 {{ ver.panel }} · sing-box 内核：{{ ver.singbox }}</p>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post } from '../api.js'

const toast = inject('toast')
const nodes = ref([]), sites = ref([]), health = ref([])
const svc = ref({}), ver = ref({})
const stale = ref(false)
const showLog = ref(false), logText = ref('(空)')
const slSites = ref([]), slChecks = ref([])
const checking = ref(false), showSiteForm = ref(false), siteText = ref('')

const healthOk = () => health.value.filter(h => h.ok).length

function latestLat(id) {
  const c = [...slChecks.value].reverse().find(c => c.site_id === id)
  return c && c.ok && c.latency_ms != null ? Math.round(c.latency_ms) + ' ms' : '—'
}

async function load() {
  const [n, s, h, sv, v] = await Promise.all([
    get('/api/nodes'), get('/api/sitesets'), get('/api/health'),
    get('/api/service'), get('/api/upgrade/status').catch(() => ({})),
  ])
  nodes.value = n; sites.value = s; health.value = h; svc.value = sv; ver.value = v
  stale.value = !!sv.config_stale
  const sl = await get('/api/site-latency').catch(() => ({ sites: [] }))
  slSites.value = sl.sites || []
  siteText.value = slSites.value.map(x => x.name + '|' + x.url).join('\n')
  const hist = await get('/api/site-latency/history?days=1').catch(() => ({ checks: [] }))
  slChecks.value = hist.checks || []
}

async function svcAct(path, label) {
  try { await post(path, {}); toast(label + '已执行'); load() }
  catch (e) { toast(e.message) }
}
async function apply() {
  try {
    const r = await post('/api/config/apply', {})
    toast(`已应用：${r.outbounds} 出站 / ${r.route_rules} 路由规则`); load()
  } catch (e) { toast(e.message) }
}
async function toggleLog() {
  showLog.value = !showLog.value
  if (showLog.value) {
    try {
      const r = await get('/api/service/log?n=100')
      logText.value = (r.log || []).join('\n') || '(空)'
    } catch (e) { logText.value = e.message }
  }
}
async function checkSites() {
  checking.value = true
  try { await post('/api/site-latency/check', {}); toast('测速完成'); load() }
  catch (e) { toast(e.message) }
  checking.value = false
}
async function saveSites() {
  const sites = siteText.value.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
    const i = l.indexOf('|')
    return i > 0 ? { name: l.slice(0, i).trim(), url: l.slice(i + 1).trim() } : { name: l, url: l }
  })
  try { await post('/api/site-latency', { sites }); toast('已保存'); showSiteForm.value = false; load() }
  catch (e) { toast(e.message) }
}

onMounted(load)
</script>
