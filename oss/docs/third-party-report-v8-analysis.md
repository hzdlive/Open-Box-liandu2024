# 第三方研究报告 v8 分析（Open-Box-liandu2024-8.zip）

- 来源：`workspace/user/files/Open-Box-liandu2024-8.zip`（488 条目，解压 124MB）
- 结论：**v7 的严格超集，零删除**。新增 19 个文件，13 个同名文件内容变更（md5 实测，
  非时间戳比对）。
- 评级：**A**（v7 为 A-；本轮把参考实现从 108/122 推到**路由全量**，且分析者备忘录、
  测试与实现三处互相钉住；扣分只剩一处文档滞后，见下）
- 路由面：**122 路由 122 已实现 / 0 stub**（v7 为 108/14；v8 备忘录 #31–#35 连关 14 桩）
  ——但注意：包内 README 扉页仍写「120 implemented · 2 stubbed」、MEMORY 仍写
  「120/122、64 套件 4165」，那是 #34 的数字，#35 只改了测试没改散文。
  以代码为准：wave1 断言 `cov.implemented === 122`，`DIAGNOSTICS_KEYS` 四条齐全，
  wave1 的桩路由小节已改名为「no route is left unimplemented」。
  这是分析者「加一个路由 = 四处数字」老坑的第五次（见 v7 四.4）。
- 测试全量：**65 套件 / 4681 断言**（v7 为 60 套件 / 3807 断言）。
  算术：4165（#34 终点，MEMORY 逐项可加）+ 53（client-routes）+ 87（diagnostics-core）
  + 98（penetration）+ 120（route-test）+ 158（terminal-test，按 `await check(`
  调用数，与前四项逐项对上备忘录）= 4681。`test:all` 串起 65 个脚本。
  本机实跑：diagnostics-core 87/0 通过；其余四套因 npm 装依赖受阻未跑通，
  计数以 check 调用数 + wave1 断言文本为准（诚实保留，见末尾）。
- 包版本仍 0.1.0，基线仍按 v0.1.344

## 一、变更清单

### 新增 19 个文件

| 类别 | 文件 |
|---|---|
| 分析者备忘录 | `.workbuddy-ai/memory/2026-10-26.md`（Wave 5 #31–#34；#35 只有代码与测试，备忘录未写） |
| 客户端路由 | `src/core/client-regions.mjs` + `src/handlers/client.mjs` + `test/panel-wave5-client-routes.mjs`（53 断言） |
| 诊断底座 | `src/core/rule-match.mjs` + `src/core/dns-predict.mjs` + `test/panel-wave5-diagnostics-core.mjs`（87 断言） |
| 路由预言机 | `src/core/route-oracle.mjs` + `test/panel-wave5-penetration.mjs`（98 断言） |
| 路由实测 | `src/core/route-test.mjs` + `src/core/rule-text.mjs` + `test/panel-wave5-route-test.mjs`（120 断言） |
| 终端诊断 | `src/core/terminal-test.mjs` + `src/core/terminal-probe.mjs` + `src/core/fetch-timeout.mjs` + `src/core/kernel-log.mjs` + `test/panel-wave5-terminal-test.mjs`（158 断言） |
| 汇总工具 | `tools/sum-tests.cjs`（逐套件跑、解析四种汇总格式再相加；管道汇总会静默丢行，TRAPS 524） |
| 诊断路由 | `src/handlers/diagnostics.mjs`（四条路由一次齐：penetration、route-test、terminal-test、terminal-test/capability） |

### 内容变更的 13 个文件（要点）

- `.workbuddy-ai/memory/MEMORY.md`（总数句仍是 #34 的 120/122、64 套件 4165，未跟进 #35）、
  `TRAPS.md`（570 条，v7 为 444+ 条）
- `openbox-panel/README.md`（扉页仍是 #34 的 120/2；新增「The phone-facing surface」小节）、
  `package.json`（`test:all` + 5 个新脚本；依赖仍是 express/ws/yaml 三个）、
  `.gitignore`（stub-core 编译产物不入库）
