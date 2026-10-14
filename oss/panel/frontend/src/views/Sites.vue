<template>
  <div class="topbar">
    <h2>站点集 <span class="sub">自上而下匹配</span></h2>
  </div>

  <div class="card">
    <h3>前置自定义分流 <span class="muted">在所有站点集之前匹配</span></h3>
    <table v-if="frontRules.length">
      <tr><th>#</th><th>域名</th><th>走</th><th>启用</th><th></th></tr>
      <tr v-for="(r, i) in frontRules" :key="r.id">
        <td class="muted">{{ i + 1 }}</td>
        <td><code>{{ r.domain }}</code></td>
        <td>{{ targetName(r.target) }}</td>
        <td><input type="checkbox" :checked="r.enabled" @change="toggleFront(r)" style="width:auto"></td>
        <td>
          <button class="small ghost" @click="moveFront(r, -1)" :disabled="i === 0">↑</button>
          <button class="small ghost" @click="moveFront(r, 1)" :disabled="i === frontRules.length - 1">↓</button>
          <button class="small danger" @click="delFront(r)">删除</button>
        </td>
      </tr>
    </table>
    <p v-else class="muted">暂无前置规则</p>
    <form @submit.prevent="addFront" class="form-row" style="margin-top:10px">
      <div><input v-model="fr.domain" placeholder="域名，如 example.com（匹配其子域名）" required></div>
      <div><input v-model="fr.target" placeholder="目标：组名 / 节点标签 / direct / reject" required></div>
      <div style="flex:0"><button class="small">添加</button></div>
    </form>
  </div>

  <div class="card">
    <table>
      <tr><th>#</th><th>名称</th><th>动作</th><th>组</th><th>规则</th><th>热切换</th><th></th></tr>
      <tr v-for="(s, i) in sites" :key="s.id">
        <td class="muted">{{ i + 1 }}</td>
        <td><b>{{ s.name }}</b></td>
        <td><span :class="['pill', s.action === 'proxy' ? 'ok' : s.action === 'reject' ? 'bad' : '']">
          {{ actName(s.action) }}</span></td>
        <td class="muted">{{ s.group }}</td>
        <td class="muted">{{ rulesSummary(s.rules) }}</td>
        <td>
          <button v-if="s.action !== 'reject'" class="small ghost"
                  @click="flip(s)">{{ s.flip === 'direct' ? '切回代理' : '切直连' }}</button>
          <span v-else class="muted">—</span>
        </td>
        <td>
          <button class="small ghost" @click="edit(s)">编辑</button>
          <button class="small ghost" @click="move(s, -1)" :disabled="i === 0">↑</button>
          <button class="small ghost" @click="move(s, 1)" :disabled="i === sites.length - 1">↓</button>
          <button class="small danger" @click="del(s)">删除</button>
        </td>
      </tr>
    </table>
  </div>

  <div class="card">
    <h3>{{ editing ? '编辑站点集' : '新建站点集' }}</h3>
    <form @submit.prevent="save">
      <div class="form-row">
        <div><label>名称</label><input v-model="f.name" required></div>
        <div><label>动作</label><select v-model="f.action">
          <option value="proxy">代理</option><option value="direct">直连</option><option value="reject">拦截</option>
        </select></div>
        <div><label>节点组（代理时）</label><input v-model="f.group" placeholder="所有-自动"></div>
      </div>
      <div class="form-row">
        <div><label>域名（逗号分隔）</label><textarea v-model="f.domains" rows="2"></textarea></div>
        <div><label>域名后缀（逗号分隔）</label><textarea v-model="f.suffix" rows="2"></textarea></div>
      </div>
      <div class="form-row">
        <div><label>IP / CIDR（逗号分隔）</label><textarea v-model="f.ip" rows="2"></textarea></div>
        <div><label>关键词（逗号分隔）</label><textarea v-model="f.keyword" rows="2"></textarea></div>
      </div>
      <div><label>引用规则集 <span class="muted">geosite 等已抓取的规则集</span></label>
        <select v-model="f.rulesets" multiple size="4" style="min-width:240px">
          <option v-for="rs in rulesets" :key="rs.name" :value="rs.name">{{ rs.name }}</option>
        </select>
      </div>
      <div style="margin-top:8px">
        <button>{{ editing ? '保存' : '创建' }}</button>
        <button v-if="editing" type="button" class="ghost" @click="reset">取消</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, put, delReq } from '../api.js'

