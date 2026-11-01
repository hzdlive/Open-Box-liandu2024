import { getLatencyByName, proxyMap, proxyProviederList } from '@/assembly/proxies'
import { NOT_CONNECTED, PROXY_SORT_TYPE } from '@/constant'
import { isProxyGroup } from '@/helper'
import {
  hideUnavailableProxies,
  proxyGroupFilterMap,
  proxySortType,
  useSmartGroupSort,
} from '@/store/settings'
import { smartOrderMap } from '@/store/smart'
import { computed, type ComputedRef } from 'vue'
import { isProxyNodeSearchMode, matchProxySearchKeyword, proxySearchKeyword } from './proxySearch'

type LatencyMap = Map<string, number>

export type ProxiesProviderSection = {
  providerName: string
  proxies: string[]
}

export const groupProxiesByProviderName = (proxies: string[]): ProxiesProviderSection[] => {
  const proxiesOfProvider: Record<string, string[]> = {}
  const providerKeys: string[] = []

  for (const proxy of proxies) {
    const proxyNode = proxyMap.value[proxy]
    const providerName =
      proxyNode['provider-name'] ||
      (proxyProviederList.value.find((group) => group.proxies.find((node) => node.name === proxy))
        ?.name ??
        '')

    if (proxiesOfProvider[providerName]) {
      proxiesOfProvider[providerName].push(proxy)
    } else {
      if (providerName === '') {
        providerKeys.unshift('')
      } else {
        providerKeys.push(providerName)
      }

      proxiesOfProvider[providerName] = [proxy]
    }
  }

  return providerKeys.map((providerName) => ({
    providerName,
    proxies: proxiesOfProvider[providerName],
  }))
}

export function useRenderProxyList(proxies: ComputedRef<string[]>, groupName?: string) {
  const renderProxies = computed(() => getRenderProxies(proxies.value, groupName))

  const proxiesCount = computed(() => {
    const available = renderProxies.value.filter(
      (proxy) => getLatencyByName(proxy, groupName) !== NOT_CONNECTED,
    ).length
    return `${available}/${proxies.value.length}`
  })

  return { renderProxies, proxiesCount }
}

const getRenderProxies = (proxies: string[], groupName: string | undefined) => {
  const latencyMap: LatencyMap = new Map(
    proxies.map((name) => [name, getLatencyByName(name, groupName)]),
  )
  const filtered = filterProxies(proxies, groupName, latencyMap)
  return sortProxies(filtered, groupName, latencyMap)
}

// v0.1.377 (#666)：组是否“可用”= 递归下去至少有一个叶子节点
// 可达。原来组名一律豁免隐藏过滤，全员失效的组也照常显示。
// resolveLatency：叶子节点的延迟取值（成员级用本组延迟桶，顶层
// 组列表用默认桶）；组名本身不取延迟（选中成员可达不代表组可
// 用，全员失效但选中成员恰好可达时组也不应藏——反之亦然）。
const hasAvailableLeaf = (
  name: string,
  resolveLatency: (n: string) => number,
  seen: Set<string>,
): boolean => {
  if (seen.has(name)) return false
  seen.add(name)
  const members = proxyMap.value[name]?.all
  if (!members?.length) return resolveLatency(name) > NOT_CONNECTED
  return members.some((m) => hasAvailableLeaf(m, resolveLatency, seen))
}

// 顶层组列表用：无 groupName 桶，取默认延迟。
export const isGroupAvailable = (name: string): boolean =>
  hasAvailableLeaf(name, (n) => getLatencyByName(n), new Set())

const filterProxies = (
  proxies: string[],
  groupName: string | undefined,
  latencyMap: LatencyMap,
) => {
  let result = proxies

  if (hideUnavailableProxies.value) {
    const resolve = (n: string) => latencyMap.get(n) ?? getLatencyByName(n, groupName)
    result = result.filter((name) =>
      isProxyGroup(name)
        ? hasAvailableLeaf(name, resolve, new Set())
        : latencyMap.get(name)! > NOT_CONNECTED,
    )
  }

  if (isProxyNodeSearchMode.value && proxySearchKeyword.value) {
    const keyword = proxySearchKeyword.value
    result = result.filter((name) => matchProxySearchKeyword(name, keyword))
  }

  const groupKeyword = groupName ? proxyGroupFilterMap.value[groupName] : ''
  if (groupKeyword) {
    result = result.filter((name) => matchProxySearchKeyword(name, groupKeyword))
  }

  return result
}

const sortProxies = (proxies: string[], groupName: string | undefined, latencyMap: LatencyMap) => {
  if (groupName && useSmartGroupSort.value && smartOrderMap.value[groupName]) {
    return sortBySmartOrder(proxies, smartOrderMap.value[groupName])
  }

  if (proxySortType.value === PROXY_SORT_TYPE.DEFAULT) {
    return proxies
  }

  const groups: string[] = []
  const nodes: string[] = []
  proxies.forEach((proxy) => {
    ;(isProxyGroup(proxy) ? groups : nodes).push(proxy)
  })

  const sortFunc = getSortFunc(proxySortType.value, latencyMap)
  return groups.concat(nodes.sort(sortFunc))
}

const sortBySmartOrder = (proxies: string[], orderMap: Record<string, number>) => {
  return [...proxies].sort((a, b) => {
    const ia = orderMap[a] ?? Number.MAX_SAFE_INTEGER
    const ib = orderMap[b] ?? Number.MAX_SAFE_INTEGER
    return ia - ib
  })
}

const getSortFunc = (sortType: PROXY_SORT_TYPE, latencyMap: LatencyMap) => {
  const latencyFor = (name: string) => {
    const latency = latencyMap.get(name)!
    return latency === 0 ? Infinity : latency
  }
  switch (sortType) {
    case PROXY_SORT_TYPE.NAME_ASC:
      return (a: string, b: string) => a.localeCompare(b)
    case PROXY_SORT_TYPE.NAME_DESC:
      return (a: string, b: string) => b.localeCompare(a)
    case PROXY_SORT_TYPE.LATENCY_ASC:
      return (a: string, b: string) => latencyFor(a) - latencyFor(b)
    case PROXY_SORT_TYPE.LATENCY_DESC:
      return (a: string, b: string) => latencyFor(b) - latencyFor(a)
    default:
      return undefined
  }
}
