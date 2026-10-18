<!-- Open-Box 二开：管理中心。各模块由旧版自研 UI 移植；过渡期 /legacy/ 仍可用。 -->
<template>
  <div class="mx-auto max-w-6xl p-4">
    <div class="tabs tabs-boxed mb-4 w-fit max-w-full flex-wrap">
      <a
        v-for="t in tabs"
        :key="t.key"
        class="tab whitespace-nowrap"
        :class="{ 'tab-active': active === t.key }"
        @click="active = t.key"
      >
        {{ t.label }}
      </a>
    </div>

    <SubsTab v-if="active === 'subs'" />
    <GroupsTab v-else-if="active === 'groups'" />
    <SitesTab v-else-if="active === 'sites'" />
    <DnsTab v-else-if="active === 'dns'" />
    <TerminalsTab v-else-if="active === 'terminals'" />
    <ChainsTab v-else-if="active === 'chains'" />
    <ShareTab v-else-if="active === 'share'" />
    <ContentFilterTab v-else-if="active === 'contentfilter'" />
    <BackupTab v-else-if="active === 'backup'" />
    <SettingsTab v-else-if="active === 'settings'" />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { computed, ref } from 'vue'
import ChainsTab from './ChainsTab.vue'
import BackupTab from './BackupTab.vue'
import ContentFilterTab from './ContentFilterTab.vue'
import DnsTab from './DnsTab.vue'
import GroupsTab from './GroupsTab.vue'
import SettingsTab from './SettingsTab.vue'
import ShareTab from './ShareTab.vue'
import SitesTab from './SitesTab.vue'
import SubsTab from './SubsTab.vue'
import TerminalsTab from './TerminalsTab.vue'

const { t } = useI18n()
const active = ref('subs')

const tabs = computed(() => [
  { key: 'subs', label: t('obx.subscriptions') },
  { key: 'groups', label: t('obx.groups') },
  { key: 'sites', label: t('obx.siteSets') },
  { key: 'dns', label: t('obx.dns') },
  { key: 'terminals', label: t('obx.terminals') },
  { key: 'chains', label: t('obx.chains') },
  { key: 'share', label: t('obx.shareNetwork') },
  { key: 'contentfilter', label: t('obx.contentFilter') },
  { key: 'backup', label: t('obx.backup') || '备份' },
  { key: 'settings', label: t('obx.panelSettings') },
])
</script>