const toast = inject('toast')
const sites = ref([])
const rulesets = ref([])
const frontRules = ref([])
const editing = ref(null)
const f = ref({ name: '', action: 'proxy', group: '所有-自动', domains: '', suffix: '', ip: '', keyword: '', rulesets: [] })
const fr = ref({ domain: '', target: '' })

const actName = a => ({ proxy: '代理', direct: '直连', reject: '拦截' }[a] || a)
const targetName = t => ({ direct: '直连', reject: '拦截', auto: '自动' }[t] || t)
const split = s => (s || '').split(',').map(x => x.trim()).filter(Boolean)

function rulesSummary(r) {
  r = r || {}
  const p = []
  if (r.domains?.length) p.push(`域名×${r.domains.length}`)
  if (r.domain_suffix?.length) p.push(`后缀×${r.domain_suffix.length}`)
  if (r.ip_cidr?.length) p.push(`IP×${r.ip_cidr.length}`)
  if (r.domain_keyword?.length) p.push(`关键词×${r.domain_keyword.length}`)
  if (r.rule_sets?.length) p.push(`规则集×${r.rule_sets.length}`)
  return p.join(' ') || '—'
}

async function load() {
  sites.value = await get('/api/sitesets')
  rulesets.value = await get('/api/rulesets').catch(() => [])
  frontRules.value = await get('/api/front-rules')
}

function reset() {
  editing.value = null
  f.value = { name: '', action: 'proxy', group: '所有-自动', domains: '', suffix: '', ip: '', keyword: '', rulesets: [] }
}
function edit(s) {
  editing.value = s.id
  const r = s.rules || {}
  f.value = { name: s.name, action: s.action, group: s.group,
    domains: (r.domains || []).join(', '), suffix: (r.domain_suffix || []).join(', '),
    ip: (r.ip_cidr || []).join(', '), keyword: (r.domain_keyword || []).join(', '),
    rulesets: r.rule_sets || [] }
}
async function save() {
  const body = { name: f.value.name, action: f.value.action, group: f.value.group,
    rules: { domains: split(f.value.domains), domain_suffix: split(f.value.suffix),
             ip_cidr: split(f.value.ip), domain_keyword: split(f.value.keyword),
             rule_sets: f.value.rulesets } }
  try {
    if (editing.value) await put('/api/sitesets/' + editing.value, body)
    else await post('/api/sitesets', body)
    toast('已保存'); reset(); load()
  } catch (e) { toast(e.message) }
}
async function del(s) {
  if (!confirm(`删除站点集 ${s.name}？`)) return
  try { await delReq('/api/sitesets/' + s.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function flip(s) {
  const to = s.flip === 'direct' ? 'proxy' : 'direct'
  try {
    const r = await post(`/api/sitesets/${s.id}/flip`, { to })
    toast(r.hot ? '已热切换（免重启）' : '已保存，下次应用生效'); load()
  } catch (e) { toast(e.message) }
}
async function move(s, dir) {
  const i = sites.value.findIndex(x => x.id === s.id)
  const j = i + dir
  if (j < 0 || j >= sites.value.length) return
  const order = sites.value.map(x => x.id)
  ;[order[i], order[j]] = [order[j], order[i]]
  try { await put('/api/sitesets/order', { order }); load() }
  catch (e) { toast(e.message) }
}

async function addFront() {
  try {
    await post('/api/front-rules', fr.value)
    fr.value = { domain: '', target: '' }; toast('已添加'); load()
  } catch (e) { toast(e.message) }
}
async function delFront(r) {
  if (!confirm(`删除前置规则 ${r.domain}？`)) return
  try { await delReq('/api/front-rules/' + r.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function toggleFront(r) {
  try { await put('/api/front-rules/' + r.id, { enabled: !r.enabled }); load() }
  catch (e) { toast(e.message) }
}
async function moveFront(r, dir) {
  const i = frontRules.value.findIndex(x => x.id === r.id)
  const j = i + dir
  if (j < 0 || j >= frontRules.value.length) return
  try {
    await put('/api/front-rules/' + frontRules.value[j].id, { position: r.position })
    await put('/api/front-rules/' + r.id, { position: frontRules.value[j].position })
    load()
  } catch (e) { toast(e.message) }
}

onMounted(load)
</script>
