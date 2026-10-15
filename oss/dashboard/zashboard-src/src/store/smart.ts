import { fetchSmartGroupWeightsAPI, fetchSmartWeightsAPI } from '@/assembly/proxies'
import type { NodeRank } from '@/types'
import { ref } from 'vue'

export const smartWeightsMap = ref<Record<string, Record<string, string>>>({})
export const smartOrderMap = ref<Record<string, Record<string, number>>>({})

const restructWeights = (proxyName: string, weights: NodeRank[]) => {
  const smartWeights: Record<string, string> = {}
  const smartOrder: Record<string, number> = {}

  weights.forEach((weight, index) => {
    smartWeights[weight.Name] = weight.Rank
    smartOrder[weight.Name] = index
  })

  smartWeightsMap.value[proxyName] = smartWeights
  smartOrderMap.value[proxyName] = smartOrder
}

// deprecated
const fetchSmartGroupWeights = async (proxyName: string) => {
  const { data } = await fetchSmartGroupWeightsAPI(proxyName)

  if (!data.weights?.length) return

  restructWeights(proxyName, data.weights)
}

// 权重是拉取代理列表时顺带取的,不是用户点出来的,失败一律静默:
// 旧内核没有 /group/weights,回落到按组逐个拉。
export const initSmartWeights = async (smartGroups: string[]) => {
  let smartWeights: Record<string, NodeRank[]> | null = null

  try {
    smartWeights = (await fetchSmartWeightsAPI()).data.weights
  } catch {
    smartWeights = null
  }

  smartWeightsMap.value = {}
  smartOrderMap.value = {}

  if (!smartWeights) {
    // deprecated fallback
    smartGroups.forEach((name) => {
      fetchSmartGroupWeights(name).catch(() => {})
    })
    return
  }

  for (const [group, weights] of Object.entries(smartWeights)) {
    if (!weights?.length) continue

    restructWeights(group, weights)
  }
}
