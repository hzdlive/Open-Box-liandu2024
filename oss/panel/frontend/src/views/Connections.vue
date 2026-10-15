<template>
  <div class="topbar"><h2>连接</h2></div>

  <div class="tabs">
    <button v-for="t in tabs" :key="t.id" :class="{ active: tab === t.id }" @click="tab = t.id">{{ t.name }}</button>
  </div>

  <div v-if="tab === 'now'">
    <div class="grid c4">
      <div class="card stat"><div class="num">{{ conns.length }}</div><div class="lbl">活跃连接</div></div>
      <div class="card stat"><div class="num">{{ fmtBytes(up) }}</div><div class="lbl">上行</div></div>
      <div class="card stat"><div class="num">{{ fmtBytes(down) }}</div><div class="lbl">下行</div></div>
      <div class="card stat"><div class="num">{{ kernelOk ? '正常' : '断开' }}</div><div class="lbl">内核 API</div></div>
    </div>
    <div class="card">
      <div style="margin-bottom:8px">
        <button class="small ghost" @click="loadConns">刷新</button>
        <input v-model="cFilter" placeholder="过滤 域名/IP/出口" style="max-width:240px;margin-left:8px">
      </div>
      <table>
        <tr><th>域名</th><th>目标</th><th>出口</th><th>上行</th><th>下行</th></tr>
        <tr v-for="c in filteredConns" :key="c.id">
          <td>{{ c.host || c.destinationIP }}</td>
          <td class="muted">{{ c.destinationIP }}:{{ c.destinationPort }}</td>
          <td><span class="pill">{{ c.chains?.[c.chains.length - 1] || '—' }}</span></td>
          <td class="muted">{{ fmtBytes(c.upload) }}</td>
          <td class="muted">{{ fmtBytes(c.download) }}</td>
        </tr>
      </table>
    </div>
  </div>

  <div v-if="tab === 'month'" class="card">
    <h3>月视图 <input v-model="month" type="month" style="max-width:180px;margin-left:8px" @change="loadMonth"></h3>
    <div class="grid c3">
      <div class="card stat" style="margin:0"><div class="num">{{ fmtBytes(mData.total?.up) }}</div><div class="lbl">上行</div></div>
      <div class="card stat" style="margin:0"><div class="num">{{ fmtBytes(mData.total?.down) }}</div><div class="lbl">下行</div></div>
      <div class="card stat" style="margin:0"><div class="num">{{ fmtBytes((mData.total?.up || 0) + (mData.total?.down || 0)) }}</div><div class="lbl">合计</div></div>
    </div>
    <p class="muted" style="margin:8px 0 0">本月连接数：{{ mData.total?.conns || 0 }}</p>
    <table style="margin-top:12px">
      <tr><th>日期</th><th>上行</th><th>下行</th><th>连接</th><th></th></tr>
      <tr v-for="d in mData.days" :key="d.day">
        <td>{{ d.day }}</td><td class="muted">{{ fmtBytes(d.up) }}</td>
        <td class="muted">{{ fmtBytes(d.down) }}</td><td class="muted">{{ d.conns || 0 }}</td>
        <td><button class="small ghost" @click="loadDay(d.day)">下钻</button></td>
      </tr>
    </table>
    <div v-if="dayData">
      <h3>{{ dayData.day }} 明细</h3>
      <div class="tabs">
        <button :class="{ active: dayDim === 'by_proxy' }" @click="dayDim = 'by_proxy'">按出口</button>
        <button :class="{ active: dayDim === 'by_host' }" @click="dayDim = 'by_host'">按目标</button>
        <button :class="{ active: dayDim === 'by_client' }" @click="dayDim = 'by_client'">按终端</button>
      </div>
      <table>
        <tr><th>{{ dayDimName }}</th><th>上行</th><th>下行</th></tr>
        <tr v-for="(r, i) in dayData[dayDim]" :key="i">
          <td>{{ r[dayDimKey] }}</td><td class="muted">{{ fmtBytes(r.up) }}</td>
          <td class="muted">{{ fmtBytes(r.down) }}</td>
        </tr>
      </table>
    </div>
  </div>

  <div v-if="tab === 'drill'" class="card">
    <h3>下钻分析</h3>
    <div class="form-row">
      <div><input v-model="month" type="month" @change="loadDrill"></div>
      <div><select v-model="dim" @change="loadDrill">
        <option value="proxy">按出口</option><option value="host">按目标</option><option value="client">按终端</option>
      </select></div>
    </div>
    <table>
      <tr><th>{{ dimName }}</th><th>上行</th><th>下行</th><th>占比</th></tr>
      <tr v-for="(r, i) in drillRows" :key="i">
        <td>{{ r[dim] }}</td><td class="muted">{{ fmtBytes(r.up) }}</td>
        <td class="muted">{{ fmtBytes(r.down) }}</td>
        <td><div class="progress"><div :style="{ width: r.pct + '%' }"></div></div></td>
      </tr>
    </table>
  </div>

  <div v-if="tab === 'daily'" class="card">
    <h3>每日汇总（近 {{ days }} 天）</h3>
    <input v-model.number="days" type="number" min="1" max="90" style="max-width:120px" @change="loadDaily">
    <table style="margin-top:8px">
      <tr><th>日期</th><th>上行</th><th>下行</th><th>合计</th></tr>
      <tr v-for="d in daily" :key="d.day">
        <td>{{ d.day }}</td><td class="muted">{{ fmtBytes(d.up) }}</td>
        <td class="muted">{{ fmtBytes(d.down) }}</td><td>{{ fmtBytes(d.total) }}</td>
      </tr>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { get, fmtBytes } from '../api.js'