- `src/handlers/index.mjs`（注册 `CLIENT_KEYS`、`DIAGNOSTICS_KEYS`；`IMPLEMENTED_KEYS`
  展开 `CLIENT_ROUTE_KEYS` 与 `DIAGNOSTICS_ROUTE_KEYS`）、`src/index.mjs`（`clientDeps`、
  三方共用的 `routeOracle` 闭包、`dnsDeps.routeFor` 经 `upstreamRoute` 适配、`diagnosticsDeps`）
- `src/handlers/client-config.mjs`（仅注释：`client-config/file`「故意缺席」改成「搬到了
  `handlers/client.mjs`」）
- `src/core/deploy-service.mjs`（适配器表 13→14 键：`dnsUpstreamRoutes` 经 `route-oracle`
  接上；**部署管线最后一个洞补上**，只剩 `rulesetExtra` 一个未接）、
  `src/core/geo.mjs`（补 `indexAddressHits`（`Hm`），返回命中地址的原始 CIDR 文本；
  索引保留 `raw4`/`raw6`，因为 `mergeIntervals` 会丢第三元素）
- 测试计数联动：wave1（`cov.implemented` 108→122、「无桩路由」小节改名）、wave2、
  wave5-deploy-service（适配器表断言 + `rulesetExtra stays absent`）

## 二、Wave 5 #31–#35 摘要

### #31 十个客户端路由（`Ow` + `SS` + `client-config/file`）

- 十条一次齐：公开四条只认 `routerId`（`home`、`regions`、`background`、`geodata/:tag`）、
  配对五条认 `routerId` + `token`（`config/:token` 及其 `content-filter`、`content-filter/:hash`、
  `rule-set/:tag`、`background`）、下载一条 `GET /api/openbox/client-config/file`。
- **两套守卫，失败语句必须不同**：公开四条是 `404 not found`；配对五条 token 错是
  `404 unpaired`、开关关是 `403 disabled`。合并就分不清「被移除」和「暂停分享」。
- 四个易错点：`?rules=2` 是**唯一**开启新方言的取值，版本 1 会整条丢掉 `ruleUrl` 规则；
  哈希算在闸门**之后**，只改 query 也改版本号；LAN 网段插在最前，抹主机位只对 IPv4
  （原版 32 位整数移位表达不了 `/128`，`/0` 要显式写 0）；`list-xxxxxxxx` 的 blob
  **只在被区域引用时才发**，否则 geodata 路由就是任意文件读。
- `res.sendFile` 换成读字节 + `res.send`，丢掉 `Last-Modified`/`Accept-Ranges`/range
  ——已知差异，写进 TRAPS 522，不是疏忽。
- 53 断言，10 个小节。结果：118/122，只剩 4 个 diagnostics。

### #32 诊断底座（`rule-match` + `dns-predict`，不关闭任何路由）

- `rule-match.mjs`：`Bo`/`Uu`/`Bu`/`sR`/`gt`/`Rc`/`ni`/`Ur`/`zo`/`Ei`，规则集匹配
  `Hu`/`ka`、索引加载 `Vr`、两个索引探针 `qm`/`ls`、内核匹配 `l0`。
- `dns-predict.mjs`：`fo`——哪台 DNS 会应答，以及为什么。
- **本波不关闭任何路由**（仍 118/122），理由诚实：四条路由共用这一层，先做路由
  等于把这层塞进 handler 草草了事。
- 纠正三处：`indexMatchesDomain` 入参是域名表，`null` 答 `unknown` 不抛 `TypeError`；
  `domain_suffix: ".example.com"` 带前导点是显式的「仅子域」，裸域不匹配；
  规则集匹配 exit 0 且无输出是**正常未命中**，错误要求 `code !== 0` 且 stdout/stderr 都空。
- 87 断言，11 个小节。结果：62 套件 3947 断言。

### #33 路由预言机 `Yl` + `POST /penetration`

- `route-oracle.mjs`：`Yl` 完整移植（`predictRoute`）+ 十八个小件（目标形状与解析
  `pR`/`dR`/`rm`/`a0`/`m0`、域名闸拆解 `dp`/`tp`、三态判定 `i0`/`iR`/`Uu`、集合地址
  `uR`、假设清单 `lR`/`aR`、旁路预匹配 `hR`、Clash 代理链 `c0`、直连主机 CIDR
  `mR`/`gR`、规则归属 `Mu`/`Du`/`Ic`/`Mc`/`Rv`/`Fr`/`np`/`ci`）。`us` 复用
  `createRuleSetEntryCache`，`rt`/`Ta` 复用 `dnsRewriteState`/`macForIp`。
