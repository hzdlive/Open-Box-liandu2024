<template>
  <div class="topbar"><h2>设置</h2></div>

  <div class="tabs">
    <button v-for="t in tabs" :key="t.id" :class="{ active: tab === t.id }" @click="tab = t.id">{{ t.name }}</button>
  </div>

  <div v-if="tab === 'tun'" class="card">
    <h3>TUN 与网络</h3>
    <form @submit.prevent="saveSettings">
      <div class="form-row">
        <div><label>TUN 栈</label><select v-model="st.tun_stack">
          <option value="mixed">mixed</option><option value="gvisor">gvisor</option><option value="system">system</option>
        </select></div>
        <div><label>TUN MTU</label><input v-model="st.tun_mtu"></div>
        <div><label>默认出口</label><input v-model="st.final_outbound"></div>
      </div>
      <label><input type="checkbox" v-model="quic" style="width:auto"> 屏蔽 QUIC（代理线路上拦截 UDP/443，默认开启）</label>
      <label><input type="checkbox" v-model="tunOnly" style="width:auto"> 纯 TUN 模式（关闭透明代理 iptables/nftables 接管）</label>
      <div style="margin-top:8px"><button>保存</button></div>
    </form>
  </div>

  <div v-if="tab === 'transparent'" class="card">
    <h3>透明代理规则预览</h3>
    <div class="tabs">
      <button :class="{ active: tp === 'nft' }" @click="loadTp('nft')">nftables</button>
      <button :class="{ active: tp === 'iprules' }" @click="loadTp('iprules')">ip rules</button>
      <button :class="{ active: tp === 'dnsmasq' }" @click="loadTp('dnsmasq')">dnsmasq</button>
    </div>
    <pre class="code">{{ tpText }}</pre>
  </div>

  <div v-if="tab === 'timezone'" class="card">
    <h3>系统时区</h3>
    <form @submit.prevent="saveTz" class="form-row">
      <div><input v-model="tz" placeholder="如 Asia/Shanghai"></div>
      <div style="flex:0"><button>保存</button></div>
    </form>
    <p class="muted">OpenWrt 上会写入 /etc/TZ 并尝试执行 UCI；其他系统只读。</p>
  </div>

  <div v-if="tab === 'password'" class="card">
    <h3>面板密码</h3>
    <form @submit.prevent="savePw">
      <label>当前密码（如已设置）</label><input v-model="pw.old" type="password">
      <label style="margin-top:8px">新密码（至少 4 位）</label><input v-model="pw.new" type="password" minlength="4">
      <div style="margin-top:8px"><button>修改</button></div>
    </form>
  </div>

  <div v-if="tab === 'pair'" class="card">
    <h3>客户端配对</h3>
    <div style="margin-bottom:8px"><button class="small" @click="newCode">生成配对码（10 分钟有效）</button></div>
    <div v-if="code">
      <p class="num" style="font-size:28px;letter-spacing:4px">{{ code }}</p>
      <img :src="qrUrl" alt="配对二维码" style="width:180px;height:180px;background:#fff;padding:8px;border-radius:8px">
    </div>
    <h3 style="margin-top:16px">已配对设备</h3>
    <table>
      <tr><th>设备名</th><th>配对时间</th><th></th></tr>
      <tr v-for="d in devices" :key="d.id">
        <td>{{ d.name }}</td><td class="muted">{{ d.created_at }}</td>
        <td><button class="small danger" @click="delDevice(d.id)">吊销</button></td>
      </tr>
    </table>
  </div>

  <div v-if="tab === 'backup'" class="card">
    <h3>备份与恢复</h3>
    <div style="margin-bottom:8px">
      <button class="small" @click="doBackup">下载备份</button>
    </div>
    <form @submit.prevent="doRestore">
      <label>恢复备份（JSON 文件）</label>
      <input type="file" ref="fileInput" accept=".json">
      <div style="margin-top:8px"><button class="small danger">恢复</button></div>
    </form>
  </div>

  <div v-if="tab === 'upgrade'" class="card">
    <h3>面板升级</h3>
    <dl class="kv">
      <dt>当前面板</dt><dd>{{ upStatus.panel || '—' }}</dd>
      <dt>当前内核</dt><dd>{{ upStatus.singbox || '—' }}</dd>
      <dt>最新</dt><dd>{{ upStatus.latest || '检查中…' }}</dd>
    </dl>
    <div style="margin-top:8px">
      <button class="small" @click="checkUpgrade">检查更新</button>
      <button class="small" @click="runUpgrade" :disabled="upgrading">{{ upgrading ? '升级中…' : '执行升级' }}</button>
      <button class="small ghost" @click="loadUpLog">升级日志</button>
    </div>
    <pre v-if="upLog" class="code">{{ upLog }}</pre>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, put, delReq } from '../api.js'

