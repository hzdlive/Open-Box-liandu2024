<!-- Open-Box 二开：后端设置（1:1 对标原版） -->
<template>
  <div class="flex flex-col gap-3">
    <div v-if="err" class="alert alert-error"><span>{{ err }}</span></div>

    <!-- 内核与更新 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-1 flex flex-wrap items-center gap-2 text-sm">
        <span class="opacity-60">ⓘ {{ $t('obx.kernelVersion') }}:</span>
        <span class="font-mono">{{ kernelVer }}</span>
        <a href="https://github.com/SagerNet/sing-box" target="_blank" class="link link-primary text-xs">sing-box GitHub ↗</a>
      </div>
      <div class="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span class="opacity-60">🗺 GeoSite {{ geoSite }} 份</span>
        <span class="opacity-60">💾 GeoIP {{ geoIp }} 份</span>
        <span class="font-mono text-xs opacity-60">{{ geoTime }}</span>
        <a href="https://github.com/SagerNet/sing-geosite" target="_blank" class="link link-primary text-xs">Geo 数据 GitHub ↗</a>
      </div>

      <div class="mb-2 flex flex-wrap items-center gap-3 text-sm">
        <span>{{ $t('obx.kernel') }} <span class="badge badge-sm" :class="kernelRunning ? 'badge-success' : 'badge-ghost'">{{ kernelRunning ? $t('obx.running') : $t('obx.stopped') }}</span></span>
        <span>{{ $t('obx.panel') }} <span class="badge badge-success badge-sm">{{ $t('obx.running') }}</span></span>
        <span>{{ $t('obx.autostart') }} <span class="badge badge-sm" :class="autostart ? 'badge-success' : 'badge-ghost'">{{ autostart ? $t('obx.enabled') : $t('obx.disabled') }}</span></span>
      </div>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.kernelOpHint') }}</p>
      <div class="mb-3 flex gap-2">
        <button class="btn btn-sm" :disabled="kernelRunning || opBusy" @click="kernelOp('start')">▶ {{ $t('obx.start') }}</button>
        <button class="btn btn-sm" :disabled="!kernelRunning || opBusy" @click="kernelOp('stop')">⏹ {{ $t('obx.stop') }}</button>
        <button class="btn btn-sm" :disabled="opBusy" @click="kernelOp('restart')">↻ {{ $t('obx.restart') }}</button>
      </div>

      <div class="mb-2 flex flex-wrap items-center gap-2">
        <select v-model="s.install_channel" class="select select-bordered select-sm" @change="saveKey('install_channel')">
          <option value="keep">{{ $t('obx.keepChannel') }}</option>
          <option value="github">GitHub {{ $t('obx.direct') }}</option>
          <option value="mirror">{{ $t('obx.mirrorAccel') }}</option>
        </select>
        <button class="btn btn-sm" :disabled="checking" @click="checkUpdate">{{ $t('obx.checkUpdate') }}</button>
        <span class="text-xs opacity-60">{{ $t('obx.channelHint') }}</span>
      </div>
      <div v-if="updateInfo" class="alert alert-info mb-2 py-2 text-sm"><span>{{ updateInfo }}</span></div>

      <label class="flex cursor-pointer items-center gap-3">
        <span class="text-sm font-medium">{{ $t('obx.autoUpdate') }}</span>
        <input v-model="autoUpd" type="checkbox" class="toggle toggle-success" @change="saveKey('auto_update', autoUpd ? '1' : '0')" />
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.autoUpdateHint') }}</p>
    </div>

    <!-- 订阅和节点站点直连 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <label class="flex cursor-pointer items-center gap-3">
        <span class="font-bold">{{ $t('obx.subDirect') }}</span>
        <input v-model="s.sub_direct" type="checkbox" class="toggle toggle-success" @change="saveBool('sub_direct')" />
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.subDirectHint') }}</p>
    </div>

    <!-- 直连不进内核 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <label class="flex cursor-pointer items-center gap-3">
        <span class="font-bold">{{ $t('obx.directBypassKernel') }}</span>
        <input v-model="s.direct_bypass" type="checkbox" class="toggle toggle-success" @change="saveBool('direct_bypass')" />
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.directBypassHint') }}</p>
    </div>

    <!-- 屏蔽 QUIC -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <label class="flex cursor-pointer items-center gap-3">
        <span class="font-bold">{{ $t('obx.blockQuic') }}</span>
        <input v-model="s.block_quic" type="checkbox" class="toggle toggle-success" @change="saveBool('block_quic')" />
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.blockQuicHint') }}</p>
    </div>

    <!-- 进内核前放行的端口 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.preKernelPorts') }}</h3>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.preKernelPortsHint') }}</p>
      <div class="mb-2 flex gap-1">
        <button type="button" class="btn btn-xs rounded-full" :class="portTab === 'black' ? 'btn-success' : 'btn-ghost'" @click="switchPortTab('black')">{{ $t('obx.blacklist') }}</button>
        <button type="button" class="btn btn-xs rounded-full" :class="portTab === 'white' ? 'btn-success' : 'btn-ghost'" @click="switchPortTab('white')">{{ $t('obx.whitelist') }}</button>
      </div>
      <input
        v-model="portInput"
        class="input input-bordered w-full rounded-full"
        :placeholder="$t('obx.portsPh')"
        @change="savePorts"
      />
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.portsHint') }}</p>
    </div>

    <!-- IPv6 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <label class="flex cursor-pointer items-center gap-3">
        <span class="font-bold">IPv6</span>
        <input v-model="s.ipv6" type="checkbox" class="toggle toggle-success" @change="saveBool('ipv6')" />
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.ipv6Hint') }}</p>
    </div>

    <!-- TUN 参数 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.tunParams') }}</h3>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.tunParamsHint') }}</p>
      <button class="btn btn-ghost btn-sm" @click="tunDlg = true">☰ {{ $t('obx.advancedSettings') }}</button>
    </div>

    <!-- TUN 高级设置 -->
    <div v-if="tunDlg" class="modal modal-open">
      <div class="modal-box">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.advancedSettings') }}</h3>
          <button class="btn btn-ghost btn-sm btn-square" @click="tunDlg = false">✕</button>
        </div>
        <div class="flex flex-col gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.tunStack') }}</span>
            <select v-model="s.tun_stack" class="select select-bordered w-full" @change="saveKey('tun_stack')">
              <option value="mixed">mixed</option>
              <option value="gvisor">gvisor</option>
              <option value="system">system</option>
            </select>
            <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.tunStackHint') }}</span>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">MTU</span>
            <input v-model="s.tun_mtu" class="input input-bordered w-full" @change="saveKey('tun_mtu')" />
            <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.mtuHint') }}</span>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.tcpMss') }}</span>
            <input v-model="s.mss_clamp" class="input input-bordered w-full" @change="saveKey('mss_clamp')" />
            <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.mssHint') }}</span>
          </label>
        </div>
        <div class="modal-action">
          <button class="btn btn-ghost" @click="tunDlg = false">{{ $t('obx.close') }}</button>
        </div>
      </div>
    </div>

    <!-- 测速地址 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.speedTestUrl') }}</h3>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.speedTestHint') }}</p>
      <div class="grid gap-3 md:grid-cols-2">
        <label class="form-control">
          <span class="label-text mb-1">{{ $t('obx.testUrl') }}</span>
          <input v-model="s.test_url" class="input input-bordered w-full rounded-full font-mono text-sm" @change="saveKey('test_url')" />
          <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.testUrlHint') }}</span>
        </label>
        <label class="form-control">
          <span class="label-text mb-1">{{ $t('obx.directTestUrl') }}</span>
          <input v-model="s.direct_test_url" class="input input-bordered w-full rounded-full font-mono text-sm" @change="saveKey('direct_test_url')" />
          <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.directTestUrlHint') }}</span>
        </label>
      </div>
      <label class="form-control mt-3 max-w-md">
        <span class="label-text mb-1">{{ $t('obx.acceptStatus') }}</span>
        <input v-model="s.test_expected" class="input input-bordered w-full rounded-full font-mono" placeholder="*" @change="saveKey('test_expected')" />
        <span class="label-text-alt mt-1 opacity-60">{{ $t('obx.acceptStatusHint') }}</span>
      </label>
    </div>

    <!-- 分析数据保留时长 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.retention') }}</h3>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.retentionHint') }}</p>
      <div class="flex items-center gap-2">
        <input v-model.number="s.retention_months" type="number" min="1" max="36" class="input input-bordered w-20 rounded-full" @change="saveKey('retention_months')" />
        <span class="text-sm">{{ $t('obx.monthUnit') }} 1–36,{{ $t('obx.default3') }}</span>
      </div>
      <p class="mt-1 text-xs opacity-60">{{ retentionInfo }}</p>
    </div>

    <!-- 时区 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.timezone') }}</h3>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.timezoneHint') }}</p>
      <select v-model="tz" class="select select-bordered w-full max-w-md" @change="saveTz">
        <option v-for="z in timezones" :key="z" :value="z">{{ z }}</option>
      </select>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.routerTime') }} {{ routerTime }}</p>
    </div>

    <!-- 导出与导入 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.exportImport') }}</h3>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.exportImportHint') }}</p>
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <button class="btn btn-sm" @click="doExport">⬇ {{ $t('obx.export') }}</button>
        <label class="flex cursor-pointer items-center gap-1 text-sm"><input v-model="expSubs" type="checkbox" class="checkbox checkbox-sm checkbox-success" /> {{ $t('obx.inclSubs') }}</label>
        <label class="flex cursor-pointer items-center gap-1 text-sm"><input v-model="expChains" type="checkbox" class="checkbox checkbox-sm checkbox-success" /> {{ $t('obx.inclChains') }}</label>
        <label class="flex cursor-pointer items-center gap-1 text-sm"><input v-model="expTerms" type="checkbox" class="checkbox checkbox-sm checkbox-success" /> {{ $t('obx.inclTerms') }}</label>
        <label class="flex cursor-pointer items-center gap-1 text-sm"><input v-model="expShare" type="checkbox" class="checkbox checkbox-sm checkbox-success" /> {{ $t('obx.inclShare') }}</label>
        <span class="text-xs opacity-60">{{ $t('obx.noPanelPass') }}</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn btn-sm" @click="triggerImport">⬆ {{ $t('obx.import') }}</button>
        <input ref="fileInput" type="file" accept=".json" class="hidden" @change="doImport" />
        <span class="text-xs opacity-60">{{ $t('obx.importHint') }}</span>
      </div>
    </div>

    <!-- 导出诊断包 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <h3 class="mb-1 font-bold">{{ $t('obx.diagPack') }}</h3>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.diagPackHint') }}</p>
      <div class="flex items-center gap-2">
        <button class="btn btn-success btn-sm" :disabled="diagBusy" @click="doDiag">⬇ {{ $t('obx.diagPack') }}</button>
        <span class="text-xs opacity-60">{{ $t('obx.diagSafe') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxGet, obxPost, obxPut } from '@/openbox/api'
import { onMounted, ref } from 'vue'

const err = ref('')
const s = ref<any>({
  install_channel: 'keep', sub_direct: true, direct_bypass: true, block_quic: true,
  ipv6: false, tun_stack: 'mixed', tun_mtu: '0', mss_clamp: '0',
  test_url: '', direct_test_url: '', test_expected: '*', retention_months: 3,
  bypass_ports: '', bypass_ports_white: '', port_list_mode: 'black',
})
const autoUpd = ref(false)
const kernelVer = ref('')
const kernelRunning = ref(false)
const autostart = ref(false)
const geoSite = ref('')
const geoIp = ref('')
const geoTime = ref('')
const opBusy = ref(false)
const checking = ref(false)
const updateInfo = ref('')
const portTab = ref('black')
const portInput = ref('')
const tunDlg = ref(false)
const tz = ref('Asia/Shanghai')
const routerTime = ref('')
const timezones = ref<string[]>(['Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Taipei', 'UTC'])
const retentionInfo = ref('')
const expSubs = ref(true)
const expChains = ref(true)
const expTerms = ref(false)
const expShare = ref(true)
const fileInput = ref<HTMLInputElement | null>(null)
const diagBusy = ref(false)

async function load() {
  err.value = ''
  try {
    const d = await obxGet<any>('/api/settings')
    for (const k of Object.keys(s.value)) {
      if (k in d) {
        const v = d[k]
        if (typeof s.value[k] === 'boolean') s.value[k] = v === '1' || v === true
        else s.value[k] = v
      }
    }
    autoUpd.value = d.auto_update === '1'
    portTab.value = d.port_list_mode || 'black'
    portInput.value = portTab.value === 'white' ? (d.bypass_ports_white || '') : (d.bypass_ports || '')
    try {
      const st = await obxGet<any>('/api/status')
      kernelVer.value = st.kernel_version || st.singbox_version || ''
      kernelRunning.value = !!st.kernel_running
      autostart.value = !!st.autostart
    } catch { /* ignore */ }
    try {
      const tzd = await obxGet<any>('/api/system/timezone')
      tz.value = tzd.timezone || 'Asia/Shanghai'
      routerTime.value = tzd.now || ''
    } catch { /* ignore */ }
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

function switchPortTab(t: string) {
  // 先保存当前输入
  const cur = portTab.value === 'white' ? 'bypass_ports_white' : 'bypass_ports'
  s.value[cur] = portInput.value
  portTab.value = t
  portInput.value = t === 'white' ? (s.value.bypass_ports_white || '') : (s.value.bypass_ports || '')
}
async function saveKey(k: string, v?: string) {
  try {
    const val = v !== undefined ? v : String((s.value as any)[k])
    await obxPut('/api/settings', { [k]: val })
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function saveBool(k: string) {
  await saveKey(k, (s.value as any)[k] ? '1' : '0')
}
async function savePorts() {
  const k = portTab.value === 'white' ? 'bypass_ports_white' : 'bypass_ports'
  s.value[k] = portInput.value
  await saveKey(k, portInput.value)
  await saveKey('port_list_mode', portTab.value)
}
async function kernelOp(op: string) {
  opBusy.value = true; err.value = ''
  try { await obxPost(`/api/kernel/${op}`, {}); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
  finally { opBusy.value = false }
}
async function checkUpdate() {
  checking.value = true; updateInfo.value = ''; err.value = ''
  try {
    const r = await obxPost<any>('/api/update/check', {})
    updateInfo.value = r.message || r.version || '已是最新'
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '检查失败' }
  finally { checking.value = false }
}
async function saveTz() {
  try { await obxPut('/api/system/timezone', { timezone: tz.value }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function doExport() {
  try {
    const r = await obxPost<any>('/api/export', {
      subs: expSubs.value, chains: expChains.value, terms: expTerms.value, share: expShare.value,
    })
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `openbox-export-${Date.now()}.json`
    a.click()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '导出失败' }
}
function triggerImport() { fileInput.value?.click() }
async function doImport(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  try {
    const text = await f.text()
    await obxPost('/api/import', JSON.parse(text))
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '导入失败' }
}
async function doDiag() {
  diagBusy.value = true; err.value = ''
  try {
    const r = await obxGet<any>('/api/diagnostics')
    const blob = new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `openbox-diag-${Date.now()}.json`
    a.click()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '导出失败' }
  finally { diagBusy.value = false }
}

onMounted(load)
</script>