- `handlers/diagnostics.mjs`：`POST /api/openbox/penetration`，**没有 try/catch**——预期
  失败都是 oracle 返回的状态码（400 输入 / 500 组不出配置），其余冒到 app 的错误处理器；
  `network` 不从 body 读。
- **部署管线最后一个洞补上**：`deploy-service` 接 `dnsUpstreamRoutes`，sidecar 现在会
  记录每个代理 DNS 上游实际被哪个 outbound 承载（`split` 部署后 DNS 是否可达就可判定）。
- 实测：起面板（临时数据目录、端口 20261、curl 一律 `--noproxy '*'`），设密码后五条
  `400` 逐字对上；`{"target":"1.1.1.1"}` 在本机答 `500 无法按当前配置生成规则`
  （无核心时 `configDetailed` 必然失败，原版装坏了也是这句）；`200` 无法在本机复现
  ——需要已部署配置 + 跑着的内核。
- 纠正三处：`entryCaches` 用 `WeakMap` 调 `.clear()`（WeakMap 没有 clear，37 条齐红）
  → 改 `Map`；`Mu` 先查「是不是策略 tag」，`fallback` 与 `direct` 同名时
  `nodes`/`ntp`/`other` 三分支不可达，答案是 `{kind:"policy", name:直连}`；
  字面量目标的版本来自地址本身，`ipVersion` 只对域名生效。
- 98 断言，12 个小节。结果：63 套件 4045 断言，119/122，剩 3 个 stub。

### #34 `POST /route-test`（`o0`）与渲染规则文本

- `route-test.mjs`（~750 行）：`o0` + 16 个叶子——CONNECT 探测 `nR`、本地解析器
  `rR`、`/connections` 轮询（`eR` + 六档退避 + settle 后三轮）。
- `rule-text.mjs`（~330 行）：Clash **渲染后**的规则文本——`$v` 解析、`Pv` 配置规则→
  条目表、`Dv` 比较、`Mv` 找回配置规则、`Aa` 归属、`oi`/`ui` 两个守卫的文本孪生。
- **纠正一处早期移植错误（重要）**：`rule-match.mjs` 的 `collapseLogicalRule` 一直自称
  是 `ni`，但原版 `ni` 剥的是 **share 入站守卫** `vf = {invert:true, inbound:["share-*"]}`，
  不是「嵌套 flip 包装器」。后果很安静：带 share 守卫的规则留着 `inbound` 键，`Mu`
  把它读成 `{kind:"builtin", name:"kernel"}`，归属全错；`Pv` 也会把 `inbound` 算进条目表，
  让 `Mv` 永远匹配不上。现在 `stripShareGuard` 是 `ni`，`collapseLogicalRule` =
  `stripShareGuard` + 嵌套拍平，两步都跑。全套 4165 断言未受影响。
- 120 断言，14 个小节，含 8 条对环回 socket 的真探测（200 隧道逐字节、`connectTo`
  只换地址不换 `Host`、403 原样报状态行、`TCP` 不写请求、`GET` 与 `HEAD`、坏状态行、
  超时、入站拒绝 `inbound:` 前缀）。
- **没有对真机跑**：这条路由会真的开一条穿过面板的连接（`penetration` 是只读，
  这条不是）。实测用桩核心（`tools/stub-core`，`OPENBOX_CORE_PATH` 指过去）拿到四条
  真 `200`（例：`exit.error:"inbound: connect ECONNREFUSED 127.0.0.1:7891"` +
  `connectionsError:"fetch failed"`）；`503`（没部署配置）与两条 `400` 逐字对上；
  `GET /route-test` 是 `404`。
- 另纠正四处：短报告与长配置列表长度必须相等（唯一容忍：内核静默截到**三**个）；
  `Mv` 用 `ni` 不用 `Bo`（flip 包装的规则原版就归属不上，复现）；「直连组规则
  `kind:"builtin"`」又踩 `fallback.name` 的坑；Clash 不可达时 `runtimeChain` 是
  单元素链 `["策略A"]`（`z && (runtimeChain = L(z))` 不检查 `L` 找到没有），不是 `undefined`。
