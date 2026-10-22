# 第三方研究报告 v4 分析（Open-Box-liandu2024-4.zip）

> 解包：370 文件，122MB（zip 8.2MB）；v3 的超集（无删除，新增 35 文件）。
> 评级：**A-**（v3 为 B+；本包首次包含分析者的工作备忘录与 Wave 4 行为契约，信息密度最高的一版）。

## 一、结构变化

- 新增 `.workbuddy-ai/memory/2026-10-21.md`：分析者 Wave 4 工作备忘录（第 12–19 刀），是本包最有价值的部分。
- 新增 `openbox-panel/src/core/` 11 个模块 + `src/handlers/` 6 个模块：原版面板 Node.js 实现的反混淆还原——**不可复制，仅行为对照**。
- 新增 `openbox-panel/test/panel-wave4-*.mjs` 9 套测试（共 564 断言，见备忘录计数）。
- 新增 `openbox-panel/.tmp-cp/`：真机面板状态快照（groups/nodes/subscriptions/profile/service/deploystate，供测试夹具用）。
- `panel-contract/`、`defaults/` 与 v3 完全相同；两份 reversed JSON 与 v3 字节相同（MD5 校验，**继续屏蔽**）；failover-engine.json 与 v3 相同。

## 二、Wave 4 交付的行为契约（可用，取行为、弃实现）

分析者口径：122 条注册路由中 105 已实现、17 仍为 stub。以下按对我们的价值排序：

### 2.1 自我更新 5 路由（我们完全没有，属功能缺口）

`GET /api/openbox/update/status`、`check`、`notes`，`POST /update/run`、`cancel`。关键行为：
- 面板自己不装任何东西：`run` = `sh <root>/update.sh --detach` 后立刻返回，进度靠脚本写的 `/tmp/openbox-update.status` 读回；
- `running` 必须 pid 还活着（`process.kill(pid, 0)`，EPERM 算活着），否则僵尸状态文件永久锁死升级按钮；
- `bytes`/`total` 缺省是 `null` 不是 0；`pid` 是字符串；
- `status` 永不失败（五个读各自降级），只有 `check` 会 503；
- 镜像阶梯四档，`HEAD` + `redirect:"manual"` 读 Location；`via` 报成功那档；
- `notes` 先 API 后 `release-notes.md` 资产（以 `<` 开头视为劫持登录页而跳过）；
- `run` 校验顺序：平台 → channel → 在跑 → 脚本。

### 2.2 client-config 前两条（与我们客户端方向相关）

`GET /client-config`、`PUT /client-config/enabled`：
- GET 会写库（无设备时第一次读就铸进 `openbox/client-devices`）；
- token 为 48 hex（24 字节），`tokenHash` 为 64 位 sha256（不做形状校验），查表用 `timingSafeEqual` 先比长度；
- 多个设备塌缩成一个（取 `lastSyncAt` 最新的有效行复用，列表重写成 `[它]`）；
- `enabled` 只有字面量 `"0"` 算关，且是 `/client/v1/*` 的总闸（关掉先答 `403 disabled`，连 token 都不看）；
- 返回八个键：`device`（投影，不含 token/tokenHash/key）、`enabled`、`token`、`key`、`routerId`、`routerName`、`lanAddresses`、`panelPort`。
- 第三条 `GET /client-config/file` 未做（要配置生成器 + 视图构建器 + 加密）。

### 2.3 config/preview（最大认知修正）

`GET /api/openbox/config/preview`：
- **配置生成器根本不在面板里**：是一条核心 RPC（`configDetailed`），面板只做参数装配；
- `configDetailed` 的 `value` 是信封 `{config, failover, dnsRuleOwners, directHosts}`，不是 config 本身；
- 真机 outbound 顺序：分组（`__fo:` 车道紧跟所属分组）→ 内置策略（Speed/AI/Youtube/…）→ 节点 → 链节点；
- 内置规则集路径在核心答完后改写，只认 `/^(geoip|geosite)-.+/`（真机 77 条里 32 条被改写）。

### 2.4 service/status + deploy/state（只读两条）

