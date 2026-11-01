<template>
  <div
    class="home-page flex size-full"
    :class="sidebarLayoutCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'"
  >
    <div
      v-if="!isMiddleScreen"
      class="relative z-40 flex-none overflow-visible transition-none"
      :class="sidebarLayoutCollapsed ? 'w-18' : 'w-64'"
    >
      <SideBar
        class="absolute inset-y-0 left-0"
        @transitionend="syncSidebarLayoutState"
      />
    </div>
    <RouterView v-slot="{ Component, route }">
      <div
        class="relative flex-1 overflow-hidden"
        ref="swiperRef"
      >
        <div class="absolute flex h-full w-full flex-col overflow-y-auto">
          <Transition
            :name="pageTransitionName"
            :mode="pageTransitionMode"
          >
            <Component :is="Component" />
          </Transition>
        </div>

        <template v-if="isMiddleScreen">
          <!-- v0.1.364：底部导航改悬浮胶囊（与客户端一致）。原 dock 是
               贴底通栏 + 近乎透明底（bg-base-100/20），暗色下对比度差；
               现改为居中悬浮胶囊：实底 + 毛玻璃 + 边框 + 阴影，选中态
               由滑动背景块（pill）表示，替代 dock-active 自带的底部
               横条；底部偏移仍含 safe-area，滑动动画遵循减少动态
               效果设置。 -->
          <div
            class="dock dock-xs z-10 h-14 w-auto rounded-full border border-base-300 bg-base-100/90 p-1 shadow-xl backdrop-blur-md left-1/2 right-auto -translate-x-1/2"
            :style="{
              bottom: 'calc(var(--spacing) * 2 + env(safe-area-inset-bottom))',
            }"
            ref="dockRef"
          >
            <div
              class="absolute top-1 bottom-1 rounded-full bg-primary/15 transition-all duration-300 motion-reduce:transition-none"
              :style="indicatorStyle"
            />
            <button
              v-for="r in renderRoutes"
              :key="r"
              @click="router.push({ name: r, replace: true })"
              class="relative h-14 flex-col items-center justify-center pt-2"
              :class="r === route.name && 'text-primary'"
            >
              <component
                :is="ROUTE_ICON_MAP[r]"
                class="h-5 w-5 flex-shrink-0"
              />
              <span class="dock-label">
                {{ $t(r) }}
              </span>
            </button>
          </div>
          <div
            class="fixed bottom-0 z-10 w-full"
            style="
              background: linear-gradient(
                to top,
                rgba(0, 0, 0, 0.18) 0%,
                rgba(0, 0, 0, 0.1) 30%,
                rgba(0, 0, 0, 0.04) 60%,
                rgba(0, 0, 0, 0.01) 85%,
                rgba(0, 0, 0, 0) 100%
              );
              height: env(safe-area-inset-bottom);
            "
          ></div>
        </template>
      </div>
    </RouterView>
  </div>
</template>

<script setup lang="ts">
import { isBackendAvailable } from '@/assembly/backend'
import { startBackendSession } from '@/assembly/session'
import SideBar from '@/components/sidebar/SideBar.vue'
import { dockTop } from '@/composables/paddingViews'
import { checkUIUpdate } from '@/assembly/version'
import { pageTransitionMode, pageTransitionName } from '@/composables/pageTransition'
import { useSwipeRouter } from '@/composables/swipe'
import { ROUTE_ICON_MAP } from '@/constant'
import { renderRoutes } from '@/helper'
import { isMiddleScreen } from '@/helper/utils'
import { fetchProxies } from '@/assembly/proxies'
import { isSidebarCollapsed } from '@/store/settings'
import { activeBackend, activeUuid } from '@/store/setup'
import { useDocumentVisibility, useElementBounding } from '@vueuse/core'
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { RouterView, useRouter, useRoute } from 'vue-router'

const router = useRouter()
const currentRoute = useRoute()
const { swiperRef } = useSwipeRouter()
const sidebarLayoutCollapsed = ref(isSidebarCollapsed.value)

const dockRef = ref<HTMLDivElement>()
const { top: dockRefTop } = useElementBounding(dockRef)

// v0.1.364 滑动选中背景：量当前激活按钮相对 dock 的位置，pill 用
// left/width 过渡跟随；路由切换、窗口尺寸变化时重算；无激活项时隐藏。
const indicatorStyle = ref<Record<string, string>>({ opacity: '0' })
function updateIndicator() {
  const el = dockRef.value
  if (!el) return
  const idx = (renderRoutes.value as unknown as string[]).indexOf(
    currentRoute.name as string,
  )
  const btns = el.querySelectorAll('button')
  const btn = idx >= 0 ? (btns[idx] as HTMLElement | undefined) : undefined
  if (!btn) {
    indicatorStyle.value = { opacity: '0' }
    return
  }
  indicatorStyle.value = {
    left: `${btn.offsetLeft}px`,
    width: `${btn.offsetWidth}px`,
    opacity: '1',
  }
}
onMounted(() => {
  nextTick(updateIndicator)
  window.addEventListener('resize', updateIndicator)
})
onUnmounted(() => {
  window.removeEventListener('resize', updateIndicator)
})
watch(
  () => currentRoute.name,
  () => nextTick(updateIndicator),
)

const syncSidebarLayoutState = () => {
  sidebarLayoutCollapsed.value = isSidebarCollapsed.value
}

watch(isSidebarCollapsed, (value) => {
  if (value) {
    sidebarLayoutCollapsed.value = true
  }
})

watch(
  isMiddleScreen,
  (value) => {
    if (!value) {
      sidebarLayoutCollapsed.value = isSidebarCollapsed.value
    }
  },
  { immediate: true },
)

watch(
  dockRefTop,
  () => {
    dockTop.value = window.innerHeight - dockRefTop.value
  },
  { immediate: true },
)

const documentVisible = useDocumentVisibility()

// 息屏 / 切走期间后端可能已经没了(睡眠、换网、内核重启)。回到前台先确认一次,
// 连不上就重开会话 —— 探测失败会把 BackendConnectionError 顶出来,
// 由它给出诊断、重试和切换后端,这里不再自己弹一个只能二选一的对话框。
watch(
  documentVisible,
  async () => {
    if (!activeBackend.value || documentVisible.value !== 'visible') return

    const uuid = activeBackend.value.uuid

    if (await isBackendAvailable(activeBackend.value)) return
    // 探测期间用户可能已经自己切走了,别把新后端的会话也重开一遍。
    if (uuid === activeUuid.value) startBackendSession()
  },
  {
    immediate: true,
  },
)

watch(documentVisible, () => {
  if (documentVisible.value !== 'visible') return
  fetchProxies()
})

checkUIUpdate()
</script>
