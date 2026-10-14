<template>
  <div class="topbar"><h2>订阅</h2></div>

  <div v-for="s in subs" :key="s.id" class="card sub-card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <span class="muted">≡</span>
        <b>{{ s.name }}</b>
        <span class="muted">（{{ nodeHealth(s.id).ok }} / {{ s.node_total || s.node_count }}）</span>
        <span v-if="!s.enabled" class="pill warn">已禁用</span>
      </div>
      <div class="actions">
        <button class="icon" :class="{ on: s.enabled }" @click="toggleEnabled(s)" title="启用/禁用">⏻</button>
        <button class="icon" @click="testSub(s)" title="测速">⚡</button>
        <button class="icon" @click="s.urls?.length ? refresh(s) : openEdit(s)"
          :disabled="refreshing === s.id" :title="s.urls?.length ? '刷新' : '手动更新'">⟳</button>
        <button class="icon" @click="openEdit(s)" title="编辑">✎</button>
        <button class="icon danger" @click="delSub(s)" title="删除">🗑</button>
      </div>
    </div>
    <div class="muted" style="font-size:12px;margin:4px 0">
      更新于 {{ relTime(s.updated_at || s.created_at) }}
      <template v-if="s.auto_update_hours"> · 每 {{ s.auto_update_hours }} 小时自动更新</template>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <span v-for="d in nodeDots(s.id)" :key="d.tag" class="dot" :class="d.cls" :title="d.tag"></span>
        <span v-if="!nodeDots(s.id).length" class="muted" style="font-size:12px">无节点</span>
      </div>
      <div v-if="s.userinfo && s.userinfo.total" class="muted" style="font-size:12px;text-align:right">
        已用 {{ fmtBytes((s.userinfo.upload || 0) + (s.userinfo.download || 0)) }}
      </div>
    </div>
    <div v-if="s.userinfo && s.userinfo.total" style="margin-top:4px">
      <div class="progress" style="max-width:100%">
        <div :style="{ width: pct(s.userinfo) + '%' }"></div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>添加订阅</h3>
    <form @submit.prevent="create">
      <div class="form-row">
        <div><label>名称</label><input v-model="f.name" required></div>
        <div><label>格式</label><select v-model="f.format">
          <option value="auto">自动识别</option><option value="links">分享链接</option><option value="clash">Clash YAML</option>
        </select></div>
      </div>
      <label>订阅链接 URL（可选，一行一个，多个地址的节点会合并）</label>
      <textarea v-model="f.url" rows="2" placeholder="https://…"></textarea>
      <label style="margin-top:8px">订阅内容（粘贴 base64 订阅 / 链接列表 / Clash YAML）</label>
      <textarea v-model="f.content" rows="6"></textarea>
      <div style="margin-top:8px"><button>解析并导入</button></div>
    </form>
  </div>

  <div class="card">
    <h3>订阅分享 <span class="muted">生成可供其他设备或代理软件直接使用的订阅链接</span></h3>
    <table v-if="shares.length">
      <tr><th>名称</th><th>公开链接</th><th>过滤</th><th></th></tr>
      <tr v-for="s in shares" :key="s.id">
        <td>{{ s.name }}</td>
        <td><input readonly :value="shareUrl(s)" size="42" @click="$event.target.select()">
          <button class="small" @click="copy(shareUrl(s))">复制</button></td>
        <td class="muted">{{ s.node_filter || '全部' }}</td>
        <td>
          <button class="small ghost" @click="regen(s)">换链接</button>
          <button class="small danger" @click="delShare(s)">删除</button>
        </td>
      </tr>
    </table>
    <p v-else class="muted">暂无订阅分享，点击右上角「添加」创建</p>
    <form @submit.prevent="createShare" style="margin-top:12px">
      <h3>新建分享</h3>
      <div class="form-row">
        <div><label>名称</label><input v-model="sf.name" required></div>
        <div><label>节点过滤（标签逗号分隔，空=全部）</label><input v-model="sf.filter"></div>
      </div>
      <div><button class="small">创建分享</button></div>
    </form>
  </div>

  <!-- edit dialog -->
  <div v-if="editing" class="modal-mask" @click.self="closeEdit">
    <div class="modal">
      <div class="modal-head">
        <b>修改订阅</b>
        <div class="tabs small-tabs">
          <button v-for="t in editTabs" :key="t.id" :class="{ active: editTab === t.id }"
            @click="editTab = t.id">{{ t.name }}</button>
        </div>
        <button class="icon" @click="closeEdit">✕</button>
      </div>

      <!-- tab: subscription -->
      <div v-if="editTab === 'sub'">
        <label>名称</label>
        <input v-model="ef.name">
        <label style="margin-top:10px">订阅链接
          <button type="button" class="small ghost" @click="ef.urls.push('')">+ 添加订阅</button></label>
        <div v-for="(u, i) in ef.urls" :key="i" style="display:flex;gap:8px;margin-bottom:6px">
          <input v-model="ef.urls[i]" placeholder="http(s)://…" style="flex:1">
          <button type="button" class="small danger" @click="ef.urls.splice(i, 1)">🗑</button>
        </div>
        <p class="muted" style="font-size:12px">一行一个，多个地址的节点会合并；支持内网 / 本地地址，不校验 https 证书。</p>
        <div class="form-row" style="margin-top:10px">
          <div><label>定期更新</label>
            <div><input type="checkbox" v-model="ef.autoUpdate" style="width:auto">
              <input v-model.number="ef.auto_update_hours" type="number" min="0" style="width:70px" :disabled="!ef.autoUpdate">
              <span class="muted">小时（0=关闭）</span></div></div>
          <div><label>订阅 DNS 解析</label><select v-model="ef.dns_resolve">
            <option value="auto">自动</option><option value="direct">直连</option><option value="proxy">代理</option>
          </select></div>
        </div>
        <div style="margin-top:14px;border-top:1px solid rgba(255,255,255,.08);padding-top:12px">
          <b>手动更新节点</b>
          <p class="muted" style="font-size:12px">粘贴新的订阅内容，直接替换当前节点（保留改名/禁用设置）。无订阅链接时用这个更新。</p>
          <textarea v-model="manualContent" rows="4" placeholder="粘贴 base64 订阅 / 链接列表 / Clash YAML"></textarea>
          <div style="margin-top:8px">
            <button type="button" class="small" @click="doReimport" :disabled="!manualContent.trim() || reimporting">
              {{ reimporting ? '导入中…' : '手动更新节点' }}</button>
          </div>
        </div>
      </div>

      <!-- tab: rename rules -->
      <div v-if="editTab === 'rule'">
        <label><input type="checkbox" v-model="ef.rename.prefix" style="width:auto">
          节点名前加订阅名（如「{{ ef.name }} | 香港-01」）</label>
        <div style="display:flex;justify-content:space-between;align-items:center;margin:10px 0">
          <b>重命名规则</b>
          <div>
            <input type="checkbox" v-model="ef.rename.enabled" style="width:auto"> 启用
            <button type="button" class="small ghost" @click="resetRename">⟲ 重置</button>
          </div>
        </div>
        <div class="muted" style="font-size:12px">拖拽排序：
          <span v-for="(slot, i) in ef.rename.order" :key="slot" class="order-chip">
            {{ slotName(slot) }}
            <button type="button" @click="moveSlot(i, -1)" :disabled="i === 0">↑</button>
            <button type="button" @click="moveSlot(i, 1)" :disabled="i === ef.rename.order.length - 1">↓</button>
          </span>
          <span style="margin-left:12px">序号位数：<input v-model.number="ef.rename.seq_digits"
            type="number" min="1" max="4" style="width:56px"></span>
        </div>
        <p class="muted" style="font-size:12px">效果：{{ renamePreview }}</p>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px">
          <b>地区关键词</b>
          <button type="button" class="small ghost" @click="addRegion">+ 新增</button>
        </div>
        <p class="muted" style="font-size:12px">按原始节点名匹配（不区分大小写）。</p>
        <div v-for="(r, i) in ef.rename.regions" :key="i" class="region-row">
          <span class="muted">≡</span>
          <input v-model="r.flag" placeholder="🇺🇸" style="width:52px">
          <input v-model="r.name" placeholder="地区名" style="width:90px">
          <input v-model="r.keywords" placeholder="关键词，逗号分隔" style="flex:1">
          <button type="button" class="small danger" @click="ef.rename.regions.splice(i, 1)">✕</button>
        </div>
        <label style="margin-top:10px">无法识别地区时的标签</label>
        <input v-model="ef.rename.fallback" style="max-width:200px">
        <label style="margin-top:10px">特征关键词
          <span class="muted">命中的关键词转成大写拼进节点名</span></label>
        <input v-model="ef.rename.features" placeholder="iepl,iplc,ipv6,专线,家宽,2x">
        <label style="margin-top:10px">过滤节点
          <span class="muted">原始节点命名中夹关键词的整条不导入</span></label>
        <input v-model="ef.rename.filter" placeholder="官网,工单,客服">
      </div>

      <!-- tab: nodes -->
      <div v-if="editTab === 'node'">
        <p>解析出 {{ subNodes.length }} 个节点
          <span class="muted">已应用重命名规则，可单独改名 / 禁用</span></p>
        <div class="tabs small-tabs" style="margin:8px 0">
          <button :class="{ active: nodeTab === 'ok' }" @click="nodeTab = 'ok'">有效（{{ okNodes.length }}）</button>
          <button :class="{ active: nodeTab === 'off' }" @click="nodeTab = 'off'">禁用（{{ offNodes.length }}）</button>
        </div>
        <div style="margin-bottom:8px">
          <button type="button" class="small ghost" @click="resetNames">⟲ 恢复默认名称</button>
          <button type="button" class="small ghost" @click="testAllNodes" :disabled="testingAll">
            ⚡ {{ testingAll ? '测速中…' : '一键测速' }}</button>
        </div>
        <table>
          <tr><th>原名</th><th></th><th>新名</th><th>延迟</th><th></th></tr>
          <tr v-for="n in shownNodes" :key="n.id">
            <td class="muted">{{ n.orig_tag || n.tag }}</td>
            <td class="muted">→</td>
            <td><input v-model="n._editTag" @change="saveNodeTag(n)" style="min-width:180px"></td>
            <td class="muted" style="font-size:12px">{{ nodeLatency(n.tag) }}</td>
            <td style="white-space:nowrap">
              <button class="icon" @click="testNode(n)" title="测速">⚡</button>
              <button class="icon" :class="{ danger: !n.disabled }" @click="toggleNode(n)"
                :title="n.disabled ? '启用' : '禁用'">{{ n.disabled ? '⏻' : '⊘' }}</button>
            </td>
          </tr>
        </table>
      </div>

      <div class="modal-foot">
        <button class="ghost" @click="closeEdit">取消</button>
        <button @click="saveEdit">保存</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { get, post, put, delReq, fmtBytes } from '../api.js'