- 结果：64 套件 4165 断言，120/122，剩 2 个 stub（两条 terminal-test）。

### #35 `terminal-test`（`IN`，最后两条路由）

- 代码一次齐：`terminal-test.mjs`（`IN`，约 400 行）+ `terminal-probe.mjs` +
  `fetch-timeout.mjs` + `kernel-log.mjs` + `handlers/diagnostics.mjs` 两条路由
  （`GET /terminal-test/capability` + `POST /terminal-test`）+ 测试 158 断言。
- 路由四道闸，按顺序：容器 → `409`（这测试在容器里无意义）；`target` 修剪 + 小写
  后形状校验（小写不是装饰：日志半边按域名大小写不敏感比较，探针把字符串直传给
  子进程）；`port` 用 `Number` 强制（`"443"` 与 `443` 同效，`null` 变 `0` 再由编排器替换）；
  `method` 规范化，未知动词抛 → `400`。串行器在 try **之外**（被拒的测试也要释放队列），
  在路由**之内**（两个请求不能重叠）。
- 备忘录未写 #35（2026-10-26.md 止于 #34 的「下一步」），#35 的存在由代码、
  测试与 wave1 断言三处钉住；README/MEMORY 的散文数字也因此滞后一波（见头条）。
- 结果：65 套件 4681 断言，**122/122，0 stub**。

## 三、屏蔽项（重申，与 v6/v7 相同）

- 两份 reversed JSON 与 v7 **字节相同**（MD5：core `48fe1849e8bcbab1db4373a4edbc0c0d`，
  windows `2cf4a789916194e1afd8ccb85dc47175`），继续屏蔽，不可用；本轮无新增逆向产物。
- `open-box-failover-engine.json` 的 function map 不可用（与 v6/v7 同规则）。
- `src/` 全部为反混淆实现：仅行为对照，不复制。`rea-tools/*.exe` 不使用。
- 与黑盒实测冲突时以实测为准。

## 四、与我们实现的对照（已在代码里核实）

### 已有（v8 不新增工作）

- **v7 缺口 1–3 已于 2026-10-25 全部落地并部署**：服务动词（7374b90）、控制器反代
  触发同步（a8f2fea）、统一部署管线（3c9855b）。v8 的部署面只补了一个我们没有的
  适配器（见下「管线跟进」）。
- **DNS 过滤应用语义**：v8 没有动任何 dns-filter 文件（`dns-filter-artifacts.mjs`、
  `handlers/dns-filter.mjs` 均不在变更清单），v7 缺口 4（`update` 严格 `=== true`、
  `listId` 校验先于 busy、`force = listId || true`、流水线失败 400）原样未动。
- **不要混淆的两组路由**（v7 已注明，v8 后更要分清）：我们的 `/api/client/*`
  （status/nodes/groups/config/mode…）是面板侧客户端管理；v8 的十条
  （`GET /client-config/file` + 九个 `/client/v1/*`）是 token 鉴权的客户端配置包协议。
  我们的 `/api/deploy/state` + `/api/deploy/rollback` 是自有部署状态/回滚，
  不是原版 `POST /deploy` 流水线（我们的等价物是 2026-10-25 新建的
  `/api/openbox/deploy`）。

### 新增缺口（按价值排序，供用户选）

1. **穿透预言机（大，只读，最值得先做）**：我们的穿透测试是其子集（字面规则 +
   geosite/geoip 展开，2026-10-24 落地）。原版 `Yl` 在此之上加：目标形状与解析、
   域名闸拆解、三态判定、集合地址命中、假设清单、旁路预匹配、Clash 代理链、
   直连主机 CIDR、规则归属（含 share 守卫剥离 `ni` 的纠正）。只读不碰流量，
   是诊断台里风险最小的一块；做完它才能接下一项。
2. **部署管线跟进：`dnsUpstreamRoutes`（小，前项的后续）**：我们的新管线
   （`core/deploy.py`，2026-10-25）不记录代理 DNS 上游实际被哪个 outbound 承载。
   原版 v8 经 `Yl` 接上后，sidecar 能判定 `split` 部署后 DNS 是否可达。需前项先落地。
