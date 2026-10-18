# 第三方研究报告分析：对开源面板开发的价值评估

> 分析对象：`Open-Box-liandu2024.zip`（别的大模型产出的研究报告）
> 分析日期：2026-10-18
> 分析人：Muse

---

## 一、报告概述

### 1.1 包结构

| 目录 | 内容 | 规模 |
|---|---|---|
| `panel-contract/` | 行为契约：OpenAPI、JSON Schema、枚举、i18n、测试向量、行为规范文档 | 约 30 个文件 |
| `openbox-panel/` | Node.js 重实现（含 973 个文件中的大部分：handlers、tests、tools） | 约 940 个文件 |

总计 973 个文件，9.6MB。

### 1.2 核心文档

| 文件 | 行数/规模 | 内容 |
|---|---|---|
| `behavior-spec.md` | 590 行 | 行为规范：系统模型、认证、页面清单、跨子系统（故障转移/DNS/入口绕过/链式代理/内容过滤/订阅分享/备份） |
| `openapi.yaml` | 122 端点（宣称） | HTTP 契约 |
| `i18n-en.json` | 1753 keys | 英文 UI 文案 |
| `panel-enums.json` | 24 个枚举 | 混淆名→语义的枚举恢复 |
| `data-model.md` | 263 行 | 运行时布局、Go core RPC 契约、SQLite 表结构 |
| `state-model.md` | 263 行 | core 输入模型（18 字段）、14 个 RPC 方法 |
| `desktop-client.md` | 226 行 | 三个二进制、obclient 符号、路由 oracle |
| `routing-golden.json` | 81 用例 | 路由决策一致性测试向量 |
| `sharelink-golden.json` + `sharelink-cases.json` | 43+86 用例 | 分享链接解析测试向量 |
| `singbox-contract.md` + `singbox-schema.json` + `singbox-tags.json` | — | sing-box 标签命名规范 |

### 1.3 方法论声明

报告自称：
- "A clean-room reimplementation ... built from the frozen HTTP contract"
- behavior-spec.md 明确标注每条陈述的来源：**R**（README v0.1.330）、**I**（i18n 表）、**C**（HTTP contract）、**E**（recovered enums + failover 分析）
- 推断内容明确标记 *(inferred)*

---

## 二、Clean-Room 合规性评估

### 2.1 可以使用的部分（行为事实）

以下属于"公开可观察行为"，与我们 REA 报告同性质，可作为交叉验证参考：

1. **枚举值**（`panel-enums.json`）：24 个枚举的取值，如 `od` 导出分组 10 项、`Zf` 排序类型 11 项、出站类型 `id` 含 smart/loadbalance
2. **API 形状**（`openapi.yaml`）：端点路径、方法、请求/响应字段名
3. **行为规则**（`behavior-spec.md`）：故障转移 11 种原因码、DNS 地区自动检测时机、备份选择性导出、入口绕过两种模式等
4. **测试向量**（`routing-golden.json`、`sharelink-*.json`）：输入/期望输出对，可用于验证我们的实现
5. **状态模型**（`state-model.md`）：`configDetailed` 的 18 个字段名、core 不做校验（unknown fields ignored）

### 2.2 不可使用的部分

1. **`openbox-panel/` 下的 Node.js 实现代码**：这是第三方的实现作品，直接复制其代码属于复制第三方实现，不是 clean-room。我们必须坚持自己用 Python/Flask 实现。
2. **反混淆后的代码片段**：如 `index.mjs:10919-10943` 这类具体代码行号引用，虽为行为证据，但不应复制其代码组织方式。

### 2.3 与 REA 的关系

| 维度 | 我们的 REA（v0.1.330） | 第三方报告（v0.1.330） |
|---|---|---|
| 版本 | v0.1.330 | v0.1.330 |
| 方法 | 静态观测（未反编译） | 静态分析 + 行为推断 |
| 故障转移 | §24（客户端功能，面板只渲染） | §5.1（11 种原因码，3 lanes，positional role） |
| 配置渲染 | §27.2（16 键） | state-model（18 字段，含 2 个注入字段） |
| 枚举 | §26.5（部分） | 24 个完整枚举 |
| i18n | 1828 keys（提及） | 1753 keys（实际文件） |
| 测试向量 | 无 | 81 路由 + 43 分享链接 |

**结论**：第三方报告在**广度**（122 端点、24 枚举、81 测试向量）和**细节**（profile 验证顺序、入口绕过机制）上超过我们的 REA。两者在关键事实上相互印证（11 种故障原因码、od 10 分组、smart/loadbalance 映射），可信度高。

---

## 三、对开源面板开发的价值（按模块）

### 3.1 已验证我们实现正确的（交叉印证）

