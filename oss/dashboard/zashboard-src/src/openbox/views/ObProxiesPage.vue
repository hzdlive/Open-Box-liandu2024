<template>
  <div class="ob-proxies">
    <!-- 顶部 Tab：策略 / 节点 / 订阅 -->
    <div class="ob-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="ob-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}({{ tab.count }})
      </button>
      <div class="ob-search">
        <input v-model="searchText" placeholder="搜索 | 多个关键词用空格分隔" />
        <span v-if="searchText" class="ob-search-clear" @click="searchText = ''">×</span>
      </div>
    </div>

    <!-- 策略 Tab：站点集 -->
    <div v-if="activeTab === 'policy'" class="ob-cards">
      <div v-for="site in filteredPolicies" :key="site.id" class="ob-card">
        <div class="ob-card-head" @click="toggleExpand('policy', site.id)">
          <div class="ob-card-icon">{{ mapIcon(site.icon, site.name) }}</div>
          <div class="ob-card-title">
            <span class="ob-card-name">{{ site.name }}</span>
            <span class="ob-card-badge">域名穿透</span>
            <span class="ob-card-type">Selector ({{ site.matched }}/{{ site.total }})</span>
          </div>
          <div class="ob-card-latency">{{ site.latency }}</div>
        </div>
        <div class="ob-card-chain">
          <span>🌍 {{ site.currentGroup }}</span>
          <span v-if="site.currentNode"> ⊕ {{ site.currentNode }}</span>
        </div>
        <div class="ob-card-dots">
          <span
            v-for="(d, i) in site.dots"
            :key="i"
            class="ob-dot"
            :class="d"
          ></span>
        </div>
        <!-- 展开：出站选项 -->
        <div v-if="expanded.policy === site.id" class="ob-options">
          <div
            v-for="opt in site.options"
            :key="opt.name"
            class="ob-option"
            :class="{ selected: opt.name === site.selected }"
            @click="selectPolicyOutbound(site, opt)"
          >
            <div class="ob-option-name">{{ opt.icon }} {{ opt.name }}</div>
            <div class="ob-option-meta">{{ opt.type }} / udp <span class="ob-lat">{{ opt.latency }}</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 节点 Tab：节点组 -->
    <div v-if="activeTab === 'node'" class="ob-cards">
      <div v-for="group in filteredNodes" :key="group.name" class="ob-card">
        <div class="ob-card-head" @click="toggleExpand('node', group.name)">
          <div class="ob-card-icon">{{ group.icon || '🎯' }}</div>
          <div class="ob-card-title">
            <span class="ob-card-name">{{ group.name }}</span>
            <span class="ob-card-type">{{ group.typeLabel }} ({{ group.alive }}/{{ group.total }})</span>
          </div>
          <div class="ob-card-latency">{{ group.latency }}</div>
        </div>
        <div class="ob-card-sub">{{ group.now }}</div>
        <div class="ob-card-meta">检测间隔 {{ group.interval }} 秒 · 容差 {{ group.tolerance }} 毫秒</div>
        <div class="ob-card-dots">
          <span v-for="(d, i) in group.dots" :key="i" class="ob-dot" :class="d"></span>
        </div>
        <!-- 展开：成员节点 -->
        <div v-if="expanded.node === group.name" class="ob-options">
          <div
            v-for="m in group.members"
            :key="m.name"
            class="ob-option"
            :class="{ selected: m.name === group.now }"
            @click="selectNode(group, m)"
          >
            <div class="ob-option-name">{{ m.name }}</div>
            <div class="ob-option-meta">{{ m.protocol }} / udp <span class="ob-lat">{{ m.latency }}</span></div>
          </div>
        </div>
        <!-- 故障转移：车道 -->
        <div v-if="group.isFailover && expanded.node === group.name" class="ob-lanes">
          <div v-for="lane in group.lanes" :key="lane.name" class="ob-lane">
            <div class="ob-lane-head">{{ lane.name }} ({{ lane.alive }}/{{ lane.total }})</div>
            <div
              v-for="m in lane.members"
              :key="m.name"
              class="ob-option"
              :class="{ selected: m.selected }"
            >
              <div class="ob-option-name">{{ m.name }}</div>
              <div class="ob-option-meta">{{ m.protocol }} / udp <span class="ob-lat">{{ m.latency }}</span></div>
            </div>
          </div>
          <div v-if="group.switchHistory" class="ob-history">
            最近切换：{{ group.switchHistory }}
          </div>
        </div>
      </div>
    </div>

    <!-- 订阅 Tab -->
    <div v-if="activeTab === 'sub'" class="ob-cards">
      <div v-for="sub in filteredSubs" :key="sub.id" class="ob-card">
        <div class="ob-card-head" @click="toggleExpand('sub', sub.id)">
          <div class="ob-card-title">
            <span class="ob-card-name">{{ sub.name }} ({{ sub.alive }}/{{ sub.total }})</span>
          </div>
          <div class="ob-card-actions">
            <button @click.stop="speedtestSub(sub)" title="测速">⚡</button>
            <button @click.stop="refreshSub(sub)" title="刷新">🔄</button>
          </div>
        </div>
        <div class="ob-card-meta">更新于 {{ sub.updated }} · {{ sub.traffic }}</div>
        <div class="ob-card-dots">
          <span v-for="(d, i) in sub.dots" :key="i" class="ob-dot" :class="d"></span>
        </div>
        <div v-if="expanded.sub === sub.id" class="ob-options">
          <div v-for="m in sub.nodes" :key="m.name" class="ob-option">
            <div class="ob-option-name">{{ m.name }}</div>
            <div class="ob-option-meta">{{ m.protocol }} / udp <span class="ob-lat">{{ m.latency }}</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { obxGet, obxPost } from '../api'

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
    const [clashData, groupsData] = await Promise.all([
      obxGet<any>('/api/openbox/clash-proxies'),
      obxGet<any>('/api/groups').catch(() => []),
    ])
    const proxies = clashData.proxies || {}
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
      // 跳过内部 flip 选择器和 lane 子组
      if (name.startsWith('flip-') || name.startsWith('obflip-')) continue
      if (name.includes('#')) continue
      if (info.type === 'Selector' || info.type === 'URLTest') {
        const isFailover = failoverNames.has(name)
        const lanes = (laneMap[name] || []).map(({ name: laneTag, info: laneInfo }: any) => {
          const laneName = laneTag.split('#')[1]
          return {
            name: laneName,
            tag: laneTag,
            alive: 0,
            total: (laneInfo.all || []).length,
            members: (laneInfo.all || []).map((m: string) => {
              const p = proxies[m] || {}
              return { name: m, protocol: p.type || '', latency: p.latency || '', selected: laneInfo.now === m }
            }),
            now: laneInfo.now || '',
          }
        })
        groups.push({
          name,
          typeLabel: isFailover ? '故障转移' : (info.type === 'URLTest' ? 'URLTest' : 'Selector'),
          alive: info.alive || 0,
          total: (info.all || []).length,
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

onMounted(() => {
  loadPolicies()
  loadNodes()
  loadSubs()
})
</script>

<style scoped>
.ob-proxies { padding: 12px; }
.ob-tabs { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }
.ob-tab {
  padding: 6px 16px; border-radius: 20px; cursor: pointer; font-size: 14px;
  border: 1px solid var(--ob-border, #e5e7eb);
  background: var(--ob-bg, #ffffff);
  color: var(--ob-text, #374151);
  transition: all 0.2s;
}
.ob-tab.active { background: #22c55e; color: #fff; border-color: #22c55e; }
.ob-search { margin-left: auto; position: relative; }
.ob-search input {
  padding: 6px 12px; border-radius: 20px; font-size: 13px; width: 280px;
  border: 1px solid var(--ob-border, #e5e7eb);
  background: var(--ob-bg, #ffffff);
  color: var(--ob-text, #374151);
}
.ob-search-clear { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); cursor: pointer; color: #9ca3af; }
.ob-cards { display: flex; flex-direction: column; gap: 12px; }
.ob-card {
  border-radius: 12px; padding: 16px;
  background: var(--ob-bg, #ffffff);
  border: 1px solid var(--ob-border, #f3f4f6);
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.ob-card-head { display: flex; align-items: center; gap: 12px; cursor: pointer; }
.ob-card-icon { font-size: 32px; line-height: 1; }
.ob-card-title { flex: 1; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ob-card-name { font-size: 16px; font-weight: 600; color: var(--ob-text, #111827); }
.ob-card-badge {
  font-size: 12px; padding: 2px 8px; border-radius: 10px;
  background: #dcfce7; color: #16a34a;
}
.ob-card-type { font-size: 13px; color: #9ca3af; }
.ob-card-latency {
  padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600;
  background: #dcfce7; color: #16a34a;
}
.ob-card-chain { margin-top: 8px; font-size: 13px; color: var(--ob-text2, #4b5563); }
.ob-card-sub { margin-top: 4px; font-size: 13px; color: var(--ob-text2, #4b5563); }
.ob-card-meta { margin-top: 4px; font-size: 12px; color: #9ca3af; text-align: right; }
.ob-card-dots { margin-top: 8px; display: flex; gap: 6px; }
.ob-dot { width: 12px; height: 12px; border-radius: 50%; background: #d1d5db; }
.ob-dot.ok { background: #22c55e; }
.ob-dot.warn { background: #facc15; }
.ob-dot.err { background: #ef4444; }
.ob-card-actions { display: flex; gap: 8px; }
.ob-card-actions button {
  border: none; background: none; cursor: pointer; font-size: 18px; color: #9ca3af;
}
.ob-card-actions button:hover { color: #4b5563; }
.ob-options {
  margin-top: 12px; display: grid; gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
}
.ob-option {
  border: 1px solid var(--ob-border, #e5e7eb); border-radius: 8px; padding: 10px;
  cursor: pointer; transition: all 0.2s;
  background: var(--ob-bg, #ffffff);
}
.ob-option:hover { border-color: #22c55e; }
.ob-option.selected { background: #22c55e; color: #fff; border-color: #22c55e; }
.ob-option-name { font-size: 14px; font-weight: 500; }
.ob-option-meta { font-size: 12px; color: #9ca3af; margin-top: 4px; }
.ob-option.selected .ob-option-meta { color: rgba(255,255,255,0.8); }
.ob-lat { background: #dcfce7; color: #16a34a; padding: 1px 8px; border-radius: 8px; font-size: 12px; }
.ob-option.selected .ob-lat { background: rgba(255,255,255,0.2); color: #fff; }
.ob-lanes { margin-top: 12px; }
.ob-lane { margin-bottom: 12px; }
.ob-lane-head { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: var(--ob-text, #374151); }
.ob-history { font-size: 12px; color: #9ca3af; margin-top: 8px; }
/* 深色模式 */
.dark .ob-tab { --ob-border: #374151; --ob-bg: #1f2937; --ob-text: #e5e7eb; }
.dark .ob-card { --ob-bg: #1f2937; --ob-border: #374151; --ob-text: #f9fafb; --ob-text2: #d1d5db; }
.dark .ob-option { --ob-border: #374151; --ob-bg: #1f2937; }
.dark .ob-search input { --ob-border: #374151; --ob-bg: #1f2937; --ob-text: #e5e7eb; }
</style>
