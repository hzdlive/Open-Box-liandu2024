<template>
  <div class="flex flex-col gap-3 p-3">
    <!-- 顶部 Tab：策略 / 节点 / 订阅（zashboard SegmentedControl 风格） -->
    <div class="flex items-center gap-2 flex-wrap">
      <SegmentedControl
        v-model="activeTab"
        :options="tabOptions"
      />
      <div class="ml-auto relative">
        <input
          v-model="searchText"
          class="input input-bordered input-sm rounded-full w-70 pr-8"
          placeholder="搜索 | 多个关键词用空格分隔"
        />
        <span
          v-if="searchText"
          class="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer opacity-50 hover:opacity-100"
          @click="searchText = ''"
        >×</span>
      </div>
    </div>

    <!-- 策略 Tab：站点集 -->
    <div v-if="activeTab === 'policy'" class="flex flex-col gap-3">
      <div
        v-for="site in filteredPolicies"
        :key="site.id"
        class="rounded-box border border-base-300/30 bg-base-100 p-4"
      >
        <div class="flex items-center gap-3 cursor-pointer" @click="toggleExpand('policy', site.id)">
          <div class="text-3xl leading-none">{{ mapIcon(site.icon, site.name) }}</div>
          <div class="flex-1 flex items-center gap-2 flex-wrap">
            <span class="text-base font-semibold">{{ site.name }}</span>
            <span class="badge badge-success badge-sm">域名穿透</span>
            <span class="text-sm opacity-60">Selector ({{ site.matched }}/{{ site.total }})</span>
          </div>
          <div class="badge" :class="latencyClass(site.latency)">{{ site.latency }}</div>
        </div>
        <div class="mt-2 text-sm opacity-70">
          <span>🌍 {{ site.currentGroup }}</span>
          <span v-if="site.currentNode"> ⊕ {{ site.currentNode }}</span>
        </div>
        <div class="mt-2 flex gap-1.5">
          <span
            v-for="(d, i) in site.dots"
            :key="i"
            class="w-3 h-3 rounded-full bg-base-300"
            :class="dotClass(d)"
          ></span>
        </div>
        <!-- 展开：出站选项 -->
        <div v-if="expanded.policy === site.id" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="opt in site.options"
            :key="opt.name"
            class="rounded-box border p-3 cursor-pointer transition-colors hover:border-success"
            :class="opt.name === site.selected
              ? 'bg-success text-success-content border-success'
              : 'border-base-300/50 bg-base-100'"
            @click="selectPolicyOutbound(site, opt)"
          >
            <div class="text-sm font-medium">{{ opt.icon }} {{ opt.name }}</div>
            <div class="text-xs opacity-60 mt-1">
              {{ opt.type }} / udp
              <span class="badge badge-sm ml-1" :class="opt.name === site.selected ? 'badge-ghost' : latencyClass(opt.latency)">{{ opt.latency }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 节点 Tab：节点组 -->
    <div v-if="activeTab === 'node'" class="flex flex-col gap-3">
      <div
        v-for="group in filteredNodes"
        :key="group.name"
        class="rounded-box border border-base-300/30 bg-base-100 p-4"
      >
        <div class="flex items-center gap-3 cursor-pointer" @click="toggleExpand('node', group.name)">
          <div class="text-3xl leading-none">{{ group.icon || '🎯' }}</div>
          <div class="flex-1 flex items-center gap-2 flex-wrap">
            <span class="text-base font-semibold">{{ group.name }}</span>
            <span class="text-sm opacity-60">{{ group.typeLabel }} ({{ group.alive }}/{{ group.total }})</span>
          </div>
          <button
            v-if="group.isFailover"
            class="btn btn-ghost btn-xs"
            title="故障转移检测"
            @click.stop="recheckFailover(group)"
          >⚡</button>
          <div class="badge" :class="latencyClass(group.latency)">{{ group.latency }}</div>
        </div>
        <div class="mt-1 text-sm opacity-70">{{ group.now }}</div>
        <div class="mt-1 text-xs opacity-50 text-right">检测间隔 {{ group.interval }} 秒 · 容差 {{ group.tolerance }} 毫秒</div>
        <div class="mt-2 flex gap-1.5">
          <span v-for="(d, i) in group.dots" :key="i" class="w-3 h-3 rounded-full bg-base-300" :class="dotClass(d)"></span>
        </div>
        <!-- 展开：成员节点 -->
        <div v-if="expanded.node === group.name" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="m in group.members"
            :key="m.name"
            class="rounded-box border p-3 cursor-pointer transition-colors hover:border-success"
            :class="m.name === group.now
              ? 'bg-success text-success-content border-success'
              : 'border-base-300/50 bg-base-100'"
            @click="selectNode(group, m)"
          >
            <div class="text-sm font-medium">{{ m.name }}</div>
            <div class="text-xs opacity-60 mt-1">
              {{ m.protocol }} / udp
              <span class="badge badge-sm ml-1" :class="m.name === group.now ? 'badge-ghost' : latencyClass(m.latency)">{{ m.latency }}</span>
            </div>
          </div>
        </div>
        <!-- 故障转移：车道 -->
        <div v-if="group.isFailover && expanded.node === group.name" class="mt-3">
          <div v-for="lane in group.lanes" :key="lane.name" class="mb-3">
            <div class="text-sm font-semibold mb-2 opacity-80">{{ lane.name }} ({{ lane.alive }}/{{ lane.total }})</div>
            <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <div
                v-for="m in lane.members"
                :key="m.name"
                class="rounded-box border p-3"
                :class="m.selected
                  ? 'bg-success text-success-content border-success'
                  : 'border-base-300/50 bg-base-100'"
              >
                <div class="text-sm font-medium">{{ m.name }}</div>
                <div class="text-xs opacity-60 mt-1">
                  {{ m.protocol }} / udp
                  <span class="badge badge-sm ml-1" :class="m.selected ? 'badge-ghost' : latencyClass(m.latency)">{{ m.latency }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="group.switchHistory" class="text-xs opacity-50 mt-2">
            最近切换：{{ group.switchHistory }}
          </div>
        </div>
      </div>
    </div>

    <!-- 订阅 Tab -->
    <div v-if="activeTab === 'sub'" class="flex flex-col gap-3">
      <div
        v-for="sub in filteredSubs"
        :key="sub.id"
        class="rounded-box border border-base-300/30 bg-base-100 p-4"
      >
        <div class="flex items-center gap-3 cursor-pointer" @click="toggleExpand('sub', sub.id)">
          <div class="flex-1 flex items-center gap-2">
            <span class="text-base font-semibold">{{ sub.name }} ({{ sub.alive }}/{{ sub.total }})</span>
          </div>
          <div class="flex gap-1">
            <button class="btn btn-ghost btn-sm text-lg" @click.stop="speedtestSub(sub)" title="测速">⚡</button>
            <button class="btn btn-ghost btn-sm text-lg" @click.stop="refreshSub(sub)" title="刷新">🔄</button>
          </div>
        </div>
        <div class="mt-1 text-xs opacity-50">更新于 {{ sub.updated }} · {{ sub.traffic }}</div>
        <div class="mt-2 flex gap-1.5">
          <span v-for="(d, i) in sub.dots" :key="i" class="w-3 h-3 rounded-full bg-base-300" :class="dotClass(d)"></span>
        </div>
        <div v-if="expanded.sub === sub.id" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div
            v-for="m in sub.nodes"
            :key="m.name"
            class="rounded-box border border-base-300/50 bg-base-100 p-3"
          >
            <div class="text-sm font-medium">{{ m.name }}</div>
            <div class="text-xs opacity-60 mt-1">
              {{ m.protocol }} / udp
              <span class="badge badge-sm ml-1" :class="latencyClass(m.latency)">{{ m.latency }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { obxGet, obxPost } from '../api'
import SegmentedControl from '@/components/common/SegmentedControl.vue'

// 图标映射：原版的 icon 标识符 -> emoji
function mapIcon(iconId: string | undefined, name: string): string {
  if (!iconId) {
    // 按名称猜
    const n = name.toLowerCase()
    if (n.includes('youtube')) return '▶️'
    if (n.includes('tiktok')) return '🎵'
    if (n.includes('netflix')) return '🎬'
    if (n.includes('github')) return '🐙'
    if (n.includes('google')) return '🔍'
    if (n.includes('apple')) return '🍎'
    if (n.includes('microsoft')) return '🪟'
    if (n.includes('ai') || n.includes('openai')) return '🤖'
    if (n.includes('game')) return '🎮'
    if (n.includes('speed')) return '⏱️'
    return '🌐'
  }
  // brand:xxx / misc:xxx 格式
  const parts = iconId.split(':')
  const key = parts[1] || ''
  const iconMap: Record<string, string> = {
    'stopwatch': '⏱️',
    'openai-light': '🤖',
    'youtube': '▶️',
    'tiktok': '🎵',
    'netflix-mono': '🎬',
    'github-mono': '🐙',
    'google': '🔍',
    'apple': '🍎',
    'microsoft': '🪟',
    'game': '🎮',
    'globe': '🌐',
    'shield': '🛡️',
  }
  return iconMap[key] || '🌐'
}

// 延迟徽章颜色：按数值分档
function latencyClass(lat: string | number | undefined): string {
  const n = typeof lat === 'string' ? parseInt(lat) : (lat ?? NaN)
  if (isNaN(n)) return 'badge-ghost'
  if (n <= 0) return 'badge-ghost'
  if (n < 150) return 'badge-success'
  if (n < 300) return 'badge-warning'
  return 'badge-error'
}

// 状态圆点颜色
function dotClass(d: string): string {
  if (d === 'ok') return 'bg-success'
  if (d === 'warn') return 'bg-warning'
  if (d === 'err') return 'bg-error'
  return ''
}

// Tab 定义
const tabs = [
  { key: 'policy', label: '策略', count: ref(0) },
  { key: 'node', label: '节点', count: ref(8) },
  { key: 'sub', label: '订阅', count: ref(0) },
]
const activeTab = ref('policy')
const searchText = ref('')
const expanded = ref({ policy: null as string | null, node: null as string | null, sub: null as string | null })

// 数据
const policies = ref<any[]>([])
const nodes = ref<any[]>([])
const subs = ref<any[]>([])

// 加载策略（站点集）：合并 sitesets 数据与 clash flip 选择器状态
async function loadPolicies() {
  try {
    const [sitesData, clashData] = await Promise.all([
      obxGet<any>('/api/sitesets'),
      obxGet<any>('/api/openbox/clash-proxies').catch(() => ({ proxies: {} })),
    ])
    const list = Array.isArray(sitesData) ? sitesData : (sitesData.sitesets || [])
    const proxies = clashData.proxies || {}
    policies.value = list.map((s: any, idx: number) => {
      // flip 选择器 tag: flip-<id> 或 flip-<name>
      const flipTag = `flip-${s.id}`
      const flipInfo = proxies[flipTag] || {}
      const all = flipInfo.all || []
      return {
        id: s.id,
        name: s.name,
        icon: s.icon,
        matched: all.length || 0,
        total: all.length || 0,
        latency: flipInfo.latency || 68,
        currentGroup: s.group || '所有-自动',
        currentNode: flipInfo.now || '',
        dots: [],
        options: all.map((name: string) => {
          const p = proxies[name] || {}
          return { name, type: p.type || 'selector', latency: p.latency || '', icon: '🎯' }
        }),
        selected: flipInfo.now || '',
        flipTag,
      }
    })
    tabs[0].count.value = policies.value.length
  } catch (e) {
    console.error('load policies failed', e)
  }
}

// 加载节点组（从 clash API）：故障转移组做归集，lane 子组不单独显示
async function loadNodes() {
  try {
    // 经后端代理获取 clash proxies
    const [clashData, groupsData, healthData] = await Promise.all([
      obxGet<any>('/api/openbox/clash-proxies'),
      obxGet<any>('/api/groups').catch(() => []),
      obxGet<any[]>('/api/health').catch(() => []),
    ])
    const proxies = clashData.proxies || {}
    // 健康数据：tag -> 是否存活（latency_ms > 0）
    const aliveSet = new Set<string>()
    for (const h of healthData || []) {
      if (h.tag && h.latency_ms != null && Number(h.latency_ms) > 0) {
        aliveSet.add(h.tag)
      }
    }
    const dbGroups = Array.isArray(groupsData) ? groupsData : (groupsData.groups || [])
    // 找出故障转移组
    const failoverNames = new Set(
      dbGroups.filter((g: any) => g.type === 'failover').map((g: any) => g.name)
    )
    const groups: any[] = []
    // 先收集 lane 子组
    const laneMap: Record<string, any[]> = {}
    for (const [name, info] of Object.entries(proxies as Record<string, any>)) {
      if (name.includes('#')) {
        const [parent] = name.split('#')
        if (!laneMap[parent]) laneMap[parent] = []
        laneMap[parent].push({ name, info })
      }
    }
    for (const [name, info] of Object.entries(proxies as Record<string, any>)) {
      // 跳过内部 flip 选择器、lane 子组、__fo: 故障转移内部出站和 sub- 订阅出站组
      if (name.startsWith('flip-') || name.startsWith('obflip-') || name.startsWith('__fo:') || name.startsWith('sub-')) continue
      if (name.includes('#')) continue
      if (info.type === 'Selector' || info.type === 'URLTest') {
        const isFailover = failoverNames.has(name)
        const lanes = (laneMap[name] || []).map(({ name: laneTag, info: laneInfo }: any) => {
          const laneName = laneTag.split('#')[1]
          const laneMembers = laneInfo.all || []
          return {
            name: laneName,
            tag: laneTag,
            alive: laneMembers.filter((m: string) => aliveSet.has(m)).length,
            total: laneMembers.length,
            members: (laneInfo.all || []).map((m: string) => {
              const p = proxies[m] || {}
              return { name: m, protocol: p.type || '', latency: p.latency || '', selected: laneInfo.now === m }
            }),
            now: laneInfo.now || '',
          }
        })
        const members = info.all || []
        const aliveCount = members.filter((m: string) => aliveSet.has(m)).length
        groups.push({
          name,
          typeLabel: isFailover ? '故障转移' : (info.type === 'URLTest' ? 'URLTest' : 'Selector'),
          alive: aliveCount,
          total: members.length,
          latency: info.latency || '',
          now: info.now || '',
          interval: info.interval || 300,
          tolerance: info.tolerance || 100,
          dots: info.dots || [],
          members: (info.all || []).map((m: string) => {
            const p = proxies[m] || {}
            return { name: m, protocol: p.type || '', latency: p.latency || '' }
          }),
          isFailover,
          lanes,
          switchHistory: info.switchHistory || '',
        })
      }
    }
    nodes.value = groups
    tabs[1].count.value = groups.length
  } catch (e) {
    console.error('load nodes failed', e)
  }
}

// 故障转移手动检测
async function recheckFailover(group: any) {
  try {
    const res = await obxPost('/api/openbox/failover/recheck', { groupId: group.name })
    // 刷新数据
    await loadNodes()
  } catch (e) {
    console.error('failover recheck failed', e)
  }
}
// 加载订阅
async function loadSubs() {
  try {
    const data = await obxGet<any>('/api/subscriptions')
    const list = Array.isArray(data) ? data : (data.subscriptions || [])
    // 并行获取每个订阅的节点
    subs.value = await Promise.all(list.map(async (s: any) => {
      let nodes: any[] = []
      try {
        const nd = await obxGet<any>(`/api/subscriptions/${s.id}/nodes`)
        nodes = Array.isArray(nd) ? nd : (nd.nodes || [])
      } catch {}
      return {
        id: s.id,
        name: s.name,
        alive: s.node_count || 0,
        total: s.node_total || s.node_count || 0,
        updated: s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN') : '',
        traffic: s.userinfo || '',
        dots: [],
        nodes: nodes.map((n: any) => ({
          name: n.tag || n.name,
          protocol: n.protocol || n.type || '',
          latency: n.latency || '',
        })),
      }
    }))
    tabs[2].count.value = subs.value.length
  } catch (e) {
    console.error('load subs failed', e)
  }
}

function toggleExpand(tab: string, id: string) {
  const key = tab as keyof typeof expanded.value
  expanded.value[key] = expanded.value[key] === id ? null : id
}

async function selectPolicyOutbound(site: any, opt: any) {
  // 调用后端切换站点集出站
  try {
    await obxPost(`/api/sitesets/${site.id}/select`, { outbound: opt.name })
    site.selected = opt.name
  } catch (e) {
    console.error('select failed', e)
  }
}

async function selectNode(group: any, member: any) {
  try {
    await obxPost('/api/openbox/clash-select', { group: group.name, name: member.name })
    group.now = member.name
  } catch (e) {
    console.error('select node failed', e)
  }
}

async function speedtestSub(sub: any) {
  try {
    await obxPost(`/api/subscriptions/${sub.id}/speedtest`, {})
  } catch (e) {
    console.error('speedtest failed', e)
  }
}

async function refreshSub(sub: any) {
  try {
    await obxPost(`/api/subscriptions/${sub.id}/refresh`, {})
    loadSubs()
  } catch (e) {
    console.error('refresh failed', e)
  }
}

// Tab 选项（SegmentedControl 格式）
const tabOptions = computed(() => tabs.map((t) => ({
  value: t.key,
  label: t.label,
  count: t.count.value,
})))

// 搜索过滤
const filteredPolicies = computed(() => {
  if (!searchText.value) return policies.value
  const keys = searchText.value.split(' ').filter(Boolean)
  return policies.value.filter((p: any) =>
    keys.every((k: string) => p.name.includes(k))
  )
})
const filteredNodes = computed(() => {
  if (!searchText.value) return nodes.value
  const keys = searchText.value.split(' ').filter(Boolean)
  return nodes.value.filter((g: any) =>
    keys.every((k: string) => g.name.includes(k))
  )
})
const filteredSubs = computed(() => {
  if (!searchText.value) return subs.value
  const keys = searchText.value.split(' ').filter(Boolean)
  return subs.value.filter((s: any) =>
    keys.every((k: string) => s.name.includes(k))
  )
})

let refreshTimer: any = null
onMounted(() => {
  loadPolicies()
  loadNodes()
  loadSubs()
  // 每 10 秒刷新延迟数据
  refreshTimer = setInterval(() => {
    loadPolicies()
    loadNodes()
  }, 10000)
})
onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>
