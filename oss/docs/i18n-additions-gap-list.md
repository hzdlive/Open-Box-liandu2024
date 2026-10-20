# 未实现功能清单 v2（i18n additions 聚类）

- 来源：第三方报告包 `Open-Box-liandu2024-2.zip` 中的 `open-box-panel-i18n-additions.txt`（1610 个 key，行为层 UI 文案，可用；包内两个 `*-reversed.json` 为反汇编/逆向产物，已屏蔽未碰）。
- 方法：1610 keys 按 camelCase 前缀聚成 111 组；逐组对 live 分支（`oss-zashboard` @ `73ed7b3`）做代码级核验（前端 `zashboard-src` + 后端 `oss/panel`），key 改名不算数，只看功能是否存在。
- 诚实说明：1610 个 key 名中只有 16 个与我方 key 名重合——双方 i18n 命名体系不同，所以"key 不在"不等于"功能不在"，下表每项都经代码核验。"additions"是相对 v1 版 1753 keys 的增量，天然偏向原版近期新增功能，正好对应"下一步做什么"。
- 对照基线：2026-10-19 18:52（CST）核验上游 Releases 页，最新仍是 **v0.1.341**，无更新。

## 出范围（不列入）

| 组 | 原因 |
|---|---|
| `activation*`（14） | 授权/激活——clean-room 明确 out of scope |
| `client*`（72） | 客户端 App——用户已明确"客户端先不管" |
| `pagination`/`http`/`chart`/`timezone`/`globe`/`unit`/`stat`/`copy` 等 | 纯 UI 琐碎项，无功能含义 |

## P0——核心功能缺口（建议优先排期）

| # | 功能 | 依据 keys | 现状核验 |
|---|---|---|---|
| 1 | **路由诊断工作bench**：分阶段路由追踪（起点→DNS→入口→规则→出口），含 DNS 假设/实测对比、入口旁路命中判定、终端事件检测（netns/veth/bridge/conntrack/dhcp/masq）、规则命中 diff、出口连通测试 | `route*` 252 个 | 缺失。阶段一穿透测试（`/api/openbox/penetration` + SitesTab UI）只是它的子集，原版有一个完整诊断台 |
| 2 | **选择性备份**：按部件备份（订阅/节点/链式代理/客户端路由/面板配置）、append/replace 两种合并模式 | `backup*` 32 个 | 缺失。后端只有整库备份；gap 3 方案已备好待开工 |
| 3 | **手动添加服务器**：协议/加密方式/obfs/TLS/分享链接全套节点录入 | `server*` 43 个 | 缺失。manage 各 tab 无"添加节点"入口 |
| 4 | **流量统计**：按客户端/主机/节点 drill-down，日/月汇总、留存期配置 | `traffic*` 43 个 | 缺失。Connections 页只有实时连接 |

## P1——高价值单项

| # | 功能 | 依据 keys | 现状核验 |
|---|---|---|---|
| 5 | **规则查询与命中统计**：规则 lookup 工具、命中/未命中图表 | `ruleLookup*`/`ruleHitChart`/`ruleMissChart` | 缺失 |
| 6 | **订阅节点批量重命名**：模板+国家/地区/特征词典+序号 token | `subscriptionRename*` 约 30 个 | 缺失 |
| 7 | **按国家自动建组**：urltest/selector/failover 三类自动组 | `groupAuto*` 约 15 个 | 缺失 |
| 8 | **节点详情**：ASN/归属地/入口 IP/出口 IP/IPv6/风险评级 | `nodeInfo*` 30 个 | live 分支缺失（旧 oss 分支 Proxies.vue 有过） |
| 9 | **内容过滤收尾**：规则集 URL 快照下载、同步、iOS 同步提示 | `cfUrl`/`cfSyncHint`/`cfSnapshotHint` 等 | 部分（阶段二只接了 sing-box 生成） |
| 10 | **面板自升级 UI**：升级通道（直连/镜像）、分阶段进度对话框 | `obUpdate*` 43 个 | 后端 `/api/upgrade/*` 有，live 前端无入口 |
| 11 | **内核管理 UI**：启动/停止/重启、运行时长、冲突提示、部署状态 | `kernel*` 35 个 | live 分支缺失（只有版本显示+开机自启；旧分支有 Kernel.vue） |
| 12 | **恢复出厂** | `factoryReset*` 5 个 | live 分支缺失（旧分支有过） |

