<!-- Open-Box 二开：管理中心。订阅管理已完整移植，其余模块按优先级逐步从旧版 UI 移植；
     过渡期可通过 /legacy/ 使用旧版完整管理界面。 -->
<template>
  <div class="mx-auto max-w-6xl p-4">
    <div class="tabs tabs-boxed mb-4 w-fit">
      <a
        v-for="t in tabs"
        :key="t.key"
        class="tab"
        :class="{ 'tab-active': active === t.key }"
        @click="active = t.key"
      >
        {{ t.label }}
      </a>
    </div>

    <SubsTab v-if="active === 'subs'" />

    <div
      v-else
      class="alert"
    >
      <span>
        「{{ currentLabel }}」正在从旧版 UI 移植中，过渡期请使用
        <a
          href="/legacy/"
          class="link link-primary"
        >旧版管理界面</a>。
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed, ref } from 'vue'
import SubsTab from './SubsTab.vue'

const { t } = useI18n()
const active = ref('subs')

const tabs = computed(() => [
  { key: 'subs', label: t('obx.subscriptions') },
  { key: 'sites', label: t('obx.siteSets') },
  { key: 'dns', label: t('obx.dns') },
  { key: 'groups', label: t('obx.groups') },
  { key: 'settings', label: t('obx.panelSettings') },
])

const currentLabel = computed(() => tabs.value.find((x) => x.key === active.value)?.label ?? '')
</script>
