# 三项对标分析汇总：完整 TODO 方案

> 分析日期：2026-10-19
> 分析人：Muse（三个并行子代理）
> 资料来源：第三方报告 v1/v2（行为类部分）+ REA 摘录 + 我方代码
> 合规：已屏蔽 `open-box-core-reversed.json` / `open-box-windows-reversed.json`（逆向产物）

---

## 一、🔴 内容过滤：形态确认 + 迁移 TODO

### 原版形态（确认）

**原版是 Surge/QuantumultX 规则集管理器**，不是域名黑名单：

- 用户添加规则集（三种输入：上传文件 / HTTPS URL / 粘贴文本）
- 面板解析规则 + 下载脚本，保存为**快照**
- 同步到 iOS 手机**离线运行**（"Sync does not enable filtering"——同步≠启用）
- 三种规则动作：`reject`（URL 正则，路由器可转 block）/ `script`（仅 iOS）/ `replace`（仅 iOS）
- **512 KiB** 文本上限；导入是**有损的**（`skippedScripts`/`skippedUnsupported`/`skippedRouting`/`skippedUnrepresentable` 四个计数器）
- 快照语义：更新失败保留旧版
- 客户端 API：`/client/v1/:routerId/config/:token/content-filter/:hash`（内容寻址）

### 我们当前的差距

| 维度 | 原版 | 我们 |
|---|---|---|
| 本质 | 规则集管理器 | 域名黑名单 🔴 |
| 规则集数量 | 用户可增删 | 固定 3 个 🔴 |
| 规则格式 | URL 正则 + 脚本引用 | 纯域名 🔴 |
| 脚本支持 | 下载保存供 iOS | 无 🔴 |
| iOS 同步 | 内容寻址 API | 无 🔴 |

**核心差异**：我们的模型丢失了 90% 信息（URL 路径、脚本、replace 规则无处存放）。

### 待用户决策（5 项）

1. API 路径用原版 `/api/openbox/content-filter` 还是保留现有 `/api/content-filters`？
2. 现有 3 个黑名单废弃还是迁移？
3. 是否预置"综合省流"等默认规则集？
4. iOS 同步接口优先级（取决于是否有 iOS 客户端）？
5. 路由器端只做 reject→block 吗？

### 迁移 TODO（用户决策后执行）

**阶段一：数据模型**
- [ ] 新建 `cf_rulesets` 表（id/name/dialect/source_url/text/rules/hostnames/arguments/scripts/enabled/updated_at/skipped_* 四计数器）
- [ ] 存量 3 条目迁移（按用户决策：废弃/兼容）
- [ ] API 路径决策落地

**阶段二：规则解析器**
- [ ] Surge 解析器（`[Rule]`/`[URL Rewrite]`/`[Script]`/`[MITM]` 段）
- [ ] QuantumultX 解析器（`[rewrite_local]`/`[filter_local]`/`[mitm]` 段）
- [ ] 512 KiB 输入校验
- [ ] 脚本下载器（sha256 校验）
- [ ] 快照原子替换（失败保留旧版）
- [ ] skipped* 计数统计

**阶段三：后端 API**
- [ ] `GET/POST /api/openbox/content-filter`、`DELETE/PATCH /:id`、`GET /:id/source`、`POST /:id/refresh`
- [ ] `GET /client/v1/:routerId/config/:token/content-filter[/:hash]`（iOS 同步）

**阶段四：sing-box 生成**
- [ ] URL 正则 → 域名提取 → `domain_suffix → block`
- [ ] 替换现有 `get_blocked_domains()` 调用

**阶段五：前端重构**
- [ ] 规则集列表（`{rules} rules · {scripts} scripts` 计数）
- [ ] 新增/编辑弹窗（文件/URL/粘贴三种输入）
- [ ] 详情页（skipped* 显示、规则列表、脚本列表）
- [ ] `cf*` 系列 i18n key（22 个，四语言）

**阶段六/七**：默认规则集 + 测试

**工作量**：中等规模重构，约 5-7 天

---

## 二、🟡 故障转移 lane：位置建模重构 TODO

### 原版模型（一句话）

**id 定身份、位置定角色、名字纯展示**——三权分立：

