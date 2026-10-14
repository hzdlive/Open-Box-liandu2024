<template>
  <div class="topbar"><h2>DNS</h2></div>

  <div class="tabs">
    <button v-for="t in tabs" :key="t.id" :class="{ active: tab === t.id }" @click="tab = t.id">{{ t.name }}</button>
  </div>

  <div v-if="tab === 'mode'" class="card">
    <h3>接管模式与上游</h3>
    <form @submit.prevent="saveDns">
      <div class="form-row">
        <div><label>接管模式</label><select v-model="dns.mode">
          <option value="dnsmasq">dnsmasq</option><option value="firewall">防火墙劫持</option><option value="off">关闭</option>
        </select></div>
        <div><label>地区</label><select v-model="dns.region">
          <option value="auto">自动</option><option value="cn">中国</option><option value="outside">海外</option>
        </select></div>
      </div>
      <label>直连 DNS（逗号分隔）</label>
      <input v-model="dns.direct_dns">
      <label style="margin-top:8px">代理 DNS（逗号分隔）</label>
      <input v-model="dns.proxy_dns">
      <p class="muted">检测到地区：{{ dns.region_detected || '—' }}</p>
      <div style="margin-top:8px">
        <button>保存</button>
        <button type="button" class="ghost" @click="detectRegion">检测地区</button>
        <button type="button" class="ghost" @click="getWan">查看 WAN DNS</button>
      </div>
    </form>
    <pre v-if="wanInfo" class="code">{{ wanInfo }}</pre>
  </div>

  <div v-if="tab === 'rewrite'" class="card">
    <h3>DNS 重写</h3>
    <table>
      <tr><th>域名</th><th>应答</th><th></th></tr>
      <tr v-for="r in dns.rewrites" :key="r.id">
        <td>{{ r.domain }}</td><td class="muted">{{ r.answer }}</td>
        <td><button class="small danger" @click="delRewrite(r.id)">删除</button></td>
      </tr>
    </table>
    <form @submit.prevent="addRewrite" class="form-row" style="margin-top:10px">
      <div><input v-model="rw.domain" placeholder="域名" required></div>
      <div><input v-model="rw.answer" placeholder="应答 IP / 域名" required></div>
      <div style="flex:0"><button class="small">添加</button></div>
    </form>
  </div>

  <div v-if="tab === 'filter'" class="card">
    <h3>过滤名单 <span class="muted">hosts / Adblock 格式，编译为 dnsmasq 规则</span></h3>
    <p class="muted">已编译 {{ filterInfo.compiled_domains || 0 }} 个域名 ·
      上次应用：{{ filterInfo.applied_at || '—' }}</p>
    <label><input type="checkbox" v-model="filter.enabled" style="width:auto"> 启用过滤</label>
    <table style="margin-top:8px">
      <tr><th>名称</th><th>URL</th><th>启用</th><th></th></tr>
      <tr v-for="(l, i) in filter.lists" :key="i">
        <td>{{ l.name }}</td>
        <td class="muted" style="max-width:300px;overflow:hidden;text-overflow:ellipsis">{{ l.url }}</td>
        <td><input type="checkbox" v-model="l.enabled" style="width:auto"></td>
        <td><button class="small danger" @click="filter.lists.splice(i, 1)">删除</button></td>
      </tr>
    </table>
    <form @submit.prevent="addFilterList" class="form-row" style="margin-top:10px">
      <div><input v-model="fl.name" placeholder="名单名称" required></div>
      <div><input v-model="fl.url" placeholder="名单 URL" required></div>
      <div style="flex:0"><button class="small">添加</button></div>
    </form>
    <div style="margin-top:8px">
      <button @click="saveFilter">保存</button>
      <button class="ghost" @click="applyFilter">下载并应用到 dnsmasq</button>
      <span class="muted">{{ filterMsg }}</span>
    </div>
    <form @submit.prevent="checkDomain" class="form-row" style="margin-top:12px">
      <div><input v-model="checkDom" placeholder="检查域名是否被拦截"></div>
      <div style="flex:0"><button class="small ghost">检查</button></div>
      <span v-if="checkRes" :class="['pill', checkRes.blocked ? 'bad' : 'ok']">
        {{ checkRes.blocked ? '会被拦截' : '不会被拦截' }}</span>
    </form>
  </div>

  <div v-if="tab === 'query'" class="card">
    <h3>查询日志 <span class="muted">需 dnsmasq 开启 log-queries</span></h3>
    <div style="margin-bottom:8px">
      <button class="small ghost" @click="loadQueryLog">刷新</button>
      <input v-model="qFilter" placeholder="过滤域名/IP" style="max-width:240px;margin-left:8px">
    </div>
    <p v-if="qNote" class="muted">{{ qNote }}</p>
    <table>
      <tr><th>终端</th><th>主机名</th><th>域名</th><th>类型</th><th>拦截</th></tr>
      <tr v-for="(q, i) in filteredQueries" :key="i">
        <td>{{ q.client }}</td><td class="muted">{{ q.hostname || '—' }}</td><td>{{ q.domain }}</td>
        <td class="muted">{{ q.qtype }}</td>
        <td><span v-if="q.blocked" class="pill bad">拦截</span><span v-else class="muted">—</span></td>
      </tr>
    </table>
  </div>

  <div v-if="tab === 'test'" class="card">
    <h3>上游实测</h3>
    <form @submit.prevent="testUpstream" class="form-row">
      <div><input v-model="tu.upstream" placeholder="上游，如 8.8.8.8 / tls://8.8.8.8 / https://dns.google/dns-query" required></div>
      <div><input v-model="tu.domain" placeholder="测试域名，默认 example.com"></div>
      <div style="flex:0"><button :disabled="tuBusy">{{ tuBusy ? '测试中…' : '测试' }}</button></div>
    </form>
    <div v-if="tuResult">
      <dl class="kv">
        <dt>上游</dt><dd>{{ tuResult.upstream }}</dd>
        <dt>延迟</dt><dd>{{ tuResult.latency_ms }} ms</dd>
        <dt>应答</dt><dd class="muted">{{ (tuResult.answers || []).join(', ') || '—' }}</dd>
      </dl>
      <p v-if="tuResult.error" class="danger-text">{{ tuResult.error }}</p>
    </div>
  </div>

  <div v-if="tab === 'trace'" class="card">
    <h3>链路追踪 <span class="muted">看域名经哪条 DNS 链路解析</span></h3>
    <form @submit.prevent="trace" class="form-row">
      <div><input v-model="trDomain" placeholder="example.com" required></div>
      <div style="flex:0"><button :disabled="trBusy">{{ trBusy ? '追踪中…' : '追踪' }}</button></div>
    </form>
    <div v-if="trResult">
      <dl class="kv">
        <dt>域名</dt><dd>{{ trResult.domain }}</dd>
        <dt>命中</dt><dd>{{ trResult.site_set }}（{{ trResult.action }}）</dd>
        <dt>链路</dt><dd>{{ trResult.link }}</dd>
        <dt>上游</dt><dd class="muted">{{ trResult.upstream }}</dd>
        <dt>应答</dt><dd class="muted">{{ (trResult.answers || []).join(', ') || '—' }}</dd>
      </dl>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { get, post, put, delReq } from '../api.js'