| 模块 | 第三方证据 | 我们的实现 | 结论 |
|---|---|---|---|
| 连接页排序 | `Zf` 枚举 11 项：host/chains/rule/type/connectTime/download/downloadSpeed/upload/uploadSpeed/sourceIP/inboundUser | `SORT_TYPE` 11 项完全一致 | ✅ 1:1 |
| 导出分组 | `od` 枚举 10 项：panel/subscriptions/groups/routing/clients/chain/dns/kernel/share/apps | REA §26.5 已记录 | ✅ 1:1 |
| 出站类型 | `id` 枚举含 smart/loadbalance/urltest/selector/fallback | 后端已映射 smart/loadbalance→urltest | ✅ 1:1 |
| 故障转移原因码 | 11 种：closed/dns/error/invalid/notFound/refused/status/timeout/tls/unreachable/unstable | `failover_sm.py` 已对齐 | ✅ 1:1 |
| 故障转移参数 | 300s 间隔、5s 超时、连续 2 次、60s 恢复保持、最多 3 通道 | 与我们默认值一致 | ✅ 1:1 |
| 链式代理排除 | "Chain proxies are excluded from dynamic groups" | 我们已实现 | ✅ 1:1 |
| DNS 地区检测 | 新装/升级/恢复默认值时按出口 IP 自动检测 | 我们已实现 | ✅ 1:1 |
| 备份排除密码 | "The file never contains the panel password" | 我们已过滤 | ✅ 1:1 |

### 3.2 发现我们缺失的功能

#### 🔴 高优先级

**1. 选择性备份导出**（behavior-spec §5.8）
- 原版：导出时可选包含 subscriptions/nodes、chain proxies、per-device routing、shared network
- 我们：只有全量导出
- 行动：`GET /api/backup` 增加 `groups` 参数，前端加复选框

**2. Profile 四步验证顺序**（openbox-panel README）
- 原版 `PUT /api/openbox/profile/` 按固定顺序验证：
  1. shape and range（~60 字段级规则）
  2. chain-proxy names vs nodes/groups/policies
  3. cross-kind name conflicts
  4. proxy DNS sanity（中国侧路由器）
- 我们：无集中式 profile 验证
- 行动：如未来做 profile 接口，需按此顺序实现

**3. 入口绕过完整机制**（behavior-spec §5.3）
- 原版有"direct traffic does not enter the kernel"总开关（默认开）
- 两种自动模式：Default-release（FakeIP 开 + 兜底直连）/ Default-enter
- Direct-answer release 集合：保留 15 分钟~1 天，内核重启后持久化，direct→proxy 时清空
- 我们：只有 nftables 基础规则，无模式自动选择、无 release 集合管理
- 行动：中长期补齐；短期至少在规则页显示当前模式及原因

#### 🟡 中优先级

**4. 内容过滤的真实形态**（behavior-spec §5.5）
- 原版：管理 rule/script 快照，方言 `surge` 和 `quantumultx`，iOS 离线运行，规则文本可粘贴至 512 KiB，导入器报告 `skippedScripts`/`skippedUnsupported`/`skippedRouting`/`skippedUnrepresentable`
- 我们：实现为 3 个硬编码域名 blocklist（广告/跟踪器/恶意软件）
- 评估：我们的实现可能是简化版。原版的"内容过滤"更像是规则集管理器，而非单纯的域名拦截。需要用户确认：是要域名拦截（我们已做），还是规则集管理（原版形态）？
- 行动：待用户决策

**5. 订阅分享的完整行为**（behavior-spec §5.6）
- 原版：`GET /sub/:token` 公开链接，`/api/openbox/subscription-shares*` 管理；禁用后 404；regenerate 换 token；列表支持展开/折叠
- 我们：有两套表（`subscription_shares` vs `ob_subscription_shares`）未合并
- 行动：合并双模型，对照 `subscription-shares.mjs` 的 5 个端点补齐

**6. 客户端供应端点**（behavior-spec §5.7）
- 原版：9 个 `/client/v1/*` 端点，config URL 自包含 token，content-filter 按 hash 寻址
- 我们：`/api/client/*` 按公开协议对齐中，但未系统对照 9 个端点
- 行动：用 openapi.yaml 逐个核对 `/client/v1/*`

#### 🟢 低优先级 / 信息性

**7. 路由测试向量**（routing-golden.json，81 用例）
- 用途：验证 sing-box 规则匹配语义，非面板逻辑
- 价值：可用作我们 `/api/openbox/penetration` 的回归测试输入（将 sing-box rule 格式转换为 site-set 格式的子集）
- 行动：抽取 domain/ip_cidr/port 相关的 30+ 用例，编写 conformance 测试

**8. 分享链接测试向量**（sharelink-golden.json 43 用例 + sharelink-cases.json 86 断言）
- 用途：验证各种分享链接（ss/vless/trojan/vmess/tuic/hysteria2/anytls）的解析
- 价值：直接用于测试我们的 `subscription.py` 解析器
- 行动：高价值，立即转化为 Python 测试用例

