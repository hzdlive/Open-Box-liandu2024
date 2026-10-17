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
          <div class="ob-card-icon">{{ site.icon || '🌐' }}</div>
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

// 加载策略（站点集）
async function loadPolicies() {
  try {
    const data = await obxGet<any>('/api/sitesets')
    const list = data.sitesets || data || []
    policies.value = list.map((s: any) => ({
      id: s.id,
      name: s.name,
      icon: s.icon,
      matched: s.matched || 0,
      total: s.total || 0,
      latency: s.latency || 68,
      currentGroup: s.group || '所有-自动',
      currentNode: s.currentNode || '',
      dots: s.dots || [],
      options: s.options || [],
      selected: s.selected || '',
    }))
    tabs[0].count.value = policies.value.length
  } catch (e) {
    console.error('load policies failed', e)
  }
}

// 加载节点组（从 clash API）
async function loadNodes() {
  try {
    // 经后端代理获取 clash proxies
    const data = await obxGet<any>('/api/openbox/clash-proxies')
    const proxies = data.proxies || {}
    const groups: any[] = []
    for (const [name, info] of Object.entries(proxies as Record<string, any>)) {
      // 跳过内部 flip 选择器
      if (name.startsWith('flip-') || name.startsWith('obflip-')) continue
      if (info.type === 'Selector' || info.type === 'URLTest') {
        groups.push({
          name,
          typeLabel: info.type === 'URLTest' ? 'URLTest' : 'Selector',
          alive: info.alive || 0,
          total: (info.all || []).length,
          latency: info.latency || '',
          now: info.now || '',
          interval: info.interval || 300,
          tolerance: info.tolerance || 100,
          dots: info.dots || [],
          members: (info.all || []).map((m: string) => ({ name: m, protocol: '', latency: '' })),
          isFailover: info.isFailover || false,
          lanes: info.lanes || [],
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
    const list = data.subscriptions || data || []
    subs.value = list.map((s: any) => ({
      id: s.id,
      name: s.name,
      alive: s.alive || 0,
      total: s.total || 0,
      updated: s.updated || '',
      traffic: s.traffic || '',
      dots: s.dots || [],
      nodes: s.nodes || [],
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
.ob-tabs { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.ob-tab {
  padding: 6px 16px; border-radius: 20px; border: 1px solid #ddd;
  background: #fff; cursor: pointer; font-size: 14px;
}
.ob-tab.active { background: #4caf50; color: #fff; border-color: #4caf50; }
.ob-search { margin-left: auto; position: relative; }
.ob-search input {
  padding: 6px 12px; border-radius: 20px; border: 1px solid #ddd;
  width: 280px; font-size: 13px;
}
.ob-search-clear { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); cursor: pointer; }
.ob-cards { display: flex; flex-direction: column; gap: 12px; }
.ob-card {
  background: #fff; border-radius: 12px; padding: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.ob-card-head { display: flex; align-items: center; gap: 12px; cursor: pointer; }
.ob-card-icon { font-size: 32px; }
.ob-card-title { flex: 1; display: flex; align-items: center; gap: 8px; }
.ob-card-name { font-size: 16px; font-weight: 600; }
.ob-card-badge {
  font-size: 12px; background: #e8f5e9; color: #4caf50;
  padding: 2px 8px; border-radius: 10px;
}
.ob-card-type { font-size: 13px; color: #999; }
.ob-card-latency {
  background: #e8f5e9; color: #4caf50; padding: 4px 12px;
  border-radius: 12px; font-size: 13px; font-weight: 600;
}
.ob-card-chain { margin-top: 8px; font-size: 13px; color: #666; }
.ob-card-sub { margin-top: 4px; font-size: 13px; color: #666; }
.ob-card-meta { margin-top: 4px; font-size: 12px; color: #999; text-align: right; }
.ob-card-dots { margin-top: 8px; display: flex; gap: 6px; }
.ob-dot { width: 12px; height: 12px; border-radius: 50%; background: #ddd; }
.ob-dot.ok { background: #4caf50; }
.ob-dot.warn { background: #ffeb3b; }
.ob-dot.err { background: #f44336; }
.ob-card-actions { display: flex; gap: 8px; }
.ob-card-actions button {
  border: none; background: none; cursor: pointer; font-size: 18px;
}
.ob-options {
  margin-top: 12px; display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}
.ob-option {
  border: 1px solid #eee; border-radius: 8px; padding: 10px;
  cursor: pointer; transition: all 0.2s;
}
.ob-option:hover { border-color: #4caf50; }
.ob-option.selected { background: #4caf50; color: #fff; }
.ob-option.selected .ob-option-meta { color: rgba(255,255,255,0.8); }
.ob-option-name { font-size: 14px; font-weight: 500; }
.ob-option-meta { font-size: 12px; color: #999; margin-top: 4px; }
.ob-lat { background: #e8f5e9; color: #4caf50; padding: 1px 8px; border-radius: 8px; }
.ob-option.selected .ob-lat { background: rgba(255,255,255,0.2); color: #fff; }
.ob-lanes { margin-top: 12px; }
.ob-lane { margin-bottom: 12px; }
.ob-lane-head { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
.ob-history { font-size: 12px; color: #999; margin-top: 8px; }
</style>