const toast = inject('toast')
const tabs = [
  { id: 'now', name: '实时' }, { id: 'month', name: '月视图' },
  { id: 'drill', name: '下钻' }, { id: 'daily', name: '每日' },
]
const tab = ref('now')
const conns = ref([]), up = ref(0), down = ref(0), kernelOk = ref(false)
const cFilter = ref('')
const month = ref(new Date().toISOString().slice(0, 7))
const mData = ref({ days: [] }), dayData = ref(null)
const dim = ref('proxy'), drillRows = ref([])
const days = ref(7), daily = ref([])
const dayDim = ref('by_proxy')

const dayDimName = computed(() => ({ by_proxy: '出口', by_host: '目标', by_client: '终端' }[dayDim.value]))
const dayDimKey = computed(() => ({ by_proxy: 'proxy', by_host: 'host', by_client: 'client' }[dayDim.value]))

const dimName = computed(() => ({ proxy: '出口', host: '目标', client: '终端' }[dim.value]))

const filteredConns = computed(() => {
  const f = cFilter.value.trim().toLowerCase()
  if (!f) return conns.value
  return conns.value.filter(c =>
    ((c.host || '') + (c.destinationIP || '') + ((c.chains || []).join(' '))).toLowerCase().includes(f))
})

async function loadConns() {
  try {
    const r = await get('/api/connections')
    conns.value = r.connections || []
    kernelOk.value = r.kernel !== false
  } catch (e) { toast(e.message) }
  try {
    const t = await get('/api/traffic/now')
    up.value = t.up; down.value = t.download; kernelOk.value = t.kernel
  } catch (e) { /* ignore */ }
}
async function loadMonth() {
  try { mData.value = await get('/api/traffic/month?month=' + month.value); dayData.value = null }
  catch (e) { toast(e.message) }
}
async function loadDay(day) {
  try { dayData.value = await get('/api/traffic/day?day=' + day) }
  catch (e) { toast(e.message) }
}
async function loadDrill() {
  try {
    const r = await get(`/api/traffic/drill?month=${month.value}&dim=${dim.value}`)
    const rows = r.rows || []
    const total = rows.reduce((a, x) => a + x.up + x.down, 0) || 1
    drillRows.value = rows.map(x => ({ ...x, pct: Math.round((x.up + x.down) / total * 100) }))
  } catch (e) { toast(e.message) }
}
async function loadDaily() {
  try { daily.value = (await get('/api/traffic/daily?days=' + days.value)).rows || [] }
  catch (e) { toast(e.message) }
}

onMounted(() => { loadConns(); loadMonth(); loadDrill(); loadDaily() })
</script>