const toast = inject('toast')
const tabs = [
  { id: 'tun', name: 'TUN' }, { id: 'transparent', name: '透明代理' },
  { id: 'timezone', name: '时区' }, { id: 'password', name: '密码' },
  { id: 'pair', name: '配对' }, { id: 'backup', name: '备份' },
  { id: 'upgrade', name: '升级' },
]
const tab = ref('tun')
const st = ref({}), quic = ref(true), tunOnly = ref(false)
const tp = ref('nft'), tpText = ref('')
const tz = ref('')
const pw = ref({ old: '', new: '' })
const code = ref(''), qrUrl = ref(''), devices = ref([])
const fileInput = ref(null)
const upStatus = ref({}), upLog = ref(''), upgrading = ref(false)

async function loadSettings() {
  const s = await get('/api/settings')
  st.value = s
  quic.value = s.quic_block === '1'
  tunOnly.value = s.tun_only === '1'
}
async function saveSettings() {
  try {
    await put('/api/settings', { tun_stack: st.value.tun_stack, tun_mtu: st.value.tun_mtu,
      final_outbound: st.value.final_outbound,
      quic_block: quic.value ? '1' : '0', tun_only: tunOnly.value ? '1' : '0' })
    toast('已保存'); loadSettings()
  } catch (e) { toast(e.message) }
}
async function loadTp(which) {
  tp.value = which
  try { tpText.value = (await get('/api/transparent/' + which)).text || '' }
  catch (e) { toast(e.message) }
}
async function loadTz() {
  try { tz.value = (await get('/api/system/timezone')).timezone || '' }
  catch (e) { /* ignore */ }
}
async function saveTz() {
  try { await put('/api/system/timezone', { timezone: tz.value }); toast('已保存') }
  catch (e) { toast(e.message) }
}
async function savePw() {
  try {
    await post('/api/auth/password', { old: pw.value.old, new: pw.value.new })
    pw.value = { old: '', new: '' }; toast('密码已修改')
  } catch (e) { toast(e.message) }
}
async function newCode() {
  try {
    const r = await post('/api/pair/code', {})
    code.value = r.token
    qrUrl.value = '/api/share/qr?text=' + encodeURIComponent(r.token)
  } catch (e) { toast(e.message) }
}
async function loadDevices() {
  devices.value = await get('/api/pair/devices').catch(() => [])
}
async function delDevice(id) {
  if (!confirm('吊销该设备？')) return
  try { await delReq('/api/pair/devices/' + id); toast('已吊销'); loadDevices() }
  catch (e) { toast(e.message) }
}
async function doBackup() {
  try {
    const r = await fetch('/api/backup')
    const blob = await r.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'openbox-backup.json'
    a.click()
  } catch (e) { toast(e.message) }
}
async function doRestore() {
  const f = fileInput.value?.files?.[0]
  if (!f) { toast('请选择备份文件'); return }
  if (!confirm('恢复将覆盖当前全部配置，确定？')) return
  try {
    await post('/api/backup', JSON.parse(await f.text()))
    toast('已恢复')
  } catch (e) { toast(e.message) }
}
async function checkUpgrade() {
  try { upStatus.value = await get('/api/upgrade/check') }
  catch (e) { toast(e.message) }
}
async function runUpgrade() {
  if (!confirm('执行面板升级？')) return
  upgrading.value = true
  try { await post('/api/upgrade/run', {}); toast('升级已启动，查看日志跟踪进度'); loadUpLog() }
  catch (e) { toast(e.message) }
  upgrading.value = false
}
async function loadUpLog() {
  try { upLog.value = (await get('/api/upgrade/log')).log || '' }
  catch (e) { toast(e.message) }
}

onMounted(async () => {
  loadSettings(); loadTp('nft'); loadTz(); loadDevices()
  upStatus.value = await get('/api/upgrade/status').catch(() => ({}))
})
</script>