| 维度 | 原版 |
|---|---|
| lane id | 随机稳定 id（`lane-<base36时间戳>-<5位随机>`），拖动重排不破坏状态 |
| lane 角色 | 按位置推导：`lane[0]`=primary，`lane[n]`=Backup n，不存名字 |
| lane 名字 | 可选（可为空），纯展示；空名回退显示 Primary/Backup n |
| 转 failover | 自动播种**两个**空 lane |

### 我们的差距（含一个 P0 bug）

| # | 位置 | 现状 | 严重度 |
|---|---|---|---|
| G3 | lane tag 生成 | **singbox.py 与 failover_sm.py 两处不一致**：多成员空名 lane，sing-box 实际创建 `组名#主用`，状态机却探测 `组名#lane0` → `apply_switch` 打到不存在的 proxy，**切换静默失败** | 🔴 **P0 真实 latent bug** |
| G1 | `failover_init` | lane id = `f"lane-{i}"`（位置式），重排后 `current_lane_id` 指错 lane | 🟡 |
| G2 | `failover_init` | 空名被伪造成"通道1/2/3" | 🟡 |
| G4 | lane tag 含名字 | 改名 → tag 变 → 状态过期 | 🟡 |
| G6 | 转 failover | 只播种 1 个空 lane（原版 2 个） | 🟡 |
| G7 | 存量数据 | `failover_state` 可能残留伪造名 | 🟡 |

### 重构 TODO

**Phase 1：数据模型——lane id 随机化（后端）**
- [ ] `db.py::_normalize_lanes`：lane shape 扩展为 `{id, name, icon, mode, members[]}`
- [ ] 新建 lane 生成稳定随机 id（`lane-<base36时间戳>-<5位随机>`）
- [ ] 存量 lane 读时补 id（幂等）

**Phase 2：状态机——去除名字伪造（后端）**
- [ ] `failover_init`：name 保持原样（空即空），删除 `f"通道{i+1}"`
- [ ] lane id 优先取配置 id，不再用 `f"lane-{i}"`
- [ ] 新增 `lane_display_name(lane, index)`：非空名→名，空名→主用/备用{n}
- [ ] 四语言 i18n：`obx.failoverPrimary`、`obx.failoverBackupN`
- [ ] `failover_finish` 日志改用 display label
- [ ] `/api/openbox/failover/status` 增加 `index`、`displayName` 字段

**Phase 3：tag 一致性修复（P0）**
- [ ] 新建统一函数 `failover_lane_tag(group_name, lane, index)`（放 `failover_sm.py`，singbox.py 引用）
- [ ] 单成员→成员 tag；多成员→`{group}#{display_name}`
- [ ] 两处手写 tag 逻辑删除，改调统一函数
- [ ] `failover_init` 加配置指纹比对：lane id/成员变化 → 丢弃旧 state 重建

**Phase 4：前端**
- [ ] 新建 lane 时前端生成 id
- [ ] 转 failover 播种**两个**空 lane
- [ ] `laneTabName` 改用 i18n key
- [ ] 删除确认弹窗用 display label

**Phase 5：存量迁移**
- [ ] 迁移脚本：补 id、清伪造名、重映射 `current_lane_id`
- [ ] 迁移前备份 panel.db

**Phase 6：回归测试**
- [ ] 新建 `test_failover_lanes.py`（6 个用例：空名显示、id 稳定、tag 一致、重排不丢状态、配置变更重建、播种 2 lane）
- [ ] VPS 真机验证：建分组 → check → recheck → iptables 故障注入 → 确认切换到正确 tag

---

## 三、🟡 入口绕过：自动模式 + release 集合 TODO

### 原版完整机制

**总开关**："直连不进内核"，**默认开**。开：直连流量在入口（nftables）放走；关：全进内核。

**两种自动模式**（无需配置，自动选择）：

| 模式 | 条件 | 行为 |
|---|---|---|
| Default-release (`blacklist`) | FakeIP 开且兜底直连 | 代理域名拿 FakeIP 必进内核；其余不在"进内核集合"就在入口放行 |
| Default-enter (`whitelist`) | 其他 | 只有直连 IP 集合（默认 geoip-cn）在入口放行；与代理集合重叠网段先减去 |

模式切换**只重写规则集文件，内核不重启**；规则页显示模式及原因。

