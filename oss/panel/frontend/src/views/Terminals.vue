<template>
  <div class="topbar"><h2>终端</h2><span class="sub">终端分流 + 连通探测</span></div>

  <div class="card">
    <h3>终端分流规则</h3>
    <table>
      <tr><th>标识（MAC/IP）</th><th>名称</th><th>策略</th><th></th></tr>
      <tr v-for="t in terminals" :key="t.id">
        <td>{{ t.ident }}</td>
        <td class="muted">{{ t.name || '—' }}</td>
        <td><span class="pill">{{ t.policy }}</span></td>
        <td><button class="small danger" @click="delT(t)">删除</button></td>
      </tr>
    </table>
    <form @submit.prevent="addT" class="form-row" style="margin-top:10px">
      <div><input v-model="tf.ident" placeholder="标识：MAC 或 IP" required></div>
      <div><input v-model="tf.name" placeholder="名称（可选）"></div>
      <div><select v-model="tf.policy">
        <option value="proxy">代理</option><option value="direct">直连</option><option value="reject">拦截</option>
      </select></div>
      <div style="flex:0"><button class="small">添加</button></div>
    </form>
  </div>

  <div class="card">
    <h3>终端探测 <span class="muted">ping + 常见 TCP 端口</span></h3>
    <div style="margin-bottom:8px"><button class="small ghost" @click="loadCandidates">加载候选（ARP / DHCP 租约 / 流量来源）</button></div>
    <table v-if="candidates.length">
      <tr><th>IP</th><th>MAC</th><th>主机名</th><th>来源</th><th></th></tr>
      <tr v-for="(c, i) in candidates" :key="i">
        <td>{{ c.ip }}</td><td class="muted">{{ c.mac || '—' }}</td><td class="muted">{{ c.hostname || '—' }}</td>
        <td class="muted">{{ c.source }}</td>
        <td>
          <button class="small ghost" @click="probe(c.ip)">探测</button>
          <button class="small ghost" v-if="c.mac" @click="addByMac(c)">按MAC添加</button>
          <button class="small ghost" @click="addByIp(c)">按IP添加</button>
        </td>
      </tr>
    </table>
    <p class="muted" style="font-size:12px">MAC 标识在拦截（bypass）时由 nftables 直接匹配，永不过期；直连（direct）时按当前 ARP 解析为 IP，设备 IP 变化后需重新应用配置。</p>
    <form @submit.prevent="probeManual" class="form-row" style="margin-top:10px">
      <div><input v-model="probeIp" placeholder="手动输入 IP" required></div>
      <div style="flex:0"><button class="small" :disabled="probing">{{ probing ? '探测中…' : '探测' }}</button></div>
    </form>
    <div v-if="probeResult">
      <dl class="kv">
        <dt>IP</dt><dd>{{ probeResult.ip }}</dd>
        <dt>ping</dt><dd>{{ probeResult.ping_ok ? `通（${probeResult.ping_ms} ms）` : '不通' }}</dd>
        <dt>开放端口</dt><dd>{{ (probeResult.open_ports || []).join(', ') || '—' }}</dd>
      </dl>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, delReq } from '../api.js'

const toast = inject('toast')
const terminals = ref([])
const tf = ref({ ident: '', name: '', policy: 'proxy' })
const candidates = ref([])
const probeIp = ref(''), probeResult = ref(null), probing = ref(false)

async function load() {
  terminals.value = (await get('/api/terminals')).terminals || []
}
async function addT() {
  try {
    await post('/api/terminals', tf.value)
    tf.value = { ident: '', name: '', policy: 'proxy' }; toast('已添加'); load()
  } catch (e) { toast(e.message) }
}
async function delT(t) {
  if (!confirm('删除该规则？')) return
  try { await delReq('/api/terminals/' + t.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}
async function loadCandidates() {
  try { candidates.value = (await get('/api/terminal-candidates')).candidates || [] }
  catch (e) { toast(e.message) }
}
async function addByMac(c) {
  try {
    await post('/api/terminals', { ident: c.mac, name: c.hostname || c.ip, policy: 'proxy' })
    toast('已按 MAC 添加'); load()
  } catch (e) { toast(e.message) }
}
async function addByIp(c) {
  try {
    await post('/api/terminals', { ident: c.ip, name: c.hostname || '', policy: 'proxy' })
    toast('已按 IP 添加'); load()
  } catch (e) { toast(e.message) }
}
async function probe(ip) { probeIp.value = ip; probeManual() }
async function probeManual() {
  probing.value = true; probeResult.value = null
  try { probeResult.value = await post('/api/terminal-test', { ip: probeIp.value }) }
  catch (e) { toast(e.message) }
  probing.value = false
}

onMounted(load)
</script>
