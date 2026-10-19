# 前置分流订阅出口显示问题分析报告

**日期**: 2026-10-19
**问题**: 用户设置前置分流规则出口为订阅（良心云，`sub-4`），重开编辑时显示异常

## 现象

用户截图显示：`openrung.org` 规则的出口显示为原始值 `sub-4`，而非订阅名称"良心云"。
用户描述："再次打开编辑时，这里会显示成良心某个节点名称了"

## 数据链路追踪

### 1. 数据库层（正常）

```sql
SELECT domain, target FROM front_rules WHERE domain LIKE '%openrung%';
-- 结果: domain=openrung.org target=sub-4
```

DB 正确存储 `sub-4`，无篡改。

### 2. 后端验证层（正常）

`db.py::validate_front_rule()`：
```python
target = str(d.get("target", "auto") or "auto").strip() or "auto"
# 直接透传，无转换
```

`singbox.py` 路由生成：
```python
rule["outbound"] = target  # sub-4 直接作为 outbound tag
```

后端对 `sub-` 前缀无特殊处理，`sub-4` 出站组已正确生成（urltest，53 个节点）。

### 3. 前端显示层（有 Bug）

`SitesTab.vue::targetDisplay()`：
```typescript
function targetDisplay(target: string): string {
  if (!target) return ''
  if (target.startsWith('sub-')) {
    const sid = parseInt(target.slice(4))
    const sub = obSel.value.subs.find((s: any) => s.id === sid)
    if (sub) return sub.name
    return target  // <-- subs 为空时返回原始值
  }
  return target
}
```

**根因**: `obSel.value.subs` 仅在用户点击出口选择器按钮（`openObSel()`）时才加载。
前置分流编辑弹窗打开时（`openFrontEdit()`），`subs` 仍为空数组 `[]`，
`find()` 找不到，返回原始 `sub-4`。

### 4. 关于"显示成节点名称"的分析

经全面排查，以下位置均未发现将 `sub-4` 转换为节点名的逻辑：

| 位置 | 检查结果 |
|------|----------|
| `db.py::validate_front_rule` | 直接透传 |
| `db.py::list_front_rules` | 直接返回 DB 值 |
| `db.py::replace_front_rules` | 直接存储 |
| `SitesTab.vue::loadFront` | 直接映射，无转换 |
| `SitesTab.vue::openFrontEdit` | 浅拷贝，无转换 |
| `SitesTab.vue::saveFront` | 直接提交，无转换 |
| `singbox.py` 路由生成 | `rule["outbound"] = target` 直接使用 |

**结论**: 代码中不存在将订阅 target 改写为节点名的逻辑。
"显示成良心某个节点名称" 的描述与截图（显示 `sub-4`）不符，
可能为用户记忆偏差，或指其他场景。建议用户提供复现步骤的录屏确认。

## 修复方案

### 方案 A（推荐）：弹窗打开时预加载订阅列表

在 `openFrontEdit()` 中调用订阅 API 预加载，供 `targetDisplay` 使用：

```typescript
async function openFrontEdit() {
  frontDlg.value = { rules: frontRules.value.map((r: any) => ({ ...r })) }
  // 预加载订阅列表，供 targetDisplay 显示订阅名
  if (!obSel.value.subs.length) {
    try {
      const subs = await obxGet<any[]>('/api/subscriptions')
      const nodes = await obxGet<any[]>('/api/nodes').catch(() => [])
      obSel.value.subs = (subs || []).map((s: any) => ({
        ...s,
        node_count: (nodes || []).filter((n: any) => n.sub_id === s.id).length,
      }))
    } catch {}
  }
}
```

**优点**: 改动小，显示立即正确
**缺点**: 多一次 API 调用（可接受）

### 方案 B：在 loadFront 时一并加载订阅映射

维护一个独立的 `subNameMap: Record<number, string>`，在组件挂载时加载：

```typescript
const subNameMap = ref<Record<number, string>>({})
onMounted(async () => {
  // ... 现有逻辑
  try {
    const subs = await obxGet<any[]>('/api/subscriptions')
    for (const s of subs || []) subNameMap.value[s.id] = s.name
  } catch {}
})

function targetDisplay(target: string): string {
  if (!target) return ''
  if (target.startsWith('sub-')) {
    const sid = parseInt(target.slice(4))
    return subNameMap.value[sid] || target
  }
  return target
}
```

**优点**: 与 `obSel` 解耦，逻辑更清晰；挂载时一次加载，全局可用
**缺点**: 改动稍大

## 建议

采用 **方案 B**，原因：
1. `targetDisplay` 不应依赖 `obSel` 这个弹窗状态
2. 订阅名称映射是全局数据，适合在挂载时加载
3. 为后续其他地方显示订阅名（如规则摘要 `frontSummary`）打基础

同时建议在 `frontSummary`（第 945 行）中也使用 `targetDisplay`，
目前摘要显示为 `openrung.org → sub-4`，应显示为 `openrung.org → 良心云`。

## 待用户确认

1. 是否按方案 B 修复？
2. "显示成节点名称" 的具体复现步骤（如果确实存在，需要录屏或更详细描述）
