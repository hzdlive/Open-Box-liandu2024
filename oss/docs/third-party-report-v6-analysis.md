# 第三方研究报告 v6 分析（Open-Box-liandu2024-6.zip）

- 来源：`workspace/user/files/Open-Box-liandu2024-6.zip`（456 条目，解压 124MB）
- 结论：**v5 的严格超集，零删除**。新增 19 个文件，5 个同名文件内容变更。
- 评级：**A-**（与 v5 持平；部署管线收尾，行为契约密度高，但 POST /deploy 本体仍未落地）
- 路由面未变：122 路由 105 已实现 / 17 stub（与 v5 相同）；测试全量 **52 套件 / 3437 断言全绿**（v5 为 42 套件 / 2877 断言，新增 10 套件 / 560 断言）

## 一、变更清单

### 新增 19 个文件

| 类别 | 文件 |
|---|---|
| 分析者备忘录 | `.workbuddy-ai/memory/2026-10-23.md`（Wave 5 #11–#21） |
| 热切换计划 | `src/core/deploy-flip.mjs`（v5 已有，本次改动见下）+ `test/panel-wave5-deploy-flip.mjs`（90 断言） |
| 不需内核的叶子 | `src/core/deploy-leaves.mjs` + `test/panel-wave5-deploy-leaves.mjs`（60 断言） |
| 翻转本体 + 选择同步 | `src/core/deploy-hotflip.mjs` + `test/panel-wave5-deploy-hotflip.mjs`（52 断言） |
| 部署前规则集阶段 | `src/core/deploy-rulesets.mjs` + `test/panel-wave5-deploy-rulesets.mjs`（43 断言） |
| 入口旁路 nft 侧 | `src/core/native-bypass.mjs` + `test/panel-wave5-native-bypass.mjs`（59 断言） |
| 选择快照与翻面 | `src/core/clash-selection.mjs` + `test/panel-wave5-clash-selection.mjs`（66 断言，含 #17 的 gv） |
| 域名过滤编译 | `src/core/dns-filter-artifacts.mjs` + `test/panel-wave5-dns-filter-artifacts.mjs`（61 断言） |
| 代理 DNS 上游表 | `src/core/dns-upstreams.mjs` + `test/panel-wave5-dns-upstreams.mjs`（50 断言） |
| 防抖选择同步 | `src/core/selection-sync.mjs` + `test/panel-wave5-selection-sync.mjs`（30 断言） |
| 部署服务 | `src/core/deploy-service.mjs` + `test/panel-wave5-deploy-service.mjs`（49 断言） |

### 内容变更的 5 个同名文件

- `.workbuddy-ai/memory/MEMORY.md`（52 套件 / 3437 断言）、`TRAPS.md`（新增 292–327+ 条）
- `openbox-panel/README.md`、`package.json`（包版本仍 0.1.0，**未提新 release 版本号**，基线仍按 v0.1.344）
- `src/core/deploy-flip.mjs`（补 `enabledOutbounds`：停用订阅的节点要过滤，见三.1）

## 二、Wave 5 #11–#21 摘要（部署管线收尾）

`runDeploy` 的 `deps` 叶子至此全部到齐，只剩 `POST /deploy` 路由本身（分析者明确留到下一轮，
因 `deps` 装配有两个非机械映射：`writeFlip` 要读**正在跑**的 flip 计划做差、`clashConfig` 要拼 store 的 secret）。

1. **#11 deploy-flip（热切换计划与写入器）**：路由表从不写节点名、只写策略，面板把策略映射成固定
   `obflip-<sha256(id|name)[0:12]>`；规则集三态（`full` 拷自内置 geo 集 / `placeholder` 空集 / `sha:…` 可复现），
   塌错方向都会坏事；`zp` 五阶段顺序是功能性的（长 need → 缩 bypass → 翻 flag → 长 bypass → 缩 need，
   每阶段间 `sleep(200)`，内核在 watch 目录，顺序错会 reload 到正在 rename 的文件）；`dynamicBypass`
   语义：n=true 写全部 bypass + 全部 need，n=false 只写开着且有 trimmed 的 bypass、一个 need 都不写。
2. **#12 deploy-leaves（三个不需内核的叶子）**：链式代理跳过是「一轮丢一个」的循环（丢 B 可能让 A 变孤儿，
   最多 `count + 2` 轮）；reason 不对称：自指是 `upstream` 不是 `cycle`、互指只报一个 `cycle`；
   `resolveHosts` 每名并行解析、各自超时、失败只贡献「无」（防火墙清单不能因一个 DNS 不通全断）。
3. **#13 deploy-hotflip（翻转本体）**：`Py` 是选择同步处理器（先试热切换拿排他锁，失败再判是站点集翻面
   还是第一层计划变了，否则什么都不做）；`iy` 是 `bu` 的逆运算（把 sidecar 的 `firstLayer.inputs` 盖回当前
   profile，否则每次编辑都被报成 flag 变更）；「没有 flag 会变」返回 `ok:true` 但形状不同（无 `need` 键）；
   新计划必须按 sidecar 已知 tag 过滤（翻转绝不能引入新集合，否则等于重启）；纯 tun 不写
   `firstLayer.nativeBypass*`（保持上次样子，不是写 `false`）。