const toast = inject('toast')
const subs = ref([]), shares = ref([]), nodes = ref([]), health = ref([])
const f = ref({ name: '', format: 'auto', url: '', content: '' })
const sf = ref({ name: '', filter: '' })
const refreshing = ref(null)
const editing = ref(null), editTab = ref('sub'), nodeTab = ref('ok')
const editTabs = [{ id: 'sub', name: '订阅' }, { id: 'rule', name: '规则' }, { id: 'node', name: '节点' }]
const ef = ref(null)
const testingAll = ref(false)
const manualContent = ref('')
const reimporting = ref(false)

const shareUrl = s => location.origin + '/sub/' + s.token
const slotName = s => ({ region: '地区', feature: '特征', seq: '序号' }[s] || s)

function relTime(t) {
  if (!t) return '—'
  const d = Math.floor((Date.now() - new Date(t).getTime()) / 86400000)
  return d <= 0 ? '今天' : d + ' 天前'
}
function nodeHealth(sid) {
  const ns = nodes.value.filter(n => n.sub_id === sid && !n.disabled)
  const hm = Object.fromEntries(health.value.map(h => [h.tag, h]))
  const ok = ns.filter(n => hm[n.tag]?.ok).length
  return { ok, total: ns.length }
}
function nodeDots(sid) {
  const ns = nodes.value.filter(n => n.sub_id === sid)
  const hm = Object.fromEntries(health.value.map(h => [h.tag, h]))
  return ns.map(n => {
    const h = hm[n.tag]
    return { tag: n.tag, cls: !h ? '' : h.ok ? 'ok' : 'bad' }
  })
}
function pct(ui) {
  const used = (ui.upload || 0) + (ui.download || 0)
  return ui.total ? Math.min(100, Math.round(used / ui.total * 100)) : 0
}
function nodeLatency(tag) {
  const h = health.value.find(x => x.tag === tag)
  if (!h) return '未测速'
  return h.ok ? (h.latency_ms != null ? h.latency_ms + ' ms' : '正常') : '异常'
}