3. **`route-test` 实测（中大，非只读）**：CONNECT 探测 + 本地解析器 + 渲染规则文本
   比对 + Clash `/connections` 轮询，回答「实际走了哪条链」。与穿透预言机互补
   （一个算、一个测），但它会真的开一条穿过面板的连接，上现网要小心，
   且 `GET /route-test` 本来就是 404（只有 POST）。
4. **`terminal-test`（最硬，价值最低）**：建 veth 对、进 network namespace、跑
   conntrack、读 dnsmasq 日志，回答「某台终端实际走了哪条路」。容器里直接 409
   拒绝；我们的 VPS 不是路由器 netns 环境，落地要先搭探针环境，性价比最低。
5. **客户端协议面（大，仍属暂缓线）**：参考实现至此已**全量**（122/122），不再有
   「等对方补齐」的理由；剩下的只是我们的实现工作量。若将来做，v8 新钉住的
   契约点：两套守卫失败语句不同（公开 404 not found / 配对 token 错 404 unpaired /
   开关关 403 disabled）；`?rules=2` 是唯一新方言开关；LAN 网段插最前且只对 IPv4
   抹主机位；`list-` blob 只在被区域引用时发；下载不用 `sendFile`（丢
   `Last-Modified`/`Accept-Ranges`/range）；以及 v7 已注明的 fakeip 双网段、
   `PANEL_PORT` 显式接线、图标字典照抄 `{}`。

### 结构性差异（注明，不急于改）

- 参考实现至此**路由全量**（122/122）。往后若还有新包，增量只会是深度
  （规则集、诊断精度、客户端细节），不再是广度；我们的剩余原版面缺口也因此收敛为：
  诊断三条 + 客户端十条 + DNS 过滤语义（小）。
- `rulesetExtra` 仍是**双方都没接**：参考实现 v8 只剩这一个未接适配器（`Ss` 已落地
  于 `client-regions.mjs`，但接线未做）；我们的部署刷新只覆盖路由引用的集合，
  与此同义，不算新缺口。
- 分析者的测试教训（可直接借鉴，与实现无关）：`WeakMap` 没有 `clear`；`fallback`
  与 `direct` 同名会让 `Mu` 的三分支不可达；字面量目标的版本来自地址本身；
  `net.Server` 没有 `closeAllConnections`；管道汇总会静默丢行，改用逐套件汇总。

## 五、建议的下一步（按价值排序，供用户选）

1. **DNS 过滤应用语义对齐**（小）：收掉 v7 最后一个小项（update/force/listId/400 四处）。
2. **穿透预言机**（大，只读）：诊断台的第一块，也是部署 `dnsUpstreamRoutes` 的前置。
3. **部署 `dnsUpstreamRoutes` 跟进**（小）：前项落地后顺手接上。
4. **`route-test` 实测**（中大）：穿透的「测」半边，上现网需小心（真实开连接）。
5. **`terminal-test`**（最硬）：最后做，探针环境先行。
6. **客户端协议面**（大，暂缓线）：需用户另行拍板是否重启。

以上均为 v8 对照建议，未经用户点头不开工；基线跟进 v0.1.344 之后版本仍按用户决定暂不做。

## 六、诚实保留

- 本机实跑只覆盖 diagnostics-core（87/0 通过）。client-routes、penetration、
  route-test、terminal-test、wave1 五套因沙箱 npm 装依赖（yaml 等）两次受阻
  （一次服务重启清空 /tmp，一次装包缓慢）未跑通；其断言数以 `await check(`
  调用数统计，与备忘录逐项一致（53/98/120/158），wave1 的 122 断言以断言文本为准。
  结论「122/122」另有三处独立证据：`IMPLEMENTED_KEYS` 展开全部四条诊断路由键、
  `test:all` 串起 65 个脚本、wave1「无桩路由」小节改名——不只依赖备忘录一句话。
- 本轮未做黑盒实测对照（原版面板未在 v8 基线上重跑）；与实测冲突时以实测为准，
  上述缺口排序里的工程量估计是推测，动手前会先核代码再报数。
