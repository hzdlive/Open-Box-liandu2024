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
    <div style="margin-bottom:8px;display:flex;gap:8px;align-items:center">
      <input v-model="nodeFilter" placeholder="搜索标签 / 服务器" style="max-width:240px">
      <span class="muted">{{ filteredNodes.length }} / {{ nodes.length }}</span>
    </div>
    <table>
      <tr><th></th><th>标签</th><th>协议</th><th>服务器</th><th>健康</th><th>延迟</th><th></th></tr>
      <tr v-for="n in filteredNodes" :key="n.tag">
        <td><input type="checkbox" :value="n.tag" v-model="selected"></td>
        <td>{{ n.tag }}</td><td>{{ n.protocol }}</td>
        <td class="muted">{{ n.server }}:{{ n.port }}</td>
        <td><span v-if="hm[n.tag]" :class="['pill', hm[n.tag].ok ? 'ok' : 'bad']">
          {{ hm[n.tag].ok ? '正常' : '异常' }}</span><span v-else class="muted">—</span></td>
        <td class="muted">{{ lastLat(n.tag) }}</td>
        <td style="white-space:nowrap">
          <button class="small ghost" @click="testOne(n.tag)" :disabled="testing === n.tag">
            {{ testing === n.tag ? '测速中…' : '测速' }}</button>
          <button class="small ghost" @click="showNodeInfo(n.tag)">出口信息</button>
          <button class="small danger" @click="delNode(n)">删除</button>
        </td>
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
    <h3>手动添加节点</h3>
    <form @submit.prevent="addManualNode">
      <label>粘贴分享链接 <span class="muted">vmess / vless / trojan / ss / tuic / hysteria2，一行一个</span></label>
      <textarea v-model="manualLinks" rows="3" placeholder="vless://…"></textarea>
      <div style="margin-top:8px"><button class="small" :disabled="addingNode">
        {{ addingNode ? '添加中…' : '添加' }}</button></div>
    </form>
  </div>

  <div class="card">
    <h3>节点组</h3>
    <div v-for="g in sortedGroups" :key="g.id" class="card" style="margin:0 0 8px 0">
      <div style="display:flex;align-items:center;gap:10px">
        <span v-if="!g.builtin" class="muted" style="cursor:ns-resize;user-select:none"
              title="拖动排序">≡</span>
        <div style="flex:1">
          <div><b>{{ g.builtin ? (g.name === 'direct' ? '直连' : '拒绝') : g.name }}</b>
            <span class="pill">{{ g.builtin ? '内置' : typeName(g.type) + ' (' + g.type + ')' }}</span>
            <span v-if="!g.enabled && !g.builtin" class="pill warn">已禁用</span>
          </div>
          <div v-if="g.builtin" class="muted">{{ g.detail }}</div>
          <div v-else class="muted" style="font-size:12px">
            <template v-if="g.type === 'urltest'">{{ g.member_count }} 个成员 · 检测间隔 {{ g.interval_s }}s · 容差 {{ g.tolerance_ms }}ms</template>
            <template v-else-if="g.type === 'failover'">{{ g.member_count }} 个节点 · 检测间隔 {{ g.interval_s }}s · 容差 {{ g.tolerance_ms }}ms</template>
            <template v-else>{{ g.dynamic ? '动态组 · ' : '' }}当前 {{ g.member_count }} 个节点</template>
            <button class="small ghost" @click="toggleMembers(g)" style="margin-left:6px">
              {{ expandedGroup === g.id ? '收起成员' : '查看成员' }}</button>
          </div>
          <div v-if="expandedGroup === g.id" class="muted" style="font-size:12px;margin-top:4px;max-height:120px;overflow-y:auto">
            {{ groupMembers.join(', ') || '无成员' }}
          </div>
          <div v-if="!g.builtin && g.dynamic_keywords.length" class="muted" style="font-size:12px">
            关键词: {{ g.dynamic_keywords.join(', ') }}</div>
        </div>
        <div style="white-space:nowrap">
          <button v-if="!g.builtin" class="small ghost" @click="moveGroup(g, -1)" title="上移">↑</button>
          <button v-if="!g.builtin" class="small ghost" @click="moveGroup(g, 1)" title="下移">↓</button>
          <button class="small ghost" @click="g.builtin ? null : toggleGroup(g)"
                  :title="g.enabled ? '禁用' : '启用'">{{ g.enabled ? '⏻' : '○' }}</button>
          <button v-if="!g.builtin" class="small ghost" @click="editGroup(g)" title="编辑">✎</button>
          <button v-if="!g.builtin" class="small danger" @click="delGroup(g.id)" title="删除">🗑</button>
        </div>
      </div>
    </div>
    <form @submit.prevent="createGroup" style="margin-top:12px">
      <h3>{{ editingGroup ? '编辑节点组' : '新建节点组' }}</h3>
      <div class="form-row">
        <div><label>名称</label><input v-model="gf.name" required :disabled="!!editingGroup"></div>
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
      <div class="form-row" style="margin-top:8px">
        <div><label>检测间隔（秒，urltest）</label><input v-model.number="gf.interval_s" type="number" min="30"></div>
        <div><label>容差（毫秒，urltest）</label><input v-model.number="gf.tolerance_ms" type="number" min="0"></div>
      </div>
      <div style="margin-top:8px">
        <button class="small">{{ editingGroup ? '保存' : '创建' }}</button>
        <button v-if="editingGroup" type="button" class="small ghost" @click="resetGroupForm">取消</button>
      </div>
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
import { ref, computed, onMounted, inject } from 'vue'
import { get, post, put, delReq } from '../api.js'

