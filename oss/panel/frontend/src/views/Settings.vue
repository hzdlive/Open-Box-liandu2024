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
      <label><input type="checkbox" v-model="subNodeDirect" style="width:auto"> 订阅和节点站点直连（订阅更新与节点拨号不走代理）</label>
      <label><input type="checkbox" v-model="directBypass" style="width:auto"> 直连不进内核（直连域名的解析 IP 在入口放行，不经过内核）</label>
      <div class="form-row" style="margin-top:8px">
        <div><label>进入内核前放行的端口 <span class="muted">如 21114-21119, 2233</span></label>
          <input v-model="st.bypass_ports" placeholder="留空=不放行"></div>
        <div><label>放行模式</label><select v-model="st.bypass_ports_mode">
          <option value="black">黑名单：这些端口不进内核</option>
          <option value="white">白名单：只有这些端口进内核</option>
        </select></div>
      </div>
      <div style="margin-top:8px"><label>测速地址 <span class="muted">urltest 组用</span></label>
        <input v-model="st.speedtest_url" placeholder="http://www.gstatic.com/generate_204"></div>
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
    <h3>路由器标识 <span class="muted">客户端 App 上显示</span></h3>
    <form @submit.prevent="saveRouter">
      <div class="form-row">
        <div><label>名称</label><input v-model="router.name"></div>
        <div><label>图标</label><input v-model="router.icon" placeholder="router"></div>
        <div><label>地区</label><input v-model="router.region" placeholder="cn"></div>
      </div>
      <div><button class="small">保存标识</button></div>
    </form>
    <h3 style="margin-top:16px">地区分流 <span class="muted">客户端按所在地区选择命中规则</span></h3>
    <table v-if="regionRules.length">
      <tr><th>地区</th><th>名称</th><th>规则数</th><th>启用</th><th></th></tr>
      <tr v-for="r in regionRules" :key="r.id">
        <td><code>{{ r.region }}</code></td>
        <td>{{ r.name || '—' }}</td>
        <td class="muted">{{ Object.keys(r.rules || {}).length }}</td>
        <td><input type="checkbox" :checked="r.enabled" @change="toggleRegion(r)" style="width:auto"></td>
        <td>
          <button class="small ghost" @click="editRegion(r)">编辑</button>
          <button class="small danger" @click="delRegion(r)">删除</button>
        </td>
      </tr>
    </table>
    <p v-else class="muted">暂无地区规则</p>
    <form @submit.prevent="saveRegion" style="margin-top:10px">
      <h3>{{ editingRegion ? '编辑地区规则' : '新建地区规则' }}</h3>
      <div class="form-row">
        <div><label>地区代码 <span class="muted">如 cn / us / auto</span></label>
          <input v-model="rg.region" required></div>
        <div><label>名称</label><input v-model="rg.name" placeholder="中国大陆"></div>
      </div>
      <label>规则 <span class="muted">JSON：{"domain_suffix": ["example.com"], "action": "proxy"}</span></label>
      <textarea v-model="rg.rulesText" rows="4" placeholder='{"domain_suffix": ["example.com"], "action": "direct"}'></textarea>
      <div style="margin-top:8px">
        <button class="small">{{ editingRegion ? '保存' : '创建' }}</button>
        <button v-if="editingRegion" type="button" class="small ghost" @click="resetRegion">取消</button>
      </div>
    </form>
    <h3 style="margin-top:16px">客户端配对</h3>
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
    <h3 style="margin-top:16px">自动更新</h3>
    <div class="grid">
      <div><label>自动更新</label><select v-model="upCfg.update_auto">
        <option value="0">关闭</option><option value="1">开启</option>
      </select></div>
      <div><label>检查时间（时）</label><input v-model="upCfg.update_hour" type="number" min="0" max="23"></div>
      <div><label>版本通道</label><select v-model="upCfg.update_channel">
        <option value="auto">自动</option><option value="stable">稳定版</option><option value="beta">测试版</option>
      </select></div>
      <div><label>检查通道</label><select v-model="upCfg.update_check_channel">
        <option value="mirror">镜像</option><option value="official">官方</option>
      </select></div>
      <div><label>检查间隔（天）</label><input v-model="upCfg.update_days" type="number" min="1" max="30"></div>
    </div>
    <div style="margin-top:8px"><button class="small" @click="saveUpCfg">保存</button></div>
    <h3 style="margin-top:16px">面板自更新状态</h3>
    <dl class="kv">
      <dt>本地提交</dt><dd>{{ puStatus.local_commit ? puStatus.local_commit.slice(0, 12) : '—' }}</dd>
      <dt>上次检查</dt><dd>{{ puStatus.update_last_check || '从未检查' }}</dd>
      <dt>检查结果</dt><dd>{{ puResultText }}</dd>
    </dl>
    <div style="margin-top:8px">
      <button class="small" @click="checkPanelUpdate" :disabled="puChecking">{{ puChecking ? '检查中…' : '检查面板更新' }}</button>
      <button class="small" @click="applyPanelUpdate" :disabled="!puStatus.last_result?.available">立即更新面板</button>
      <button class="small ghost" @click="loadPuLog">更新日志</button>
    </div>
    <pre v-if="puLog" class="code">{{ puLog }}</pre>
  </div>
</template>

