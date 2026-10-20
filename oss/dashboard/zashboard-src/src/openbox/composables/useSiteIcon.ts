// Open-Box: 站点集 icon 渲染（面板 iconId -> emoji，与 ObPolicyTab 同源）
export function siteIcon(iconId: string | undefined, name: string): string {
  if (!iconId) {
    const n = (name || '').toLowerCase()
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
  const key = iconId.split(':')[1] || ''
  const iconMap: Record<string, string> = {
    'stopwatch': '⏱️', 'openai-light': '🤖', 'youtube': '▶️', 'tiktok': '🎵',
    'netflix-mono': '🎬', 'github-mono': '🐙', 'google': '🔍', 'apple': '🍎',
    'microsoft': '🪟', 'game': '🎮', 'globe': '🌐', 'shield': '🛡️',
    'earth-americas': '🌍',
  }
  return iconMap[key] || '🌐'
}