const toast = inject('toast')
const nodes = ref([]), groups = ref([])
const hm = ref({}), latHist = ref({})
const selected = ref([]), shareResult = ref([])
const busy = ref(false), testing = ref(null)
const failover = ref([])
const nodeInfo = ref(null), niBusy = ref(false), entryText = ref('')
const nodeFilter = ref('')
const manualLinks = ref(''), addingNode = ref(false)
const expandedGroup = ref(null), groupMembers = ref([])
const gf = ref({ name: '', type: 'urltest', members: '', keywords: '', interval_s: 300, tolerance_ms: 100 })
const editingGroup = ref(null)
const typeName = t => ({ urltest: '自动择优', selector: '手动选择', failover: '故障转移', builtin: '内置' }[t] || t)

const filteredNodes = computed(() => {
  const f = nodeFilter.value.trim().toLowerCase()
  if (!f) return nodes.value
  return nodes.value.filter(n => (n.tag + n.server + n.protocol).toLowerCase().includes(f))
})

const sortedGroups = computed(() =>
  [...groups.value].sort((a, b) => (a.builtin ? 1 : 0) - (b.builtin ? 1 : 0)
    || (a.position ?? 0) - (b.position ?? 0)))

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
  const body = { name: gf.value.name, type: gf.value.type,
    members: split(gf.value.members), dynamic_keywords: split(gf.value.keywords),
    interval_s: gf.value.interval_s, tolerance_ms: gf.value.tolerance_ms }
  try {
    if (editingGroup.value) {
      await put('/api/groups/' + editingGroup.value, body)
      toast('已保存')
    } else {
      await post('/api/groups', body)
      toast('已创建')
    }
    resetGroupForm(); load()
  } catch (e) { toast(e.message) }
}
function resetGroupForm() {
  editingGroup.value = null
  gf.value = { name: '', type: 'urltest', members: '', keywords: '', interval_s: 300, tolerance_ms: 100 }
}
function editGroup(g) {
  editingGroup.value = g.id
  gf.value = { name: g.name, type: g.type, members: (g.members || []).join(', '),
    keywords: (g.dynamic_keywords || []).join(', '),
    interval_s: g.interval_s || 300, tolerance_ms: g.tolerance_ms || 100 }
}
async function toggleGroup(g) {
  try { await put('/api/groups/' + g.id, { enabled: !g.enabled }); load() }
  catch (e) { toast(e.message) }
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
async function testOne(tag) {
  testing.value = tag
  try {
    await post('/api/health/check', { tag })
    const h = await get('/api/health')
    hm.value = Object.fromEntries(h.map(x => [x.tag, x]))
    const r = hm.value[tag]
    toast(r?.ok ? `${tag}: ${r.latency_ms ?? '—'} ms` : `${tag}: 异常`)
  } catch (e) { toast(e.message) }
  testing.value = null
}
async function delNode(n) {
  if (!confirm(`删除节点 ${n.tag}？`)) return
  try { await delReq('/api/nodes/' + n.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function addManualNode() {
  if (!manualLinks.value.trim()) return
  addingNode.value = true
  try {
    const r = await post('/api/nodes', { content: manualLinks.value })
    toast(`已添加 ${r.node_count} 个节点到「手动节点」`)
    manualLinks.value = ''; load()
  } catch (e) { toast(e.message) }
  addingNode.value = false
}
async function toggleMembers(g) {
  if (expandedGroup.value === g.id) { expandedGroup.value = null; return }
  try {
    const r = await get('/api/groups/' + g.id + '/members')
    groupMembers.value = r.members || []
    expandedGroup.value = g.id
  } catch (e) { toast(e.message) }
}
async function moveGroup(g, dir) {
  const order = sortedGroups.value.filter(x => !x.builtin)
  const i = order.findIndex(x => x.id === g.id)
  const j = i + dir
  if (j < 0 || j >= order.length) return
  const ids = order.map(x => x.id)
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  try { await post('/api/groups/reorder', { ids }); load() }
  catch (e) { toast(e.message) }
}

onMounted(load)
</script>