- `running` 是三个条件：退出码 0 **且** 出现 `running` **且** 不出现 `no instances`（procd 对"已启用但已停止"的服务会同时印两个词）；
- `uptimeSeconds` 在内核没跑时是 `null` 不是 0，由 `/proc/<pid>/stat` 第 22 字段对 `/proc/uptime` 算（切分要跳过最后一个 `)`，comm 可含空格括号）；
- 冲突检测两条判据：init 脚本说在跑，**或**安装路径出现在某进程 argv 里（惰性、最多跑一次）；
- `conflictAutoStopped` 是四元合取：内核没跑且有冲突且上次部署 stage==="conflict" 且 autoStopped；
- `deploy/state` 永远不返回 `null`（默认 `{stage:"idle",message:"",at:0,badTags:[]}`）。
- 真机验证的 service/status 来自 **Debian 13 systemd（非 OpenWrt）**，与我们 VPS 同平台。

### 2.5 rollback + 部署管线外围

- 锁（store 锁、租约、心跳、进程内队列、世代 cancel）、dnsmasq 还原（三个标记文件、备份消费时机、`uci revert` 兜底）、防火墙移除（uci × nft `!fw4:` 对账）、拆除编排与回滚；
- `POST /service/core/:action` 故意没注册（start/restart/stop 依赖管线，只有 enable/disable 能单独工作）。

### 2.6 订阅公开分享

`GET /sub/:token`：token 即凭据（与 `/api` 闸门互不干扰）；未找到时 404 纯文本 `subscription share not found`；成功才加 `no-store`。

### 2.7 防火墙构建半（OpenWrt 向）

11 个导出：读/改 uci section、协议→proto、六段规则（面板端口、DNS 7853、TUN 转发/入站、IPv6 封堵、分享规则同步），六段只 commit 一次；`systemd`/`container` 整段跳过。DNS 端口 7853 是常量，与面板端口无关。

### 2.8 nft 入口旁路规则（与我们 transparent.py 直接相关）

`entryBypassRules` 五段规则集文本及配套规范化：
- `normalizeCidr`：裸地址补 `/32`、`/128`，前缀越界拒绝；
- `normalizeMac`：短横线转冒号，六组十六进制校验；
- `bypassPorts`：黑白名单两个字段**不合并**；一条坏项否决整串；
- `tunTcpMss`：0 或 536–65495；
- **MAC-only 的 admit 路由一条规则都不产生**（admit 块的门是 `admit.ips.length`）；
- 默认 profile 产出空字符串（无旁路端口、无 clientRoutes、tcpMss 0 时）。

## 三、仍为 stub 的 17 条（分析者下一刀方向）

`client`（9，`/client/v1/*`）、`deploy`（2）、`diagnostics`（4）、`GET /client-config/file`、`POST /sub/:token`（已做？备忘录前后口径不一，以 17 stub 为准）、`POST /dns-filter/apply`，以及部署管线本体 `vv`（规则集落地 `Ip`、校验 `tn`/`ah`、自签证书 `Yh`、写 config+侧车 `K`、DNS 接管 `cu`/`eu`）。

## 四、版本证据

- 真机 `check` 拍到的最新版：**v0.1.344**（我们的对照基线为 v0.1.341，已落后 3 个版本）；
- 测试机当前版 v0.1.337。

## 五、屏蔽清单（延续）

- 两份 reversed JSON（字节同 v3）。
- `openbox-panel/src/**` 反混淆实现代码：**不可复制**，仅行为对照。
- 激活/验签相关；与黑盒实测冲突时以实测为准。

## 六、对下一步的建议

1. **入口旁路对齐**（2.8）：逐项核对我们 `transparent.py`——bypassPorts 黑白名单不合并、MAC-only admit 无规则、tunTcpMss 取值域、裸地址补掩码。
2. **service/status 语义**（2.4）：`running` 三条件与 `uptimeSeconds` null 语义值得对照我们的 `/api/service/status`。
3. **自我更新**（2.1）：我们完全没有，是独立功能块；若要做，按"面板只调 update.sh + 读状态文件"的架构做，不自己实现升级逻辑。
4. **基线跟进**：原版已到 v0.1.344，对照基线可考虑从 v0.1.341 前移到 v0.1.344（需先抓 release notes）。
