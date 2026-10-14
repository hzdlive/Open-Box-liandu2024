<template>
  <div class="topbar"><h2>订阅</h2></div>

  <div v-for="s in subs" :key="s.id" class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <b>{{ s.name }}</b>
        <span class="muted">（{{ nodeHealth(s.id).ok }} / {{ nodeHealth(s.id).total }}）</span>
        <span v-if="!s.enabled" class="pill warn">已禁用</span>
      </div>
      <div>
        <button class="small ghost" @click="toggleEnabled(s)">{{ s.enabled ? '禁用' : '启用' }}</button>
        <button v-if="s.url" class="small ghost" @click="refresh(s)" :disabled="refreshing === s.id">
          {{ refreshing === s.id ? '刷新中…' : '刷新' }}</button>
        <button class="small ghost" @click="editSub(s)">编辑</button>
        <button class="small danger" @click="delSub(s)">删除</button>
      </div>
    </div>
    <div class="muted" style="font-size:12px;margin:4px 0">
      更新于 {{ s.updated_at || s.created_at || '—' }}
      <template v-if="s.auto_update_hours"> · 每 {{ s.auto_update_hours }} 小时自动更新</template>
      <template v-if="s.url"> · <span class="muted">{{ shortUrl(s.url) }}</span></template>
    </div>
    <div v-if="s.userinfo && s.userinfo.total" class="muted" style="font-size:12px">
      已用 {{ fmtBytes((s.userinfo.upload || 0) + (s.userinfo.download || 0)) }} /
      {{ fmtBytes(s.userinfo.total) }}，剩 {{ fmtBytes(s.userinfo.total - (s.userinfo.upload || 0) - (s.userinfo.download || 0)) }}
      <template v-if="s.userinfo.expire"> {{ fmtDate(s.userinfo.expire) }} 到期（剩 {{ leftDays(s.userinfo.expire) }}）</template>
      <div class="progress" style="margin-top:4px;max-width:400px">
        <div :style="{ width: pct(s.userinfo) + '%' }"></div>
      </div>
    </div>
    <div style="margin-top:6px">
      <span v-for="d in nodeDots(s.id)" :key="d.tag" class="dot" :class="d.cls" :title="d.tag"></span>
      <span v-if="!nodeDots(s.id).length" class="muted" style="font-size:12px">无节点</span>
    </div>
    <div v-if="editing === s.id" class="form-row" style="margin-top:10px">
      <div><label>名称</label><input v-model="ef.name"></div>
      <div><label>自动更新（小时，0=关闭）</label><input v-model.number="ef.auto_update_hours" type="number" min="0"></div>
      <div style="flex:0;align-self:end"><button class="small" @click="saveEdit(s)">保存</button></div>
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
      <label>订阅链接 URL（可选，填写后可一键刷新/自动更新）</label>
      <input v-model="f.url" placeholder="https://…">
      <label style="margin-top:8px">订阅内容（粘贴 base64 订阅 / 链接列表 / Clash YAML）</label>
      <textarea v-model="f.content" rows="8" required></textarea>
      <div style="margin-top:8px"><button>解析并导入</button></div>
    </form>
  </div>

  <div class="card">
    <h3>订阅分享 <span class="muted">生成免登录的公开订阅链接</span></h3>
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
    <p v-else class="muted">暂无分享</p>
    <form @submit.prevent="createShare" style="margin-top:12px">
      <h3>新建分享</h3>
      <div class="form-row">
        <div><label>名称</label><input v-model="sf.name" required></div>
        <div><label>节点过滤（标签逗号分隔，空=全部）</label><input v-model="sf.filter"></div>
      </div>
      <div><button class="small">创建分享</button></div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, put, delReq, fmtBytes } from '../api.js'

const toast = inject('toast')
const subs = ref([]), shares = ref([]), nodes = ref([]), health = ref([])
const f = ref({ name: '', format: 'auto', url: '', content: '' })
const sf = ref({ name: '', filter: '' })
const refreshing = ref(null)
const editing = ref(null), ef = ref({ name: '', auto_update_hours: 0 })

const shareUrl = s => location.origin + '/sub/' + s.token
const shortUrl = u => { try { return new URL(u).hostname } catch { return u } }

function nodeHealth(sid) {
  const ns = nodes.value.filter(n => n.sub_id === sid)
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
function fmtDate(ts) {
  return new Date(ts * 1000).toLocaleDateString()
}
function leftDays(ts) {
  const d = Math.ceil((ts * 1000 - Date.now()) / 86400000)
  return d < 0 ? '已过期' : d + ' 天'
}

async function load() {
  const [s, n, h] = await Promise.all([
    get('/api/subscriptions'), get('/api/nodes'), get('/api/health'),
  ])
  subs.value = s; nodes.value = n; health.value = h
  shares.value = await get('/api/subscription-shares').catch(() => [])
}
async function create() {
  try {
    const r = await post('/api/subscriptions', { name: f.value.name.trim(),
      content: f.value.content, format: f.value.format, url: f.value.url.trim() || undefined })
    toast(`已导入 ${r.node_count} 个节点`)
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
    toast(`已刷新：${r.node_count} 个节点`); load()
  } catch (e) { toast(e.message) }
  refreshing.value = null
}
async function toggleEnabled(s) {
  try { await put('/api/subscriptions/' + s.id, { enabled: !s.enabled }); load() }
  catch (e) { toast(e.message) }
}
function editSub(s) {
  editing.value = s.id
  ef.value = { name: s.name, auto_update_hours: s.auto_update_hours || 0 }
}
async function saveEdit(s) {
  try {
    await put('/api/subscriptions/' + s.id, ef.value)
    editing.value = null; toast('已保存'); load()
  } catch (e) { toast(e.message) }
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
.dot {
  display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  background: #5a6a8a; margin: 2px;
}
.dot.ok { background: #38c172; }
.dot.bad { background: #e5534b; }
</style>