**Direct-answer release**（仅 blacklist 模式）：入口只能看到 IP，CDN 后的直连站点地址可能落在代理集合内。机制：在把直连 DNS 应答交给设备**之前**，内核先把地址写入**限时入口放行集合**：
- TTL = DNS 缓存时间，**最少 15 分钟、最多 1 天**
- **重启持久化**，启动时按剩余时间重写
- direct→proxy/reject 或路由变更时**全清**（连带 dnsmasq 缓存）；proxy→direct 只删相关条目

### 我们的差距

**已有**：`direct_bypass_kernel` 设置（但默认关）、直连域名 ipset、旧前端开关。

**缺失**（🔴）：总开关默认开且新版前端无开关；自动模式选择（无 blacklist）；entryPlan 规划函数；规则页模式显示；direct-answer 集合；直连设备首包预判。

### 补齐 TODO

**A. 数据模型与设置**
- [ ] `direct_bypass_kernel` 默认改为 `"1"`（新安装默认开，存量保持）
- [ ] 新建 `oss/core/entry_plan.py`：`entry_plan()` 返回 `{mode, reason, need_cidrs, need_sets, direct_answer}`
- [ ] blacklist 条件 = FakeIP 开且兜底 direct

**B. Direct-answer 集合**
- [ ] 新建 `direct_answer_ips` 表（ip/expires_at/source）
- [ ] TTL clamp 15min~1天
- [ ] 面板启动重建 nftables set
- [ ] direct→proxy 全清 + dnsmasq 缓存清；proxy→direct 精准删
- [ ] transparent.py 新增 set，prerouting 优先 accept
- [ ] ⚠️ **最大风险**：写入时机（sing-box 无钩子），v1 面板侧异步写入并诚实标注"近似实现"

**C. nftables 联动**
- [ ] TransparentConfig 新增 `entry_mode/entry_cidrs/direct_answer_set`
- [ ] blacklist 逻辑（进内核集合外全放行）
- [ ] whitelist 逻辑（直连集合放行、重叠网段减去）
- [ ] app.py 改调 `entry_plan()`

**D. 前端**
- [ ] 恢复总开关（复用已有文案）
- [ ] 目标分流页新增"入口绕过状态"区（模式+原因）
- [ ] 新增 `GET /api/openbox/entry-plan`
- [ ] 四语言 i18n 补 key

**E. 直连设备**（v2）
- [ ] 首包预判 nftables 规则
- [ ] 按设备 DNS（面板 DNS 代理层按源 IP 区分）
- [ ] FakeIP 误发回退

**F. 验证**
- [ ] entry_plan 单元测试
- [ ] TTL 边界、重启持久化、清空规则
- [ ] 真机 CDN 站点首连验证

**优先级**：A → D → C → B → E（A+D 即可让用户看到"模式及原因"，性价比最高）

---

## 四、执行顺序建议

| 顺序 | 任务 | 原因 |
|---|---|---|
| 1 | **内容过滤形态决策**（用户） | 阻塞后续 5-7 天工作，需先拍板 5 个问题 |
| 2 | **故障转移 lane Phase 3**（P0 bug 修复） | 真实 latent bug，切换静默失败 |
| 3 | **故障转移 lane Phase 1/2/4/5/6** | 完整重构 |
| 4 | **入口绕过 A+D** | 用户可见的"模式及原因"，性价比最高 |
| 5 | **入口绕过 C+B** | nftables 联动 + direct-answer |
| 6 | **内容过滤迁移**（用户决策后） | 大重构 |
| 7 | **入口绕过 E** | v2 优化 |

---

## 五、需要用户拍板的

### 内容过滤（5 项，阻塞）
1. API 路径：原版 `/api/openbox/content-filter` 还是保留 `/api/content-filters`？
2. 现有 3 个黑名单：废弃还是迁移？
3. 是否预置默认规则集？
4. iOS 同步接口优先级？
5. 路由器端只做 reject→block？

### 故障转移（1 项）
6. lane id 格式：`lane-<base36时间戳>-<5位随机>`（对标原版）还是 `lane-<uuid4前8>`（更简单）？

### 入口绕过（1 项）
7. direct-answer 的"近似实现"（面板异步写入）是否可接受？还是要等找到 sing-box 钩子方案？