4. **#14 deploy-rulesets（部署前规则集阶段）**：跑 pipeline 之前先把用户名单更新一遍，失败以
   `stage:"rulesets"`（503）结束、内核一步都不碰。24h TTL + URL 匹配 + 文件在盘上三条件与在一起才复用；
   「在盘上」两个半边都算（`<tag>.srs` 或 `<tag>-ip.srs`）；老版式从本地文件重编、不重新下载；
   失败三支：无本地副本 → 致命、无本地副本 + optional → 跳过记日志、有本地副本 → 沿用旧记录且老版式当场迁移
   （致命那支在写表之前返回，半张表比没有更糟）；`keepOthers` 默认 `false` 是故意破坏性的；
   只有字符串化形式变了才写表。
5. **#15 native-bypass（入口旁路 nft 侧）**：三个扣减按顺序：地址空间末尾一位（`255.255.255.255` /
   `ffff:…:ffff`，某些内核上放进集合会让整段命中）→ FakeIP 池（入口放行它等于真实目标永远不被解析）
   → 前面集合已覆盖的部分；扣完不剩是**回落**不是空集合。四种回落话术：域名条件、逻辑/取反（范围说不清）、
   别的条件如 `port`（放行会放大范围）、压根没有 `ip_cidr`；`reason` 用 `;`（无空格）拼。
6. **#16 clash-selection（选择快照与翻面）**：真相在内核不在库里——`readClashSelection` 只收带 `now` 的条目；
   `reconcileSelection` 写回 `routing.policies[].default`（查表键是 trim 过的策略名、命中内置组 tag 要变回
   `direct`/`block` 关键字）；`selectionSnapshot` 是「给了就存 + 对账、没给就读回来」的包装（两个副作用各自一个 try）；
   `siteSetsFlipped` 只比两边都有的键、读不出来答 `false`（假阳性会让每次防抖同步都重启内核）；
   什么都没变就不调 `setProfile`（会 bump revision 并重跑迁移）。
7. **#17 firstLayerChanged（`gv`）**：三层按便宜在前排序——bypass 计划（有 `nativeBypassPlanKey` 就一次哈希比，
   没有就手比 set 名 + pending 名；任一侧 `pending.length > 0` 都算变）→ 策略分类（只在可见开关本来就开着时
   重算）→ DNS 转发计划（只在 dnsmasq 模式比；域名过滤一开整个计划被覆盖成 `{mode:"all"}`）；前面命中就
   `true` 返回，后面的 RPC 压根不发。
8. **#18 dns-filter-artifacts（域名过滤编译）**：部署里最贵的一步，三道闸门按代价从小到大——key + hash 表 +
   文件是否还在（缓存命中，连一次名单 `stat` 都不做）→ 每条名单 10 分钟重试冷却 → 160 MB 内存下限；
   单条名单 250 000 matcher、所有名单合计 400 000；每个 `.srs` 用所依据文档的哈希命名（没变的块不重编）；
   一个失败的名单不等于一次失败的部署（有旧副本 → 记 `missing` + 每条 `error` 继续；无副本 + 无 force → 记
   `missing` 继续；无副本 + 有 force → 错误抛给用户）。
9. **#19 dns-upstreams（代理 DNS 上游表）**：内核发出 `dns-proxy` 出站时它还没有 `detour`——这张表逐个回答
   「宿主自己的解析器，直连」还是「出站、归属策略和判定的那条规则」。两处不对称：代理侧兜底是
   `1.1.1.1`/tcp、**永远不是**宿主解析器（等于用户要求走境外的查询被本地解析 = 泄漏），直连侧正好反过来；
   `"wan"` 哨兵直接给 `wan: true` + `direct` tag；扩展项最多 3 个、和基础行去重、非字面量整项丢掉；
   `rn` 的两个 reject 来源：`matched.action === "reject"` 或 `finalOutbound === builtin.block`（后者不是冗余）。
10. **#20 selection-sync（防抖选择同步）**：面板把内核 Clash API 原样代理出去，用户切代理时 profile 完全不知情，
    `hD` 补这一环：尾随防抖（每次调用重置，连切五个只跑一次、跑最终状态）；定时器在体开头清空（跑的过程中
    来的切换会再排一次，放结尾会吞掉）；两个 try 互相独立（刷 DNS 缓存失败不阻止同步、同步失败只 log 不抛，
    因它跑在定时器里没有请求可答）；顺序是刷新 → 读选择 → 快照/对账 → 同步（选择在刷新**之后**读才是重点）。