const subNodes = computed(() =>
  editing.value ? nodes.value.filter(n => n.sub_id === editing.value) : [])
const okNodes = computed(() => subNodes.value.filter(n => !n.disabled))
const offNodes = computed(() => subNodes.value.filter(n => n.disabled))
const shownNodes = computed(() => nodeTab.value === 'ok' ? okNodes.value : offNodes.value)

const renamePreview = computed(() => {
  if (!ef.value) return ''
  const r = ef.value.rename
  const parts = []
  for (const s of r.order) {
    if (s === 'region') parts.push('美国')
    else if (s === 'feature') parts.push('专线')
    else if (s === 'seq') parts.push('1'.padStart(r.seq_digits || 2, '0'))
  }
  const name = parts.join('-')
  return (r.prefix ? ef.value.name + ' | ' : '') + name
})

async function load() {
  const [s, n, h] = await Promise.all([
    get('/api/subscriptions'), get('/api/nodes'), get('/api/health'),
  ])
  subs.value = s
  nodes.value = n.map(x => ({ ...x, _editTag: x.tag }))
  health.value = h
  shares.value = await get('/api/subscription-shares').catch(() => [])
}
async function create() {
  const urls = f.value.url.split('\n').map(x => x.trim()).filter(Boolean)
  const body = { name: f.value.name.trim(), content: f.value.content,
    format: f.value.format }
  if (urls.length) body.urls = urls
  else if (!f.value.content.trim()) { toast('请填写订阅链接或订阅内容'); return }
  try {
    const r = await post('/api/subscriptions', body)
    toast(`已导入 ${r.node_count} 个节点` + (r.filtered_count ? `（过滤 ${r.filtered_count}）` : ''))
    f.value = { name: '', format: 'auto', url: '', content: '' }; load()
  } catch (e) { toast(e.message) }
}
async function delSub(s) {
  if (!confirm('删除该订阅及其节点？')) return
  try { await delReq('/api/subscriptions/' + s.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function refresh(s) {
  refreshing.value = s.id
  try {
    const r = await post(`/api/subscriptions/${s.id}/refresh`, {})
    toast(`已刷新：${r.node_count} 个节点` + (r.filtered_count ? `（过滤 ${r.filtered_count}）` : ''))
    load()
  } catch (e) { toast(e.message) }
  refreshing.value = null
}
async function toggleEnabled(s) {
  try { await put('/api/subscriptions/' + s.id, { enabled: !s.enabled }); load() }
  catch (e) { toast(e.message) }
}
async function testSub(s) {
  toast('开始测速…')
  try {
    await post('/api/health/check', { sub_id: s.id })
    toast('测速完成'); load()
  } catch (e) { toast(e.message) }
}

function openEdit(s) {
  editing.value = s.id
  editTab.value = 'sub'
  nodeTab.value = 'ok'
  manualContent.value = ''
  ef.value = {
    name: s.name,
    urls: [...(s.urls || [])],
    autoUpdate: (s.auto_update_hours || 0) > 0,
    auto_update_hours: s.auto_update_hours || 0,
    dns_resolve: s.dns_resolve || 'auto',
    rename: JSON.parse(JSON.stringify(s.rename || {})),
  }
  if (!ef.value.rename.regions?.length) {
    ef.value.rename.regions = []
  }
}
function closeEdit() { editing.value = null; ef.value = null }
function resetRename() {
  ef.value.rename = { enabled: true, prefix: true, order: ['region', 'feature', 'seq'],
    seq_digits: 2, regions: [], fallback: '其他', features: '', filter: '' }
  toast('已重置为空，可重新添加地区关键词')
}
function moveSlot(i, dir) {
  const o = ef.value.rename.order
  const j = i + dir
  if (j < 0 || j >= o.length) return
  ;[o[i], o[j]] = [o[j], o[i]]
}
function addRegion() {
  ef.value.rename.regions.push({ name: '', flag: '', keywords: '' })
}
async function saveEdit() {
  const body = {
    name: ef.value.name,
    urls: ef.value.urls.map(u => u.trim()).filter(Boolean),
    auto_update_hours: ef.value.autoUpdate ? (ef.value.auto_update_hours || 0) : 0,
    dns_resolve: ef.value.dns_resolve,
    rename: ef.value.rename,
  }
  try {
    await put('/api/subscriptions/' + editing.value, body)
    toast('已保存'); closeEdit(); load()
  } catch (e) { toast(e.message) }
}
async function saveNodeTag(n) {
  const v = (n._editTag || '').trim()
  if (!v || v === n.tag) { n._editTag = n.tag; return }
  try {
    await put('/api/nodes/' + n.id, { custom_tag: v })
    toast('已改名'); load()
  } catch (e) { toast(e.message); n._editTag = n.tag }
}
async function toggleNode(n) {
  try {
    await put('/api/nodes/' + n.id, { disabled: !n.disabled })
    load()
  } catch (e) { toast(e.message) }
}
async function resetNames() {
  if (!confirm('恢复所有节点为重命名规则生成的默认名称？')) return
  try {
    for (const n of subNodes.value) {
      if (n.custom_tag) await put('/api/nodes/' + n.id, { custom_tag: '' })
    }
    toast('已恢复'); load()
  } catch (e) { toast(e.message) }
}
async function testNode(n) {
  try {
    await post('/api/health/check', { tag: n.tag })
    const h = await get('/api/health')
    health.value = h
  } catch (e) { toast(e.message) }
}
async function testAllNodes() {
  testingAll.value = true
  try {
    await post('/api/health/check', { sub_id: editing.value })
    const h = await get('/api/health')
    health.value = h
    toast('测速完成')
  } catch (e) { toast(e.message) }
  testingAll.value = false
}
async function doReimport() {
  reimporting.value = true
  try {
    const r = await post(`/api/subscriptions/${editing.value}/reimport`,
      { content: manualContent.value })
    toast(`已更新：${r.node_count} 个节点` + (r.filtered_count ? `（过滤 ${r.filtered_count}）` : ''))
    manualContent.value = ''
    load()
  } catch (e) { toast(e.message) }
  reimporting.value = false
}

async function createShare() {
  try {
    await post('/api/subscription-shares', { name: sf.value.name.trim(), node_filter: sf.value.filter.trim() })
    toast('已创建'); sf.value = { name: '', filter: '' }; load()
  } catch (e) { toast(e.message) }
}
async function regen(s) {
  if (!confirm('更换链接？旧链接将失效。')) return
  try { await post(`/api/subscription-shares/${s.id}/regenerate`, {}); toast('已更换'); load() }
  catch (e) { toast(e.message) }
}
async function delShare(s) {
  if (!confirm('删除该分享？')) return
  try { await delReq('/api/subscription-shares/' + s.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function copy(t) {
  try { await navigator.clipboard.writeText(t); toast('已复制') }
  catch (e) { toast('复制失败') }
}

onMounted(load)
</script>

<style scoped>
.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #5a6a8a; margin: 2px; }
.dot.ok { background: #38c172; }
.dot.bad { background: #e5534b; }
.sub-card .actions { display: flex; gap: 4px; }
.icon { background: none; border: none; cursor: pointer; font-size: 16px; padding: 4px 6px; border-radius: 6px; color: #8a93a8; }
.icon:hover { background: rgba(255,255,255,.08); color: #fff; }
.icon.on { color: #38c172; }
.icon.danger { color: #e5534b; }
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex;
  align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal { background: #1c2230; border-radius: 12px; width: 720px; max-width: 100%;
  max-height: 90vh; overflow-y: auto; padding: 20px 24px; }
.modal-head { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,.08); padding-bottom: 12px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;
  border-top: 1px solid rgba(255,255,255,.08); padding-top: 14px; }
.small-tabs button { font-size: 13px; padding: 5px 14px; }
.order-chip { display: inline-block; background: rgba(255,255,255,.06); border-radius: 6px;
  padding: 3px 4px 3px 10px; margin: 0 4px; }
.order-chip button { background: none; border: none; color: #8a93a8; cursor: pointer; padding: 0 4px; }
.region-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
</style>
