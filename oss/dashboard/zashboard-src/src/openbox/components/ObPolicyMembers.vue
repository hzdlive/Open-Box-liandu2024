<template>
  <div>
    <div class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="opt in visibleOptions"
        :key="opt.name"
        class="rounded-box border p-3 cursor-pointer transition-colors hover:border-success"
        :class="opt.name === selected
          ? 'bg-success text-success-content border-success'
          : 'border-base-300/50 bg-base-100'"
        @click="$emit('select', opt)"
      >
        <div class="text-sm font-medium">{{ opt.name }}</div>
        <div class="text-xs opacity-60 mt-1">
          {{ opt.type }} / udp
          <span class="badge badge-sm ml-1" :class="opt.name === selected ? 'badge-ghost' : latencyClass(opt.latency)">{{ opt.latency }}</span>
        </div>
      </div>
    </div>
    <div v-if="maxProxies < options.length" class="mt-2 text-xs opacity-60">
      已显示 {{ maxProxies }} 个，滚动加载更多（共 {{ options.length }} 个）
    </div>
  </div>
</template>

<script setup lang="ts">
// v0.1.360：策略卡展开的成员列表按可见区域加载，复用节点页
// ProxiesContent 已有的 useCalculateMaxProxies（滚动逼近底部时追加，
// 初始保证选中项可见）。本组件随展开创建、随收起销毁，故每次展开
// 都从初始窗口重新开始，不会把上一张卡的进度带过来。
import { computed } from 'vue'
import { useCalculateMaxProxies } from '@/composables/proxiesScroll'

const props = defineProps<{
  options: any[]
  selected: string
}>()
defineEmits<{
  (e: 'select', opt: any): void
}>()

function latencyClass(lat: string | number | undefined): string {
  const n = typeof lat === 'string' ? parseInt(lat) : (lat ?? NaN)
  if (isNaN(n) || n <= 0) return 'badge-ghost'
  if (n < 150) return 'badge-success'
  if (n < 300) return 'badge-warning'
  return 'badge-error'
}

const activeIndex = props.options.findIndex((o) => o.name === props.selected)
const { maxProxies } = useCalculateMaxProxies(props.options.length, activeIndex)
const visibleOptions = computed(() => props.options.slice(0, maxProxies.value))
</script>