**9. 状态模型 18 字段**（state-model.md）
- `configDetailed` 接收 18 字段（REA 说 16，第三方说 18，含 `chainNodes` 和 `filterExpectedKey` 两个注入字段）
- `filterExpectedKey` = sha256(JSON.stringify(dns.filter minus autoUpdate))[:16]，用于变更检测
- 价值：确认我们的架构（Python 直接生成 sing-box 配置）是合法替代，因为 core 只是"无校验的配置渲染器"（unknown fields ignored）
- 行动：无需行动，架构已正确

**10. i18n 1753 keys**
- 第三方有完整的 `i18n-en.json`（1753 keys）
- 我们四语言 979 keys 已同步
- 价值：可用作"功能清单"——缺失的 key 对应未实现的功能模块
- 行动：将 1753 keys 按功能域聚类，生成"未实现功能清单"

### 3.3 发现我们可能实现错误的地方

**1. 故障转移 lane 角色**（behavior-spec §5.1）
- 原版："Lane role is derived positionally, not stored as a name"（角色按位置推导，不存名字）
- 我们：DB 中 lane 有 `name` 字段（主用/备用1/备用2），`failover_init` 用名字生成 tag
- 影响：中等。功能上我们能工作，但与原版的数据模型不同。如果原版升级时按位置重排 lane，我们的按名字匹配会错乱。
- 行动：评估是否改为 positional（lane 0=primary，1=backup-1，2=backup-2）

**2. 内容过滤的数据模型**（见 3.2-4）
- 可能完全理解错了功能形态，需用户确认

---

## 四、端点覆盖率分析

第三方 `openapi.yaml` 宣称 122 端点（实际解析出 99 个路径）。我们已实现的核心端点：

| 功能域 | 第三方端点数（估算） | 我们已实现 | 缺失（示例） |
|---|---|---|---|
| 认证 | 5 | ✅ 5 | - |
| 订阅 | 7 | ✅ 7 | - |
| 分组 | ~8 | ✅ 6 | 部分 PUT 语义 |
| 站点集/路由 | ~10 | ✅ 8 | profile 四步验证 |
| DNS | ~12 | ✅ 10 | - |
| 故障转移 | ~6 | ✅ 4 | lane positional |
| 链式代理 | ~6 | ✅ 5 | - |
| 备份/恢复 | 4 | ⚠️ 2 | 选择性导出/导入 |
| 客户端 | 9 | ⚠️ ~4 | 需逐个核对 |
| 内容过滤 | ~6 | ⚠️ 3 | surge/quantumultx 方言 |
| 系统/升级 | ~10 | ⚠️ 5 | 组件更新检查 |

**结论**：核心 CRUD 端点覆盖率 ~80%，缺失主要集中在"验证顺序"、"选择性操作"、"客户端供应"三类。

---

## 五、行动建议（优先级排序）

### P0（立即做，价值高、成本低）

1. **分享链接 conformance 测试**：将 `sharelink-cases.json` 的 86 个断言转化为 Python 测试，验证 `subscription.py` 解析器
2. **合并订阅分享双模型**：统一为一套表 + `/api/openbox/subscription-shares*` 5 端点

### P1（本周做）

3. **选择性备份**：`GET /api/backup` 加 `groups` 参数 + 前端复选框
4. **客户端端点核对**：用 openapi.yaml 逐个检查 9 个 `/client/v1/*`
5. **i18n 功能清单**：用 1753 keys 聚类生成未实现功能列表，指导后续对标

### P2（中长期）

6. **入口绕过完整机制**：模式自动选择 + direct-answer release 集合 + 规则页显示原因
7. **内容过滤形态确认**：与用户确认要域名拦截还是规则集管理（surge/quantumultx）
8. **故障转移 lane positional**：评估数据模型变更成本
9. **Profile 四步验证**：如做 profile 接口时实现

### 不做

- 复制 `openbox-panel/` 的 Node.js 代码（clean-room 违规）
- 授权/激活/验签（用户已排除）

---

## 六、风险提示

1. **报告本身的可靠性**：第三方报告自称 clean-room，但其 `state-model.md` 引用了 `index.mjs:10919-10943` 这类精确行号，说明其分析深度超出纯黑盒。我们将其作为"交叉验证"而非"唯一真相源"——凡与我们黑盒实测冲突处，以实测为准。
2. **版本差异**：报告基于 v0.1.330，我们对照的是 v0.1.331。 minor 版本差异可能导致个别行为不同。
3. **i18n key 命名空间不同**：第三方重命名了 key（如 `routXxx`、`subsXxx`），不能直接 diff，需按 value 语义对比。

---

## 七、总评

**这份报告对开源面板开发非常有帮助，评级：A-**

- **最有价值**：24 枚举（交叉验证）、81 路由测试向量、43+86 分享链接测试向量、行为规范 §5（故障转移/DNS/入口绕过/备份的验收标准）
- **中等价值**：122 端点清单（覆盖率检查）、state-model（架构确认）、desktop-client（obclient 符号表）
- **无价值/不可用**：`openbox-panel/` 的 Node.js 实现代码（不可复制）

建议将其 `panel-contract/` 纳入我们的 `oss/docs/` 作为长期参考（仅行为契约部分），并立即启动 P0 的两项工作。