## P2——细节与体验

| # | 功能 | 依据 keys | 现状核验 |
|---|---|---|---|
| 13 | 自定义测速站点 | `testSites*` | 缺失（阶段三只做了故障转移组测速入口） |
| 14 | 共享网络地区规则 | `shareRegions*` 约 40 个 | 缺失（ShareTab 只有共享开关+订阅分享） |
| 15 | IPv6 代理选项（按 v4/v6/节点分流） | `ipv6Proxy*` 9 个 | 缺失（只有总开关 `ipv6`） |
| 16 | Geo 数据更新计划 | `geoUpdate*` | 缺失（geodata.ts 只有分类下拉数据） |
| 17 | 穿透多模式：域名穿透/逐步/策略模式 | `domainPenetration*`/`stepwisePenetration`/`strategyPenetration` | 缺失（阶段一只做了基础穿透） |
| 18 | 穿透结果丰富度：链跳展示、出口节点、策略目标 | `penetrationChainHop`/`penetrationExitNode`/`penetrationPolicyTarget` 等 | 部分 |
| 19 | 代理页显示选项：排序/分组布局/列数 | `proxySortType`/`proxyNodeSortBy`/`proxyGroupLayout` 等 | 缺失 |
| 20 | 图标管理：分类/缩放 | `icon*` 8 个 | 缺失 |
| 21 | 待重启提示（配置变更后 toast + 原因） | `restartPending*` 8 个 | 缺失 |
| 22 | 规则显示/匹配顺序设置 | `policyDisplayOrder`/`policyMatchOrder` | 缺失（前置规则拖拽排序已做，不是一回事） |
| 23 | 订阅单节点 DNS（bootstrap/DoH） | `subscriptionNodeDns*` | 缺失 |
| 24 | 站点延迟测试 | `siteLatency*` 7 个 | 缺失 |
| 25 | 新手引导 | `tutorial*` 4 个 | 缺失（低优先级） |
| 26 | 上游 DNS 的 WAN 专项配置 | `dnsUpstreamWan*` | 部分（DnsTab 有 wan 地址概念，无专项配置） |
| 27 | 隐藏 DNS 连接/使用服务器代理 | `hideDnsConnections`/`useServerProxy` | 部分（只有 hideUnavailableProxies） |
| 28 | 故障转移"恢复保持"UI | `failoverHold*` | 后端 60s 保持已实现；GroupsTab 无对应设置项 |

## 待确认（需要你拍板或对原版 UI 实测）

| # | 功能 | 依据 keys | 说明 |
|---|---|---|---|
| 29 | `aiRelay*`（3 个：aiRelayLabel/aiRelayOnDemand/aiRelaySubscription） | 3 | 含义不明，疑似"AI 中继"新功能；需对原版 UI 实测确认后再定是否做 |
| 30 | `docker*`（17 个） | 17 | Docker 部署页；你跑的是 Debian 裸机 VPS，默认不做，除非你想加 Docker 分发 |

## 已实现（无需动作，供对照）

`df*` DNS 查询日志、端口旁路黑/白名单、`tun*`（stack/MTU/MSS）、dnsmasq DNS 模式、链式代理、故障转移核心、订阅预览/分享/QR/排序/停用、DNS 重写/上游/地区、12 默认分流策略、前置 8 规则类型、obflip、诊断导出（`/api/diagnostics`）、备份脱敏导出、密码登录、主题、QUIC 屏蔽、直连旁路（P0）、`groupExpectedStatus`、`hideUnavailableProxies`。

## 与待决策项的对应

- 待决策 #3 `invert` 字段：`groupInvert` 在 additions 里只有 1 个 key，属 P2 细节，与评估一致。
- 待决策 #1 内容过滤默认规则集：对应上表 #9，做了默认规则集则"恢复默认"可一并落地。
- 阶段四终端分流真机验证、阶段五 DNS 钩子：additions 未覆盖（i18n 触及不到），仍按原计划。