<script setup>
import { ref, onMounted, inject, computed } from 'vue'
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
const subNodeDirect = ref(false), directBypass = ref(false)
const tp = ref('nft'), tpText = ref('')
const tz = ref('')
const pw = ref({ old: '', new: '' })
const code = ref(''), qrUrl = ref(''), devices = ref([])
const router = ref({ name: '', icon: '', region: '' })
const regionRules = ref([])
const editingRegion = ref(null)
const rg = ref({ region: '', name: '', rulesText: '' })
const fileInput = ref(null)
const upStatus = ref({}), upLog = ref(''), upgrading = ref(false)
const upCfg = ref({ update_auto: '0', update_hour: '4', update_channel: 'auto', update_check_channel: 'mirror', update_days: '1' })

async function loadSettings() {
  const s = await get('/api/settings')
  st.value = s
  quic.value = s.quic_block === '1'
  tunOnly.value = s.tun_only === '1'
  subNodeDirect.value = s.sub_node_direct === '1'
  directBypass.value = s.direct_bypass_kernel === '1'
  upCfg.value = { update_auto: s.update_auto || '0', update_hour: s.update_hour || '4',
    update_channel: s.update_channel || 'auto', update_check_channel: s.update_check_channel || 'mirror',
    update_days: s.update_days || '1' }
}
async function saveUpCfg() {
  try {
    await put('/api/settings', { update_auto: upCfg.value.update_auto, update_hour: upCfg.value.update_hour,
      update_channel: upCfg.value.update_channel, update_check_channel: upCfg.value.update_check_channel,
      update_days: upCfg.value.update_days })
    toast.success('已保存')
  } catch (e) { toast.error('保存失败: ' + e.message) }
}
async function saveSettings() {
  try {
    await put('/api/settings', { tun_stack: st.value.tun_stack, tun_mtu: st.value.tun_mtu,
      final_outbound: st.value.final_outbound,
      quic_block: quic.value ? '1' : '0', tun_only: tunOnly.value ? '1' : '0',
      sub_node_direct: subNodeDirect.value ? '1' : '0',
      direct_bypass_kernel: directBypass.value ? '1' : '0',
      bypass_ports: st.value.bypass_ports || '',
      bypass_ports_mode: st.value.bypass_ports_mode || 'black',
      speedtest_url: st.value.speedtest_url || '' })
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
async function loadRouter() {
  const s = await get('/api/settings')
  router.value = { name: s.router_name || '', icon: s.router_icon || '', region: s.router_region || '' }
}
async function saveRouter() {
  try {
    await put('/api/settings', { router_name: router.value.name, router_icon: router.value.icon, router_region: router.value.region })
    toast('已保存')
  } catch (e) { toast(e.message) }
}
async function loadRegionRules() {
  regionRules.value = await get('/api/region-rules').catch(() => [])
}
function resetRegion() {
  editingRegion.value = null
  rg.value = { region: '', name: '', rulesText: '' }
}
function editRegion(r) {
  editingRegion.value = r.id
  rg.value = { region: r.region, name: r.name, rulesText: JSON.stringify(r.rules || {}, null, 2) }
}
async function saveRegion() {
  let rules = {}
  try { rules = rg.value.rulesText.trim() ? JSON.parse(rg.value.rulesText) : {} }
  catch { toast('规则 JSON 格式错误'); return }
  try {
    if (editingRegion.value) await put('/api/region-rules/' + editingRegion.value,
      { region: rg.value.region, name: rg.value.name, rules })
    else await post('/api/region-rules', { region: rg.value.region, name: rg.value.name, rules })
    toast('已保存'); resetRegion(); loadRegionRules()
  } catch (e) { toast(e.message) }
}
async function delRegion(r) {
  if (!confirm(`删除地区规则 ${r.region}？`)) return
  try { await delReq('/api/region-rules/' + r.id); toast('已删除'); loadRegionRules() }
  catch (e) { toast(e.message) }
}
async function toggleRegion(r) {
  try { await put('/api/region-rules/' + r.id, { enabled: !r.enabled }); loadRegionRules() }
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
const puStatus = ref({}), puLog = ref(''), puChecking = ref(false)
const puResultText = computed(() => {
  const r = puStatus.value.last_result
  if (!r || !Object.keys(r).length) return '—'
  if (r.error) return '检查失败：' + r.error
  if (r.available) return '有可用更新（远端 ' + String(r.remote || '').slice(0, 12) + '）'
  return '已是最新'
})
async function loadPanelUpdate() {
  try { puStatus.value = await get('/api/panel/update/status') }
  catch (e) { toast(e.message) }
}
async function checkPanelUpdate() {
  puChecking.value = true
  try { await post('/api/panel/update/check', {}); await loadPanelUpdate(); toast.success('检查完成') }
  catch (e) { toast(e.message) }
  puChecking.value = false
}
async function applyPanelUpdate() {
  if (!confirm('将拉取远端更新并重启面板，确定？')) return
  try { await post('/api/panel/update/apply', {}); toast('更新已启动，面板即将重启'); loadPuLog() }
  catch (e) { toast(e.message) }
}
async function loadPuLog() {
  try { puLog.value = (await get('/api/panel/update/log')).log || '' }
  catch (e) { toast(e.message) }
}

onMounted(async () => {
  loadSettings(); loadTp('nft'); loadTz(); loadDevices(); loadRouter(); loadRegionRules()
  upStatus.value = await get('/api/upgrade/status').catch(() => ({}))
  loadPanelUpdate()
})
</script>