11. **#21 deploy-service（状态表、十二个适配器、队列）**：`Ny` 状态码表——conflict/validate/cancelled → 409
    （请求没问题，是世界不配合）、rulesets → 503（缺依赖）、start/verify/error → 500、未知 stage 也是 500、
    `ok:true` 先短路；`deps` 四条陷阱：`writeFlip` 写的是流水线传进来的 `ctx`/`paths`、 `nativeBypass` 从 store
    读 profile 而 `flipPlan` 从参数读（必须用刚 build 的那份，合过 failover）、`chainSkips` 返回 `.skipped`
    而不是 `.nodes`、`dnsFilterApply` 必须转发 `force`；generation 在入队前取（队列回调里取会让排队中的部署
    对 stop 免疫）；三个适配器故意不传（`dnsUpstreamRoutes` 要 `Yl`、`hotFlipReconcile` 要热翻转 apply 半边、
    `rulesetExtra` 要 `Ss`/`kr`），`runDeploy` 三处都有 `deps.x &&` 守卫，缺它们是「小一点的部署」不是坏部署。

## 三、屏蔽项（重申，与 v5 相同）

- 两份 reversed JSON 与 v5 **字节相同**（MD5：core `48fe1849e8bcbab1db4373a4edbc0c0d`，
  windows `2cf4a789916194e1afd8ccb85dc47175`），继续屏蔽，不可用。
- `src/` 全部为反混淆实现：仅行为对照，不复制。`rea-tools/*.exe` 不使用。
- 与黑盒实测冲突时以实测为准。

## 四、与我们实现的对照（已在代码里核实）

### 已有（v6 不新增工作）

- **停用订阅过滤**：v6 #12 补的 `enabledOutbounds`（停用订阅节点不得进配置）我们早已在
  `load_app_config` 做（`WHERE s.enabled = 1 AND n.disabled = 0`），无动作。
- **DNS detour**：cn 时 proxy DNS 走代理组、outside 地区直连是文档化的有意行为（无 GFW 可绕），
  且 `detour: "direct"` 会被省略（sing-box 1.14 拒绝 detour 指向 plain direct 出站）——与 v6 #19
  的「代理侧兜底永不是宿主解析器」在 cn 语义下一致，无泄漏。
- **热切换机制**：原版 obflip 文件交换与我们的 selector-now 方案行为等价（热切换无需重启），
  #11 的三态 / `zp` 五阶段 / `sleep(200)` 是他们机制的内部细节，无需跟。

### 缺口（按价值排序，供用户选）

1. **选择同步（原生组切换旁路 DB，推荐先做）**：策略卡经 `/select` 落盘 ✓，但原生节点 Tab 的组切换走
   `axios.put('/proxies/{group}', {name})` 直连 Clash API，不经过后端；且 selector 组的 `default` 在 build 时
   恒为 `tags[0]`，下次 apply 会把原生切换复位。v6 #16/#20 给了完整机制：只收带 `now` 的条目 → 写回
   profile 默认值（内置组 tag 变回 `direct`/`block` 关键字、什么都没变就不写）→ 600ms 尾随防抖同步
   （刷新后读选择）。注意 urltest 的 `now` 是内核算出来的，不是用户选择，写回时要区分。
2. **规则集 24h 刷新语义**：我们待办里的 rule-set 24h 自动刷新一直没做；v6 #14 给了完整行为（24h TTL +
   URL 匹配、双半边文件算在盘上、老版式离线重编、失败三支、`keepOthers=false`、仅字符串化变化才写表），
   可直接套用到规则集与内容过滤名单刷新。
3. **链式前置校验**：`create_chain`/`update_chain` 只校验 `exit_protocol`，不校验 front 存在性、自指、成环；
   front 是任意字符串，环可经组间接构成。v6 #12 给了丢弃语义（自指 = upstream、互指 = 单 cycle、
   一轮丢一个最多 `count + 2` 轮）。现网 7 条链 presumably 无环，但 API 可直接写出环。
4. **内容过滤冷却与上限**：现有 512KiB 单条上限；缺失败冷却（死链每次部署都重打）、250k/400k matcher 上限、
   哈希命名 `.srs`（我们不编 `.srs`、扁平化为 domain_suffix，量级不同——按需取）。
5. **入口 CIDR 三扣减（边缘）**：nft 集合生成只做 `normalize_cidr`，无广播地址排除、无 FakeIP 池排除、
   无重叠去重；现网直连列表撞上这三类的概率低，属边缘加固。

### 结构性差异（注明，不急于改）

- 原版正在收敛到单一 `POST /deploy`（preflight → assembly → start + 锁队列 + 状态码表）；
  我们是 apply + start 两步，pieces 都有（check 门、冲突门、verify、bad_node 定位）但没有统一管线与状态机。
  v6 本身也还没落地 POST /deploy（他们的下一步），所以这条线两边都还没收口。

## 五、建议的下一步（按价值排序，供用户选）

1. **选择同步**（推荐先做）：原生组切换写回 profile 默认值 + 600ms 防抖，堵住「apply 复位原生切换」的口子。
2. 规则集 24h 刷新：按 #14 语义落地规则集与名单刷新。
3. 链式前置校验：create/update 时校验 front 存在性、自指、成环（或 apply 时报丢弃）。

以上三条均为 v6 对照建议，未经用户点头不开工；基线跟进 v0.1.344 之后版本仍按用户决定暂不做。
