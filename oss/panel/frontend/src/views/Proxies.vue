<template>
  <div class="topbar">
    <h2>代理</h2>
    <div>
      <button class="small" @click="checkHealth" :disabled="busy">{{ busy ? '检查中…' : '检查健康' }}</button>
      <button class="small ghost" @click="syncLatency">从内核同步延迟</button>
      <span class="muted">TCP 连通 + TLS 握手延迟；UDP 协议会标记为跳过</span>
    </div>
  </div>

  <div class="card">
    <h3>节点（{{ nodes.length }}）</h3>
    <table>
      <tr><th></th><th>标签</th><th>协议</th><th>服务器</th><th>健康</th><th>延迟历史</th><th></th></tr>
      <tr v-for="n in nodes" :key="n.tag">
        <td><input type="checkbox" :value="n.tag" v-model="selected"></td>
        <td>{{ n.tag }}</td><td>{{ n.protocol }}</td>
        <td class="muted">{{ n.server }}:{{ n.port }}</td>
        <td><span v-if="hm[n.tag]" :class="['pill', hm[n.tag].ok ? 'ok' : 'bad']">
          {{ hm[n.tag].ok ? '正常' : '异常' }}</span><span v-else class="muted">—</span></td>
        <td class="muted">{{ lastLat(n.tag) }}</td>
        <td><button class="small ghost" @click="showNodeInfo(n.tag)">出口信息</button></td>
      </tr>
    </table>
    <div style="margin-top:10px">
      <button @click="genShare">生成分享链接</button>
      <span class="muted">勾选节点后生成 vmess/vless/trojan/ss 链接 + 二维码</span>
    </div>
    <div v-if="shareResult.length" style="margin-top:10px">
      <div v-for="it in shareResult" :key="it.tag" class="card">
        <b>{{ it.tag }}</b>
        <template v-if="it.link">
          <textarea rows="3" readonly :value="it.link"></textarea>
          <div><button class="small" @click="copy(it.link)">复制链接</button></div>
          <img :src="'/api/share/qr?text=' + encodeURIComponent(it.link)" alt="QR"
               style="width:160px;height:160px;background:#fff;padding:8px;border-radius:8px">
        </template>
        <span v-else class="pill bad">{{ it.error }}</span>
      </div>
    </div>
  </div>

  <div v-if="nodeInfo" class="card">
    <h3>{{ nodeInfo.tag }} 出口信息
      <span v-if="nodeInfo.cached" class="muted">（缓存）</span></h3>
    <div v-if="nodeInfo.ip">
      <dl class="kv">
        <dt>出口 IP</dt><dd>{{ nodeInfo.ip }}</dd>
        <dt>国家</dt><dd>{{ nodeInfo.country || '—' }}</dd>
        <dt>地区</dt><dd>{{ nodeInfo.region || '—' }}</dd>
        <dt>城市</dt><dd>{{ nodeInfo.city || '—' }}</dd>
        <dt>ISP</dt><dd>{{ nodeInfo.isp || '—' }}</dd>
        <dt>ASN</dt><dd>{{ nodeInfo.asn || '—' }}</dd>
        <dt>协议</dt><dd>{{ nodeInfo.proxy_type || '—' }}</dd>
      </dl>
      <div style="margin-top:8px">
        <button class="small ghost" @click="refreshNodeInfo(nodeInfo.tag)" :disabled="niBusy">
          {{ niBusy ? '探测中…' : '刷新（经该节点实测）' }}</button>
        <button class="small ghost" @click="entryCountry(nodeInfo.tag)">入口 IP 国家</button>
        <span class="muted">{{ entryText }}</span>
      </div>
    </div>
    <div v-else>
      <p class="muted">暂无缓存</p>
      <button class="small ghost" @click="refreshNodeInfo(nodeInfo.tag)" :disabled="niBusy">
        {{ niBusy ? '探测中（约 10-20 秒）…' : '经该节点实测' }}</button>
    </div>
  </div>

  <div class="card">
    <h3>节点组</h3>
    <div class="grid c2">
      <div v-for="g in groups" :key="g.id" class="card" style="margin:0">
        <div><b>{{ g.name }}</b> <span class="muted">{{ g.type }}</span></div>
        <div class="muted">成员: {{ g.members.length ? g.members.join(', ') : '—' }}</div>
        <div class="muted">关键词: {{ g.dynamic_keywords.length ? g.dynamic_keywords.join(', ') : '—' }}</div>
        <div><button class="small danger" @click="delGroup(g.id)">删除</button></div>
      </div>
    </div>
    <form @submit.prevent="createGroup" style="margin-top:12px">
      <h3>新建节点组</h3>
      <div class="form-row">
        <div><label>名称</label><input v-model="gf.name" required></div>
        <div><label>类型</label><select v-model="gf.type">
          <option value="urltest">自动择优 (urltest)</option>
          <option value="selector">手动选择 (selector)</option>
          <option value="failover">故障转移 (failover)</option>
        </select></div>
      </div>
      <label>成员标签（逗号分隔；*nodes* = 全部节点，*all* = 节点+链式代理）</label>
      <input v-model="gf.members" placeholder="*nodes*">
      <label style="margin-top:8px">动态关键词（逗号分隔，标签含关键词自动收编）</label>
      <input v-model="gf.keywords" placeholder="香港, HK">
      <div style="margin-top:8px"><button class="small">创建</button></div>
    </form>
  </div>

  <div class="card">
    <h3>故障转移状态</h3>
    <div v-if="failover.length" class="grid c2">
      <div v-for="g in failover" :key="g.group" class="card" style="margin:0">
        <div><b>{{ g.group }}</b>
          <span :class="['pill', g.current ? 'ok' : '']">{{ g.current ? '当前: ' + g.current : '未运行' }}</span></div>
        <div class="muted">主用: {{ g.primary || '—' }} · 最近切换: {{ g.last_switch_at || '无' }}</div>
        <div class="muted">成员: {{ g.members.map(m => m.tag + (m.health === true ? '✓' : m.health === false ? '✗' : '?')).join(' ') }}</div>
        <div><button class="small ghost" @click="recheck(g.group)">强制重测该组</button></div>
      </div>
    </div>
    <p v-else class="muted">暂无故障转移组（新建组时类型选 failover）</p>
    <div style="margin-top:8px"><button class="small ghost" @click="refreshFailover">立即重选全部</button></div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, delReq } from '../api.js'

