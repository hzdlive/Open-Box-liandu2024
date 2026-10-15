<template>
  <div class="topbar"><h2>规则集</h2><span class="sub">远程规则列表，定期更新</span></div>

  <div class="card">
    <h3>内置规则数据 <span class="muted">geosite / geoip（sing-box 本地规则集，站点集分流引用）</span></h3>
    <div style="margin-bottom:8px">
      <button class="small ghost" @click="ensureGeo">下载缺失</button>
      <span class="muted" style="margin-left:8px">目录：{{ geo.dir }}</span>
    </div>
    <p v-if="geo.missing && geo.missing.length" class="muted">缺失 {{ geo.missing.length }} 个：{{ geo.missing.join(', ') }}</p>
    <table v-if="geo.files && geo.files.length">
      <tr><th>名称</th><th>类型</th><th>大小</th><th>更新时间</th></tr>
      <tr v-for="f in geo.files" :key="f.name">
        <td>{{ f.name }}</td><td class="muted">{{ f.kind }}</td>
        <td class="muted">{{ fmtSize(f.size) }}</td><td class="muted">{{ f.updated_at }}</td>
      </tr>
    </table>
    <p v-else class="muted">尚未下载。点"下载缺失"从上游公开源获取（geosite: MIT 数据；geoip: MaxMind GeoLite2，需署名）。</p>
  </div>

  <div class="card">
    <h3>自定义远程规则集</h3>
    <table>
      <tr><th>名称</th><th>URL</th><th>格式</th><th>大小</th><th>更新时间</th><th></th></tr>
      <tr v-for="r in list" :key="r.id">
        <td>{{ r.name }}</td>
        <td class="muted" style="max-width:280px;overflow:hidden;text-overflow:ellipsis">{{ r.url || '—' }}</td>
        <td class="muted">{{ r.format }}</td>
        <td class="muted">{{ r.size }} 条</td>
        <td class="muted">{{ r.updated_at || '—' }}</td>
        <td>
          <button v-if="r.url" class="small ghost" @click="refresh(r)">更新</button>
          <button class="small danger" @click="del(r)">删除</button>
        </td>
      </tr>
    </table>
  </div>

  <div class="card">
    <h3>新增规则集</h3>
    <form @submit.prevent="create">
      <div class="form-row">
        <div><label>名称</label><input v-model="f.name" required></div>
        <div><label>格式</label><select v-model="f.format">
          <option value="auto">自动识别</option><option value="domain-list">域名列表</option>
          <option value="clash-classical">Clash classical</option>
        </select></div>
      </div>
      <label>URL（可选，不填则手动粘贴内容）</label>
      <input v-model="f.url" placeholder="https://…">
      <label style="margin-top:8px">内容（URL 为空时必填）</label>
      <textarea v-model="f.content" rows="6"></textarea>
      <div style="margin-top:8px"><button>保存</button></div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, delReq } from '../api.js'

const toast = inject('toast')
const list = ref([])
const geo = ref({ files: [], missing: [], dir: '' })
const f = ref({ name: '', format: 'auto', url: '', content: '' })

async function load() {
  list.value = await get('/api/rulesets')
  try { geo.value = await get('/api/geodata') } catch (e) { /* optional */ }
}
function fmtSize(n) {
  if (n > 1e6) return (n / 1e6).toFixed(1) + ' MB'
  if (n > 1e3) return Math.round(n / 1e3) + ' KB'
  return n + ' B'
}
async function ensureGeo() {
  try {
    const x = await post('/api/geodata/ensure', {})
    toast(`已下载 ${x.downloaded.length} 个` + (x.missing.length ? `，缺失 ${x.missing.length} 个` : ''))
    load()
  } catch (e) { toast(e.message) }
}
async function create() {
  try {
    await post('/api/rulesets', { name: f.value.name, format: f.value.format,
      url: f.value.url.trim() || undefined, content: f.value.content || undefined })
    toast('已保存'); f.value = { name: '', format: 'auto', url: '', content: '' }; load()
  } catch (e) { toast(e.message) }
}
async function refresh(r) {
  try { const x = await post(`/api/rulesets/${r.id}/refresh`, {}); toast(`已更新：${x.size} 条`); load() }
  catch (e) { toast(e.message) }
}
async function del(r) {
  if (!confirm(`删除规则集 ${r.name}？`)) return
  try { await delReq('/api/rulesets/' + r.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}

onMounted(load)
</script>