const toast = inject('toast')
const tabs = [
  { id: 'mode', name: '接管' }, { id: 'rewrite', name: '重写' },
  { id: 'filter', name: '过滤' }, { id: 'query', name: '查询日志' },
  { id: 'test', name: '上游实测' }, { id: 'trace', name: '链路追踪' },
]
const tab = ref('mode')
const dns = ref({ mode: 'dnsmasq', region: 'auto', direct_dns: '', proxy_dns: '', rewrites: [] })
const rw = ref({ domain: '', answer: '' })
const wanInfo = ref('')
const filter = ref({ enabled: false, lists: [] })
const filterInfo = ref({})
const fl = ref({ name: '', url: '' })
const filterMsg = ref('')
const checkDom = ref(''), checkRes = ref(null)
const queries = ref([]), qFilter = ref(''), qNote = ref('')
const tu = ref({ upstream: '', domain: '' }), tuResult = ref(null), tuBusy = ref(false)
const trDomain = ref(''), trResult = ref(null), trBusy = ref(false)

const filteredQueries = computed(() => {
  const f = qFilter.value.trim().toLowerCase()
  if (!f) return queries.value.slice(0, 200)
  return queries.value.filter(q => (q.domain + q.client + (q.hostname || '')).toLowerCase().includes(f)).slice(0, 200)
})

async function load() {
  dns.value = await get('/api/dns')
  const flt = await get('/api/dns/filter')
  filter.value = { enabled: !!flt.enabled, lists: flt.lists || [] }
  filterInfo.value = flt
}
async function saveDns() {
  try { dns.value = await put('/api/dns', dns.value); toast('已保存') }
  catch (e) { toast(e.message) }
}
async function detectRegion() {
  try { const r = await post('/api/dns/detect-region', {}); toast('地区：' + r.region); load() }
  catch (e) { toast(e.message) }
}
async function getWan() {
  try { wanInfo.value = JSON.stringify(await get('/api/dns/wan'), null, 2) }
  catch (e) { toast(e.message) }
}
async function addRewrite() {
  try {
    await post('/api/dns/rewrite', rw.value)
    rw.value = { domain: '', answer: '' }; toast('已添加'); load()
  } catch (e) { toast(e.message) }
}
async function delRewrite(id) {
  try { await delReq('/api/dns/rewrite/' + id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
function addFilterList() {
  filter.value.lists.push({ name: fl.value.name.trim(), url: fl.value.url.trim(), enabled: true })
  fl.value = { name: '', url: '' }
}
async function saveFilter() {
  try {
    const r = await put('/api/dns/filter', filter.value)
    filter.value.lists = r.lists || filter.value.lists
    toast('已保存')
  } catch (e) { toast(e.message) }
}
async function applyFilter() {
  try {
    const r = await post('/api/dns/filter/apply', {})
    filterMsg.value = `已应用（${(r.lists || []).length} 个名单）`
    toast('已应用'); load()
  } catch (e) { toast(e.message) }
}
async function checkDomain() {
  try { checkRes.value = await get('/api/dns/filter/preview?domain=' + encodeURIComponent(checkDom.value)) }
  catch (e) { toast(e.message) }
}
async function loadQueryLog() {
  try {
    const r = await get('/api/dns/query-log')
    queries.value = r.queries || []
    qNote.value = r.note || ''
  } catch (e) { toast(e.message) }
}
async function testUpstream() {
  tuBusy.value = true; tuResult.value = null
  try { tuResult.value = await post('/api/dns/upstream-test', tu.value) }
  catch (e) { toast(e.message) }
  tuBusy.value = false
}
async function trace() {
  trBusy.value = true; trResult.value = null
  try { trResult.value = await post('/api/dns/trace', { domain: trDomain.value }) }
  catch (e) { toast(e.message) }
  trBusy.value = false
}

onMounted(load)
</script>