const toast = inject('toast')
const nodes = ref([]), groups = ref([])
const hm = ref({}), latHist = ref({})
const selected = ref([]), shareResult = ref([])
const busy = ref(false)
const failover = ref([])
const nodeInfo = ref(null), niBusy = ref(false), entryText = ref('')
const gf = ref({ name: '', type: 'urltest', members: '', keywords: '' })

function lastLat(tag) {
  const h = (latHist.value[tag] || []).filter(x => x.ok && x.latency_ms != null)
  return h.length ? Math.round(h[h.length - 1].latency_ms) + ' ms' : '—'
}

async function load() {
  const [n, h, g, lh] = await Promise.all([
    get('/api/nodes'), get('/api/health'), get('/api/groups'),
    get('/api/latency/history').catch(() => ({})),
  ])
  nodes.value = n
  hm.value = Object.fromEntries(h.map(x => [x.tag, x]))
  groups.value = g; latHist.value = lh
  failover.value = await get('/api/failover/status').catch(() => [])
}

async function checkHealth() {
  busy.value = true
  try { await post('/api/health/check', {}); toast('检查完成'); load() }
  catch (e) { toast(e.message) }
  busy.value = false
}
async function syncLatency() {
  try {
    const r = await post('/api/latency/history/sync', {})
    const samples = Object.values(hm.value).filter(h => h.latency_ms != null)
      .map(h => ({ tag: h.tag, ok: !!h.ok, latency_ms: h.latency_ms }))
    if (samples.length) await post('/api/latency/history/samples', { samples })
    toast(`已同步 ${r.synced} 条内核延迟`); load()
  } catch (e) { toast(e.message) }
}
async function genShare() {
  if (!selected.value.length) { toast('请先勾选节点'); return }
  try { shareResult.value = await post('/api/share', { node_tags: selected.value }) }
  catch (e) { toast(e.message) }
}
async function copy(t) {
  try { await navigator.clipboard.writeText(t); toast('已复制') }
  catch (e) { toast('复制失败') }
}
async function delGroup(id) {
  if (!confirm('删除该组？')) return
  try { await delReq('/api/groups/' + id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function createGroup() {
  const split = s => s.split(',').map(x => x.trim()).filter(Boolean)
  try {
    await post('/api/groups', { name: gf.value.name, type: gf.value.type,
      members: split(gf.value.members), dynamic_keywords: split(gf.value.keywords) })
    toast('已创建'); gf.value = { name: '', type: 'urltest', members: '', keywords: '' }; load()
  } catch (e) { toast(e.message) }
}
async function refreshFailover() {
  try { await post('/api/failover/refresh', {}); toast('已重选'); load() }
  catch (e) { toast(e.message) }
}
async function recheck(group) {
  try { await post('/api/failover/recheck', { group }); toast('已重测'); load() }
  catch (e) { toast(e.message) }
}
async function showNodeInfo(tag) {
  entryText.value = ''
  try { nodeInfo.value = { tag, ...await get('/api/node-info/' + encodeURIComponent(tag)) } }
  catch (e) { nodeInfo.value = { tag } }
}
async function refreshNodeInfo(tag) {
  niBusy.value = true
  try {
    const r = await post('/api/node-info/' + encodeURIComponent(tag) + '/exit', {})
    if (r.error) toast(r.error); else toast('已刷新')
  } catch (e) { toast(e.message) }
  niBusy.value = false
  showNodeInfo(tag)
}
async function entryCountry(tag) {
  try {
    const r = await get('/api/node-info/' + encodeURIComponent(tag) + '/entry-country')
    entryText.value = r.ok ? `入口 ${r.ip} · ${r.country}` : '失败：' + (r.error || '')
  } catch (e) { toast(e.message) }
}

onMounted(load)
</script>
