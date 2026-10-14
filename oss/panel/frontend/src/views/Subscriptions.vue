<template>
  <div class="topbar"><h2>订阅</h2></div>

  <div class="card">
    <table>
      <tr><th>名称</th><th>节点数</th><th>链接</th><th>创建时间</th><th></th></tr>
      <tr v-for="s in subs" :key="s.id">
        <td>{{ s.name }}</td><td>{{ s.node_count }}</td>
        <td class="muted">{{ s.url ? '✓' : '—' }}</td>
        <td class="muted">{{ s.created_at }}</td>
        <td>
          <button v-if="s.url" class="small ghost" @click="refresh(s)" :disabled="refreshing === s.id">
            {{ refreshing === s.id ? '刷新中…' : '刷新' }}</button>
          <button class="small danger" @click="delSub(s)">删除</button>
        </td>
      </tr>
    </table>
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
      <label>订阅链接 URL（可选，填写后可一键刷新）</label>
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
import { get, post, patch, delReq } from '../api.js'

const toast = inject('toast')
const subs = ref([]), shares = ref([])
const f = ref({ name: '', format: 'auto', url: '', content: '' })
const sf = ref({ name: '', filter: '' })
const refreshing = ref(null)

const shareUrl = s => location.origin + '/sub/' + s.token

async function load() {
  subs.value = await get('/api/subscriptions')
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
