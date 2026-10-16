<!-- Open-Box 二开：DNS 设置（1:1 对标原版） -->
<template>
  <div class="flex flex-col gap-3">
    <div
      v-if="err"
      class="alert alert-error"
    >
      <span>{{ err }}</span>
    </div>

    <!-- DNS 劫持 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="font-bold">{{ $t('obx.dnsHijack') }} <span class="text-xs font-normal opacity-60">(DNS{{ $t('obx.port') }}:7853)</span></h3>
        <select v-model="f.mode" class="select select-bordered select-sm" @change="saveMode">
          <option value="dnsmasq">{{ $t('obx.dnsmasqForward') }}</option>
          <option value="firewall">{{ $t('obx.dnsFirewall') }}</option>
          <option value="off">{{ $t('obx.dnsOff') }}</option>
        </select>
      </div>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.dnsHijackDesc') }}</p>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.dnsHijackDesc2') }}</p>
      <label class="flex cursor-pointer items-center gap-3">
        <input v-model="f.fakeip" type="checkbox" class="toggle toggle-success" @change="saveFakeip" />
        <span class="text-sm">{{ $t('obx.enableFakeIp') }}</span>
      </label>
      <p class="mt-1 text-xs opacity-60">{{ $t('obx.fakeIpDetail') }}</p>
    </div>

    <!-- DNS 上游 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="font-bold">{{ $t('obx.dnsUpstream') }}</h3>
        <div class="flex gap-1">
          <button class="btn btn-ghost btn-sm btn-square" :title="$t('obx.reset')" @click="resetUpstream">↩</button>
          <button class="btn btn-success btn-sm btn-square" @click="openUpstreamAdd">+</button>
        </div>
      </div>
      <p class="mb-3 text-xs opacity-60">{{ $t('obx.dnsUpstreamDesc') }}</p>

      <!-- 路由器在 -->
      <div class="mb-2 flex items-center gap-2">
        <span class="text-sm">{{ $t('obx.routerIn') }}</span>
        <button
          type="button"
          class="btn btn-sm rounded-full"
          :class="regionTab === 'cn' ? 'btn-success' : 'btn-ghost'"
          @click="askSwitchRegion('cn')"
        >
          {{ $t('obx.regionCn') }}
        </button>
        <button
          type="button"
          class="btn btn-sm rounded-full"
          :class="regionTab === 'outside' ? 'btn-success' : 'btn-ghost'"
          @click="askSwitchRegion('outside')"
        >
          {{ $t('obx.regionOutside') }}
        </button>
      </div>
      <p class="mb-3 text-xs opacity-60">
        {{ regionTab === 'cn' ? $t('obx.regionCnDesc') : $t('obx.regionOutsideDesc') }}
      </p>

      <!-- 直连 DNS -->
      <div class="mb-1 text-xs opacity-60">
        <span class="badge badge-ghost badge-sm">{{ $t('obx.directDns') }}</span>
      </div>
      <div v-for="(u, i) in directList" :key="'d'+i" class="flex items-center gap-2 border-b border-base-200 py-2">
        <span class="flex-1 font-mono text-sm">{{ u.label }}</span>
        <button class="btn btn-ghost btn-xs" @click="testOne(u)">⚡</button>
        <button class="btn btn-ghost btn-xs" @click="openUpstreamEdit('direct', i)">✎</button>
        <button class="btn btn-ghost btn-xs text-error" @click="delUpstream('direct', i)">🗑</button>
      </div>
      <!-- 代理 DNS -->
      <div class="mb-1 mt-3 text-xs opacity-60">
        <span class="badge badge-ghost badge-sm">{{ $t('obx.proxyDns') }}</span>
      </div>
      <div v-for="(u, i) in proxyList" :key="'p'+i" class="flex items-center gap-2 border-b border-base-200 py-2">
        <span class="flex-1 font-mono text-sm">{{ u.label }}<span v-if="(u as any).directNote" class="ml-2 text-xs opacity-60">{{ $t('obx.directNoProxy') }}</span></span>
        <button class="btn btn-ghost btn-xs" @click="testOne(u)">⚡</button>
        <button class="btn btn-ghost btn-xs" @click="openUpstreamEdit('proxy', i)">✎</button>
        <button class="btn btn-ghost btn-xs text-error" @click="delUpstream('proxy', i)">🗑</button>
      </div>
      <p class="mt-2 text-xs opacity-60">{{ $t('obx.upstreamFormatHint') }}</p>
    </div>

    <!-- 地区切换确认框 -->
    <div v-if="regionConfirm" class="modal modal-open">
      <div class="modal-box">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.confirm') }}</h3>
          <button class="btn btn-ghost btn-sm btn-square" @click="regionConfirm = null">✕</button>
        </div>
        <p class="text-sm">{{ regionConfirm.text }}</p>
        <div class="modal-action">
          <button class="btn btn-ghost" @click="regionConfirm = null">{{ $t('obx.cancel') }}</button>
          <button class="btn btn-error" @click="doSwitchRegion()">{{ $t('obx.confirm') }}</button>
        </div>
      </div>
    </div>

    <!-- 上游编辑框 -->
    <div v-if="upDlg" class="modal modal-open">
      <div class="modal-box">
        <h3 class="mb-3 text-lg font-bold">{{ upDlg.isNew ? $t('obx.add') : $t('obx.edit') }} {{ upDlg.side === 'direct' ? $t('obx.directDns') : $t('obx.proxyDns') }}</h3>
        <div class="flex flex-col gap-2">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.protocol') }}</span>
            <select v-model="upDlg.proto" class="select select-bordered w-full">
              <option value="udp">UDP</option>
              <option value="tcp">TCP</option>
              <option value="tls">TLS</option>
              <option value="https">HTTPS</option>
            </select>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.address') }}</span>
            <input v-model="upDlg.addr" class="input input-bordered w-full font-mono" placeholder="223.5.5.5 或 上游 DNS" />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.port') }}</span>
            <input v-model.number="upDlg.port" type="number" class="input input-bordered w-full" />
          </label>
        </div>
        <div class="modal-action">
          <button class="btn btn-ghost" @click="upDlg = null">{{ $t('obx.cancel') }}</button>
          <button class="btn btn-success" @click="saveUpstream()">{{ $t('obx.save') }}</button>
        </div>
      </div>
    </div>

    <!-- DNS 重写 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="font-bold">{{ $t('obx.dnsRewrite') }}</h3>
        <div class="flex items-center gap-2">
          <label class="flex cursor-pointer items-center gap-2">
            <input v-model="rewriteEnabled" type="checkbox" class="toggle toggle-success toggle-sm" />
            <span class="badge badge-ghost badge-sm">{{ rewriteEnabled ? $t('obx.enabled') : $t('obx.disabled') }}</span>
          </label>
          <button class="btn btn-ghost btn-sm btn-square" @click="resetRewrite">↩</button>
          <button class="btn btn-success btn-sm btn-square" @click="openRewriteAdd">+</button>
        </div>
      </div>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.rewriteDesc') }}</p>
      <div v-for="r in rewrites" :key="r.id" class="flex items-center gap-2 border-b border-base-200 py-2">
        <input type="checkbox" class="toggle toggle-success toggle-sm" :checked="!!r.enabled" @change="toggleRewrite(r)" />
        <span class="flex-1 font-mono text-sm">{{ r.domain }} - {{ r.target }}</span>
        <button class="btn btn-ghost btn-xs" @click="openRewriteEdit(r)">✎</button>
        <button class="btn btn-ghost btn-xs text-error" @click="delRewrite(r)">🗑</button>
      </div>
      <p class="mt-2 text-xs opacity-60">{{ $t('obx.rewriteHint') }}</p>
    </div>

    <!-- 域名过滤 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="font-bold">{{ $t('obx.domainFilter') }}</h3>
        <div class="flex items-center gap-2">
          <label class="flex cursor-pointer items-center gap-2">
            <input v-model="filterEnabled" type="checkbox" class="toggle toggle-success toggle-sm" @change="saveFilterEnabled" />
            <span class="badge badge-ghost badge-sm">{{ filterEnabled ? $t('obx.enabled') : $t('obx.disabled') }}</span>
          </label>
          <button class="btn btn-ghost btn-sm btn-square" @click="loadFilter">↻</button>
          <button class="btn btn-success btn-sm btn-square" @click="openFilterAdd">+</button>
        </div>
      </div>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.filterDesc') }}</p>
      <div v-for="fl in filters" :key="fl.id" class="flex items-center gap-2 border-b border-base-200 py-2">
        <input type="checkbox" class="toggle toggle-success toggle-sm" :checked="!!fl.enabled" @change="toggleFilter(fl)" />
        <span class="flex-1 text-sm">{{ fl.name }} <span class="font-mono text-xs opacity-60">{{ fl.url }}</span></span>
        <span v-if="fl.count" class="text-xs opacity-60">{{ $t('obx.rulesCount', { n: fl.count }) }}</span>
        <button class="btn btn-ghost btn-xs" @click="previewFilter(fl)">👁</button>
        <button class="btn btn-ghost btn-xs" @click="refreshFilter(fl)">↻</button>
        <button class="btn btn-ghost btn-xs" @click="openFilterEdit(fl)">✎</button>
        <button class="btn btn-ghost btn-xs text-error" @click="delFilter(fl)">🗑</button>
      </div>
    </div>

    <!-- 域名解析查询 -->
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="font-bold">{{ $t('obx.dnsQueryLog') }}</h3>
        <div class="flex gap-2">
          <input v-model="qSearch" class="input input-bordered input-sm" :placeholder="$t('obx.searchDomain')" />
          <select v-model="qFilter" class="select select-bordered select-sm">
            <option value="">{{ $t('obx.all') }}</option>
            <option value="blocked">{{ $t('obx.blocked') }}</option>
          </select>
          <button class="btn btn-ghost btn-sm btn-square" @click="loadQueryLog">↻</button>
        </div>
      </div>
      <p class="mb-2 text-xs opacity-60">{{ $t('obx.queryLogDesc') }}</p>
      <div class="overflow-x-auto">
        <table class="table table-sm">
          <thead>
            <tr>
              <th>{{ $t('obx.time') }}</th>
              <th>{{ $t('obx.domain') }}</th>
              <th>{{ $t('obx.type') }}</th>
              <th>{{ $t('obx.result') }}</th>
              <th>{{ $t('obx.device') }}</th>
              <th>{{ $t('obx.hitList') }}</th>
              <th>{{ $t('obx.latency') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(q, i) in filteredQueryLog" :key="i">
              <td class="font-mono text-xs">{{ q.time }}</td>
              <td class="font-mono text-xs">{{ q.domain }}</td>
              <td class="text-xs">{{ q.qtype }}</td>
              <td><span class="badge badge-sm" :class="q.blocked ? 'badge-error' : 'badge-ghost'">{{ q.blocked ? $t('obx.blocked') : q.result }}</span></td>
              <td class="text-xs">{{ q.device }}</td>
              <td class="text-xs">{{ q.list }}</td>
              <td class="text-xs">{{ q.latency }}</td>
            </tr>
            <tr v-if="!filteredQueryLog.length">
              <td colspan="7" class="text-center opacity-60">{{ $t('obx.noData') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const err = ref('')

// 基础
const f = ref({ mode: 'dnsmasq', fakeip: false })
const regionTab = ref('cn')

// 上游
type Up = { proto: string; addr: string; port: number; label: string; isUpstream?: boolean }
const directList = ref<Up[]>([])
const proxyList = ref<Up[]>([])
const regionConfirm = ref<null | { to: string; text: string }>(null)
const upDlg = ref<null | { isNew: boolean; side: string; idx: number; proto: string; addr: string; port: number }>(null)

function parseUpstream(s: string): Up {
  // 格式: [proto://]addr[:port] 或 "上游 DNS"
  s = (s || '').trim()
  let proto = 'udp', addr = s, port = 53, isUpstream = false
  if (s.includes('上游 DNS')) {
    isUpstream = true
    // "上游 DNS 223.5.5.5" -> addr=223.5.5.5
    const am = s.match(/上游 DNS\s*(.*)/)
    addr = (am && am[1].trim()) || 'wan'
  } else {
    const m = s.match(/^(udp|tcp|tls|https):\/\/(.+)$/i)
    if (m) { proto = m[1].toLowerCase(); addr = m[2] }
    const pm = addr.match(/^(.*):(\d+)$/)
    if (pm && !addr.includes('://')) { addr = pm[1]; port = parseInt(pm[2]) }
    if (proto === 'tls' && port === 53) port = 853
    if (proto === 'https' && port === 53) port = 443
  }
  let label: string
  if (isUpstream) {
    label = `${t('obx.upstreamDns')}${addr && addr !== 'wan' ? ' ' + addr : ''}`
  } else {
    label = `${proto.toUpperCase()} ${addr}`
    const defaultPort = proto === 'tls' ? 853 : proto === 'https' ? 443 : 53
    if (port !== defaultPort) label += `:${port}`
    else if (proto !== 'udp') label += `:${port}`
  }
  return { proto, addr, port, label, isUpstream }
}
function fmtUpstream(u: any): string {
  if (u.isUpstream) return `上游 DNS${u.addr && u.addr !== 'wan' ? ' ' + u.addr : ''}`.trim()
  const defaultPort = u.proto === 'tls' ? 853 : u.proto === 'https' ? 443 : 53
  let s = ''
  if (u.proto !== 'udp') s += `${u.proto}://`
  s += u.addr
  if (u.port !== defaultPort) s += `:${u.port}`
  else if (u.proto !== 'udp') s += `:${u.port}`
  return s
}

// 重写
const rewrites = ref<any[]>([])
const rewriteEnabled = ref(true)

// 过滤
const filters = ref<any[]>([])
const filterEnabled = ref(false)

// 查询日志
const queryLog = ref<any[]>([])
const qSearch = ref('')
const qFilter = ref('')
const filteredQueryLog = computed(() => {
  let list = queryLog.value
  if (qSearch.value) list = list.filter((q) => (q.domain || '').includes(qSearch.value.trim()))
  if (qFilter.value === 'blocked') list = list.filter((q) => q.blocked)
  return list
})

async function load() {
  err.value = ''
  try {
    const d = await obxGet<any>('/api/dns')
    f.value = { mode: d.mode || 'dnsmasq', fakeip: !!d.fakeip }
    regionTab.value = d.region === 'outside' ? 'outside' : 'cn'
    const toList = (s: string) => (s || '').split(',').map((x) => x.trim()).filter(Boolean).map(parseUpstream)
    directList.value = toList(d.direct_dns)
    proxyList.value = toList(d.proxy_dns)
    rewrites.value = d.rewrites || []
    await loadFilter()
    await loadQueryLog()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

async function saveMode() {
  try { await obxPut('/api/dns', { mode: f.value.mode }) }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function saveFakeip() {
  try { await obxPut('/api/dns', { fakeip: f.value.fakeip }) }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}

// 地区切换
function askSwitchRegion(to: string) {
  if (to === regionTab.value) return
  const text = to === 'outside'
    ? t('obx.switchOutsideConfirm')
    : t('obx.switchCnConfirm')
  regionConfirm.value = { to, text }
}
async function doSwitchRegion() {
  if (!regionConfirm.value) return
  const to = regionConfirm.value.to
  regionConfirm.value = null
  try {
    // 按原版：两侧换成默认值，备用清空
    if (to === 'outside') {
      directList.value = [parseUpstream('上游 DNS 223.5.5.5')]
      const p = parseUpstream('上游 DNS 223.5.5.5')
      ;(p as any).directNote = true
      proxyList.value = [p]
    } else {
      directList.value = [parseUpstream('上游 DNS 223.5.5.5')]
      proxyList.value = [parseUpstream('tcp://1.1.1.1:53')]
    }
    regionTab.value = to
    await saveUpstreams()
    await obxPut('/api/dns', { region: to })
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}

async function saveUpstreams() {
  const direct_dns = directList.value.map(fmtUpstream).join(',')
  const proxy_dns = proxyList.value.map(fmtUpstream).join(',')
  await obxPut('/api/dns', { direct_dns, proxy_dns })
}

// 上游 CRUD
function openUpstreamAdd() {
  // 默认加到直连
  upDlg.value = { isNew: true, side: 'direct', idx: -1, proto: 'udp', addr: '', port: 53 }
}
function openUpstreamEdit(side: string, idx: number) {
  const u = side === 'direct' ? directList.value[idx] : proxyList.value[idx]
  upDlg.value = { isNew: false, side, idx, proto: u.proto, addr: u.addr, port: u.port }
}
async function saveUpstream() {
  if (!upDlg.value || !upDlg.value.addr.trim()) return
  const addrTrim = upDlg.value.addr.trim()
  const isUp = addrTrim.includes('上游 DNS') || addrTrim === 'wan'
  const u: Up = { proto: upDlg.value.proto, addr: addrTrim.replace('上游 DNS', '').trim() || 'wan', port: upDlg.value.port, label: '', isUpstream: isUp }
  u.label = fmtUpstream(u)
  const list = upDlg.value.side === 'direct' ? directList.value : proxyList.value
  if (list.length >= 4 && upDlg.value.isNew) { err.value = t('obx.maxUpstream'); return }
  if (upDlg.value.isNew) list.push(u)
  else list[upDlg.value.idx] = u
  upDlg.value = null
  try { await saveUpstreams() } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function delUpstream(side: string, idx: number) {
  const list = side === 'direct' ? directList.value : proxyList.value
  list.splice(idx, 1)
  try { await saveUpstreams() } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function resetUpstream() {
  await doSwitchRegionReset()
}
async function doSwitchRegionReset() {
  // 重置为当前地区的默认值
  if (regionTab.value === 'outside') {
    directList.value = [parseUpstream('上游 DNS 223.5.5.5')]
    const p = parseUpstream('上游 DNS 223.5.5.5')
    ;(p as any).directNote = true
    proxyList.value = [p]
  } else {
    directList.value = [parseUpstream('上游 DNS 223.5.5.5')]
    proxyList.value = [parseUpstream('tcp://1.1.1.1:53')]
  }
  try { await saveUpstreams() } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function testOne(u: Up) {
  try {
    await obxPost('/api/dns/upstream-test', { upstream: fmtUpstream(u) })
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '测速失败' }
}

// 重写
async function toggleRewrite(r: any) {
  try { await obxPut(`/api/dns/rewrite/${r.id}`, { enabled: r.enabled ? 0 : 1 }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}
async function delRewrite(r: any) {
  try { await obxDel(`/api/dns/rewrite/${r.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}
function openRewriteAdd() { /* TODO */ }
function openRewriteEdit(r: any) { /* TODO */ }
function resetRewrite() { /* TODO */ }

// 过滤
async function loadFilter() {
  try {
    const d = await obxGet<any>('/api/dns/filter')
    filters.value = d.lists || d.filters || []
    filterEnabled.value = !!d.enabled
  } catch { /* 忽略 */ }
}
async function saveFilterEnabled() {
  try { await obxPut('/api/dns/filter', { enabled: filterEnabled.value }) }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
function toggleFilter(fl: any) { /* TODO */ }
function previewFilter(fl: any) { /* TODO */ }
function refreshFilter(fl: any) { /* TODO */ }
function openFilterAdd() { /* TODO */ }
function openFilterEdit(fl: any) { /* TODO */ }
function delFilter(fl: any) { /* TODO */ }

// 查询日志
async function loadQueryLog() {
  try {
    const d = await obxGet<any>('/api/dns/query-log')
    queryLog.value = d.logs || d.records || []
  } catch { /* 忽略 */ }
}

onMounted(load)
</script>
