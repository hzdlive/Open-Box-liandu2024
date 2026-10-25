# 第三方研究报告 v7 分析（Open-Box-liandu2024-7.zip）

- 来源：`workspace/user/files/Open-Box-liandu2024-7.zip`（469 条目，解压 128MB）
- 结论：**v6 的严格超集，零删除**。新增 13 个文件，25 个同名文件内容变更（md5 实测，
  非时间戳比对）。
- 评级：**A-**（与 v5/v6 持平；部署管线收口 + 客户端配置包本体落地，但 14 个桩仍在，
  且本轮大头属于用户已暂缓的客户端线）
- 路由面：**122 路由 108 已实现 / 14 stub**（v6 为 105/17）；测试全量 **60 套件 / 3807 断言全绿**
  （v6 为 52 套件 / 3437 断言，新增 8 套件 / 370 断言）
- 包版本仍 0.1.0（package.json diff 只有测试脚本），未提新 release 版本号，基线仍按 v0.1.344

## 一、变更清单

### 新增 13 个文件

| 类别 | 文件 |
|---|---|
| 分析者备忘录 | `.workbuddy-ai/memory/2026-10-25.md`（Wave 5 #22–#30） |
| Clash 控制器反代 | `src/core/clash-proxy.mjs` + `test/panel-wave5-controller-proxy.mjs`（39 断言） |
| 客户端配置包 | `src/core/client-bundle.mjs` + `test/panel-wave5-client-bundle.mjs`（50 断言）+ `test/panel-wave5-client-bundle-doc.mjs`（41 断言，wS 本体） |
| 客户端视图层 | `src/core/client-view.mjs` + `test/panel-wave5-client-view.mjs`（70 断言） |
| 客户端四张卡片 | `src/core/client-panels.mjs` + `test/panel-wave5-client-panels.mjs`（67 断言） |
| 客户端信封 | `test/panel-wave5-client-seal.mjs`（17 断言；实现补进既有 `client-config.mjs`） |
| 域名过滤应用 | `test/panel-wave5-dns-filter-apply.mjs`（39 断言；实现补进既有 `dns-filter-artifacts.mjs`） |
| 服务五动词 | `test/panel-wave5-service-verbs.mjs`（28 断言；实现补进既有 `deploy-run.mjs` + handlers） |

### 内容变更的 25 个文件（要点）

- `.workbuddy-ai/memory/MEMORY.md`（60 套件 / 3807 断言）、`TRAPS.md`（新增至 444+ 条）、
  `openbox-panel/README.md`（108/14、deploy 与 service-verbs 章节）
- `src/handlers/deploy.mjs`（`DEPLOY_KEYS` 三键 + `POST /deploy`）、`src/handlers/index.mjs`
  （工厂补 `ops`）、`src/index.mjs`（`deployLog`/`rulesetLog`）、`src/app.mjs`（控制器反代挂载）
- `src/core/deploy-service.mjs`（58 断言，表 12 键改 13 键）、`deploy-hotflip.mjs`（62 断言）、
  `deploy-run.mjs`（`deployFailureText`）、`dns-filter-artifacts.mjs`（`pruneDnsFilterArtifacts`）、
  `kernel-start.mjs`（`kernelVersionString`）、`system.mjs`（`readFileBinary` + `readdir`）、
  `client-config.mjs`（`sealConfig`）、`handlers/dns-filter.mjs`、`handlers/service.mjs`、`paths.mjs`
- 测试计数联动：wave1/wave2 的 `cov.implemented` 105→106→107→108、wave4-deploy 的
  `DEPLOY_KEYS` 断言、wave4-dnsfilter 的 `DNS_FILTER_KEYS` 精确数组、wave4-service 的
  `SERVICE_KEYS` 精确数组（分析者第六次踩硬编码计数，见四.4）

## 二、Wave 5 #22–#30 摘要

### #22 POST /deploy 落地（部署管线收口）

- 路由本身很薄：`res.status(service.status(result)).json(result)`，状态**不**由 `ok` 决定：
  conflict/validate/cancelled → 409（请求没问题，是世界不配合）、rulesets 缺依赖 → 503、
  start/verify/error 三阶段 → 500、未知 stage 也是 500（对失败答 200 是客户端无法恢复的）。
- 服务**一进程只装一次**（`createDeployHandlers` 里装）：原版 `ln` 挂模块级队列 + 模块级
  generation 计数，每请求新建 service 会导致两个并发部署各有一条队列、stop 只取消一条。
  第 11 节用「run 卡在 gate 上，order 只有一个 start」钉住单队列。
- 失败模型三路由三套，**不要统一**：`POST /deploy` 不 catch（锁被占是 reject，express 5 转
  `/api` 错误处理器渲染 `500 {error}`，原版一模一样）；`GET /deploy/state` 纯 store 读，永不失败；
  `POST /rollback` 有 try/catch，答 `500 {ok:false,message}`，步骤失败仍 200 放进 `failures`。
- 仍有两处可选 deps 不传：`dnsUpstreamRoutes`（等诊断引擎 `Yl`）、`rulesetExtra`（等 `Ss`/`kr`），
  `runDeploy` 有 `deps.x &&` 守卫，缺它们是「小一点的部署」不是坏部署。

### #23 Clash 控制器反代 + 选择同步接线 + 部署后热翻转对账

- `bD`（`clash-proxy.mjs`）：面板把控制器写请求原样转给内核；`PUT|DELETE` 且路径含 `/proxies/`
  就是「用户换了选择」，是 `hD` 选择同步的**唯一触发点**（此前 `hD` 写好了但零调用方）。
- 三个易错点：尾巴是 `originalUrl.slice(15)`（`"/api/controller".length === 15`），路由用**正则**
  挂载（前缀挂载会把 `req.url` 切成尾巴，再 slice 就少三段）；调用方给的
  `x-zashboard-target-base` 是**替换**密钥（`x-zashboard-target-secret || ""`），不是叠加；
  只有 `/delay` 请求挂 60s 上限、超时答 `504`，其余失败答 `502`；客户端挂断时 `res.on("close")`
  里 `controller.abort()`，`finally` 里摘监听（keep-alive 上会累积）。
- 装配：密码闸门**之后**、路由**之前**挂，`express.raw({type:"*/*", limit:"25mb"})`（body 不是
  面板能替它解释的东西，原样转发 Buffer；测试断言 PUT 转 Buffer、GET 不带 body），
  `onProxied: () => selectionSync.schedule()`。
- `deps.hotFlipReconcile` 必须**直接调 `runHotFlip`**：`syncSelections` 第一句是
  `deps.exclusive → lock.run`，而 `runDeploy` 已在 `lease.run` 里面，走那条路等于自锁，
  卡到 90s 锁等待超时。`buildDeployDeps` 因此多吃一个 `lock` 并自建 `hotFlipDeps` 复用。
- 无内核证明法：`runHotFlip` 读不到 sidecar 立刻返回 `{ok:false, reason: NO_SIDECAR}`，
  一次写都不发；三条断言（只读 `config.meta.json`、锁探针 `runs.length === 0`、
  只有 `warn` 的 logger 也不炸）就够了。

### #24 POST /dns-filter/apply 落地 + 清理（`Pl`）

- 路由两条路径：`{update:true}` → `Gi(force)` → `Pl()` → `tick()` → 答固定
  `{ok:true, stage:"updated", message:""}`；其它任何 body → `ln()`（整条部署）→ `Pl()` →
  `tick()` → 答流水线自己的 result。
- `update` 必须严格 `=== true`（`{update:"true"}` 走部署路径，慢但不会错）；`force` 是
  `listId || true`（给 id 只强制那一条，不给就全量）；`listId` 校验在 busy 检查**之前**
  （否则拼写错误会被报成「稍后重试」，而重试还是错）。
- 失败处理各不相同，别统一：流水线失败是 **400**（带 `message`）不是 500；prune 失败被吞，
  但 `tick` 失败会传播成 400（原版把 `await s.tick()` 放在 try 里）；`tick` 默认取
  `observer.tick`，没有就跳过（采集器 `kf` 还没移植）。
- `pruneDnsFilterArtifacts` 引用集合是**三个来源的并集**，只按其一清理会把内核正在用的
  `.srs` 删掉：① profile 里还在的名单的 `path`（写回时顺手剔掉已删除名单）；② 已应用
  runtime 的 `sets[].path`；③ `config.json` 的 `route.rule_set[].path`。两个提前 return
  都是「拒绝猜」：`config.json` 读不到就在列目录**之前**返回（引用不完整时删文件不安全），
  目录不存在就是「从没编译过」；只删 `^[A-Za-z0-9_-]+\.(txt|json|srs)$`，运维手放的文件必须活过清理。
- 配套：`system.mjs` 补 `readdir`（必须是「目录不存在就 reject」的语义，`Pl` 拿这个
  reject 当「没东西可清理」）。

### #25 POST /service/core/:action（服务五动词）

- 五个动词只有三条路径：`start` **=** `restart` → `ln`（整条部署；原版没有「只启动」，
  没有新配置的内核会带着上次写的东西起来，而面板会报告一台它没配置过的机器）；
  `stop` → `stopKernel`（停 → 等真的退出 → 清开机自启，第三步失败**不清 `ok`**，只往
  `stderr` 追加 `disable autostart failed: …`）；`enable`/`disable` 只碰 initd，不跑流水线、
  不带 warning、不计时。
- 三个「看着像 bug，其实是原版」的点：`durationMs` 算了但**从不返回**（测试用假时钟数到
  2 次读取证明「计了」，再用 `"durationMs" in body === false` 证明「没发」）；非法动词的
  400 用 `message` 不用 `error`（全面板就这一条）；`yN`（`deployFailureText`）没有空值守卫，
  传 `{}` 得到字面量 `deploy failed at stage: undefined`（那是用户日志面板一直显示的东西，别「修」）。
- 该路由**永远不答 500**：部署失败、stop 失败、甚至没装配 `deploy`/`stop`，都是
  `200 {ok:false, code:1, stderr}`，只有非法动词是 400。

### #26 客户端信封（`Dd` / `sealConfig`）+ 一次白写

- 新建 `client-device.mjs` 写了 300 行、43 条断言全绿后发现 `client-config.mjs`（wave 4）
  里已经有前十个函数，只缺 `sealConfig`：删掉重写本，测试改写为 `client-seal`（17 条，
  只测信封 + 「配对记录的 key 能解开它自己的信封」）。教训成全局规则 28：**写任何新
  `core/*.mjs` 之前先 grep**。
- 过程中纠正的错误认知：存储里**有 `token` 明文**（`writeDevices` 写完整对象），所以
  `hasValidToken` 在正常数据上恒为真，`ensureDevice` 是**幂等**的（列表只有一条且自证成立 →
  原样返回，一个字节都不写）；只有列表为空或多于一条时才铸造，多条时**复用 `newest`**
  （`randomBytes` 在分支之前就取了，复用时会丢弃）。测试先红（`a second call mints a new
  token` 失败）才暴露模型错误。
- 信封形状 `{v:1, iv, data}`，三种编码在四个字段里：`key` 是设备记录的 **base64url**
  字符串；`iv` 是 **base64**，12 字节，每次新取；`data` 是 **base64**，内容是
  `密文 || GCM tag`，**tag 追加在末尾**，不是第四个字段。消费方要 `slice(0, -16)` 再解密。

### #27 客户端视图层（`iP` 与四个辅助）

- 动手前 grep 省下一半：`dt`（URL → `list-xxxxxxxx`）=`rulesets.mjs` 的 `listTag`、
  `Rn`=`ruleset-materialize.mjs` 的 `isOwnListTag`、`Jt`=`geo.mjs` 的 `isSafeRuleSetName`、
  `He`=`rulesets.mjs` 的 `ipTag`、`Be`（链式代理 → 伪节点）=`conflict.mjs` 的
  `chainTagsFromProxies`；真正只写了 `iP` + `_l`/`Vl`/`Jl`/`Ao` + `Bs`/`g$`
 （`client-view.mjs` 约 380 行含注释）。
- **图标字典在真实部署里是空的**：`g$()` 解压 `panel/server/resources/icons.json.gz`，
  全树一个 `.gz` 都没有（`resources/` 下只有 `geodata/` 和 `licenses/`），所以恒走 catch
  返回 `{}` → 客户端拿到的每个 `iconSvg` 都是 `""`。这是**必须照抄的降级**，不是 bug；
  给重实现造一张图标表等于给客户端发送原版从不发送的数据。`readIconTable` 把六种失败
  （缺文件 / 读不了 / gzip 坏 / JSON 坏 / 不是对象 / `null`）统统收成 `{}`。
- `Bs` 两套规范化：命中 `/^(globe|misc|brand):(.+)$/i` 才保留命名空间并小写，其余**整串大写**
  （`flag:hk` → `FLAG:HK`，`flag:` 不是命名空间，测试专门钉住）。
- 三个易写歪的形状：回落策略的 `drill` 是 `{fallback:true}`，没有 `custom`/`rulesets`
  （客户端做 `drill.rulesets.length` 会抛）；`drill.rulesets` 把 `_l` 的
  `{tag, source, url, parts}` 重映射成 `{tag, source, parts}`，`url` 被丢掉，只在 `source`
  里以「找到用 URL、没找到用 tag」残留；去重只在 `displayOrder` 内部，重复**保留**，
  同名时回落图标赢（Map 回落最后插入）。

### #28 客户端配置包（`hh` / `pi` / `mh`）

- `hh` 名义依赖十个函数，逐个查完只有 `pi`、`mh` 没移植：`client-bundle.mjs` 只有三个导出
  （`injectUpstreamRoutes`、`clientFlaggedConfig`、`clientBundleConfig`）。复用 `configState`
  的办法是造六方法假 store（`getClashSecret: () => ""` 正好对上 `clashSecret: ""`，
  `getRaw: () => null` 让 `readFilterRuntime` 返回 `null`，正好对上 `dnsFilter` 默认值）。
- 三个必须照抄的怪处：**路径全是相对的**（`geoDir: "rulesets"`、`rulesetDir: "rulesets"`、
  `cacheFilePath: "cache.db"`，手机把包解到自己目录里按自身解析）；**两个 fakeip 网段**
  （客户端 `198.18.0.0/16`，部署 `198.19.0.0/16`，相邻两个 /16，另有 `198.18.0.0/15`
  把两者一起校验，**别合并**）；`obflip-byp-` / `obflip-need-` 在客户端配置里要**抛错**
  （那是 nft 入口模式用的集合，漏过来说明上游已经错了，抛在 `flip/<tag>.json` 分支之前）。
- 夹具教训：flag 的 `selector` 完全依赖核心发出的 rule_set 标签与 `policyTag`（`obflip-` +
  sha256(id) 前 12 位）一致，这个不变量现在有断言。

### #29 客户端四张卡片（`Ad`/`Eo`/`Us`/`Xa`/`Za`/`ph`）

- `wS` 的 `view` 是 `iP` 的五个集合 **加上** 四张独立卡片：`ph` → `clientProfilePatch`
  （放 `client-bundle.mjs`，它是 bundle 的补丁）、`Xa` → `testSiteCards`（按位置合并
  `defaults/test-sites.json`）、`Za` → `testSettings`（三个数在 settings store，不在
  profile）、`ob` → `serverInfoCard`（纯投影）、`Ad` → `serverCard`（`ob` +
  `readEgressCountry` + `Ao`/`Bs`）、`Eo` → `dashboardBackground`（本地图 / URL 两态）、
  `Us` → `backgroundView`（`withData` 只对本地图有效）、`it` → `clientPanelPort`（只复现原版规则）。
- 三个「名字骗人」的地方：`yo` 不是「是不是 SVG」，是 `typeof === "string"`
  （服务卡片的 `iconSvg` 回退：只要存的是字符串就原样回传，`<svg` 前缀只在写入时校验）；
  `T$` 是日期不是时间戳（URL 背景追加 `?v=YYYY-MM-DD`，换图最多一天后才生效；`version`
  字段是另一套，sha256 前 16 位）；`Rw` 的下限恒为 0，只有上限和默认值按设置不同
  （透明度 `(90,100)`、模糊 `(10,39)`），非数值走默认值。
- region 不对称：`ho(serverInfo.region) || ho(detectedRegion).toUpperCase()` —— **只有自动探测
  的那个被大写**，通过 API 存进去的必然大写（校验器 `/^([A-Z]{2})?$/`），差异只在手改库时可见。
- 端口：原版只有一个变量（`it()` 读 `process.env.PORT`，监听与上报天然一致）；我们监听
  `OPENBOX_PANEL_PORT`，所以 `clientPanelPort()` 只复现原版规则（`PORT` 优先、1..65535、
  否则 2026），**接线时必须显式把 `PANEL_PORT` 传进 `wS`**，否则 3036 的部署会对外报 2026。

### #30 配置包本体（`wS`）

- 十步，四个决定：**活的 Clash 选择 > store 快照 > `{}`**（内核没起时 `readClashSelection`
  返回 `{}`，于是用 `getSelectionsSnapshot()`，包里仍是用户最后选的那个）；**配置用打过补丁
  的 profile，视图用原始 profile**（`d = {...a, ...ph(a)}` 给核心，`iP({profile: a})` 给原始，
  顺手统一就会出事）；`upstreamRoutes` 只在 `dns.split` 为真时算，关掉就是 `[]`；
  **指纹在贴背景图字节之前算**（`withData` 包与普通包指纹相同，客户端靠这个判断「配置没变，
  只是换了图」）。
- 顺手补的基础设施：`system.mjs` 加 `readFileBinary`（编译好的 `.srs` 是二进制，按 UTF-8 读会
  让 `length` 和 `sha256` 都错）；`kernel-start.mjs` 加 `kernelVersionString`（`Ba`，只取版本号
  `"1.11.0"`，不是 `kernel/version` 那个 `{version, raw, ok}`）。
- 生成配置包会写库：`routerId(store)` 在缺失时**铸造并持久化** 16 字节 id（和
  `GET /client-config` 同一种「读操作带写副作用」），第二次生成必须拿到同一个 id。
- 硬错误 vs 跳过：引用了但不在盘的规则集，`wS` 选择**抛错**（`规则集 <tag> 还没准备好,
  先在路由器上启动一次内核再试`）而不是跳过（跳过会产出「装得上但加载失败且无解释」的包）；
  `withData` 只内联用户集合，永不内联 geo 集合（`geoip-cn.srs` 一个就比包里其余部分都大）。

## 三、屏蔽项（重申，与 v6 相同）

- 两份 reversed JSON 与 v6 **字节相同**（MD5：core `48fe1849e8bcbab1db4373a4edbc0c0d`，
  windows `2cf4a789916194e1afd8ccb85dc47175`），继续屏蔽，不可用；本轮无新增逆向产物。
- `src/` 全部为反混淆实现：仅行为对照，不复制。`rea-tools/*.exe` 不使用。
- 与黑盒实测冲突时以实测为准。

## 四、与我们实现的对照（已在代码里核实）

### 已有（v7 不新增工作）

- **选择同步机制**：我们 2026-10-23 已落地（`selectionsync.py` + 600ms 尾随防抖 +
  `POST /api/openbox/selection-sync`，apply/hotapply 前自动对账）。v7 #23 的增量只是**触发面**：
  原版经控制器反代捕获一切写请求，我们的同步目前只挂在面板原生切换路径上（见缺口 3）。
- **DNS 过滤应用**：我们 2026-10-25 已落地 `POST /api/dns/filter/apply`（编译 + 安装 +
  自动同步重启）。v7 #24 的 `update`/`force`/`listId` 语义可对照（见缺口 4）；`Pl` 的 prune
  对我们目前不适用——我们不产 `.srs`，只有一个扁平拦截文件，无陈旧产物可清。
- **服务启停**：我们已有 `GET /api/service`、`POST /api/service/start|stop|restart`（含
  startverify）。缺的是 `enable`/`disable` 动词与 #25 的动词语义（见缺口 2）。
- **不要混淆的两组路由**：我们的 `/api/client/*`（status/nodes/groups/config/mode/…）是
  面板侧客户端管理；v7 的 `GET /client-config/file` + 九个 `/client/v1/*` 是 token 鉴权的
  客户端配置包协议（`wS` + `Dd` 封印），我们**没有**实现后者。我们的
  `/api/deploy/state` + `/api/deploy/rollback` 是自有部署状态/回滚，也不是原版
  `POST /deploy` 流水线。

### 缺口（按价值排序，供用户选）

1. **统一部署管线 POST /deploy（结构性，推荐度最高但工程量最大）**：原版已收口
   （只剩 `dnsUpstreamRoutes`/`rulesetExtra` 两个可选 deps），我们仍是 apply + start 两步，
   pieces 都有（check 门、冲突门、verify、bad_node 定位）但没有统一管线、状态机、单队列
   与 #22 的状态码表（409/503/500）。这是 v6 就已注明的结构性差异，现在对方已收口。
2. **服务动词补齐 + 语义对齐（小）**：补 `enable`/`disable`（只碰 initd，不跑流水线）；
   对齐 #25：`start` = `restart` = 整条部署（我们目前 start/restart 是拉起内核，不跑全量
   apply——语义差）；`stop` 第三步失败不清 `ok` 只追加 stderr；非法动词 400 用 `message`；
   `durationMs` 不返回；部署失败永远不答 500（`200 {ok:false, code:1, stderr}`）。
3. **控制器反代触发选择同步（中小）**：我们已有同步机制，只差触发面——原版经
   `/api/controller/*` 反代捕获一切 `PUT|DELETE …/proxies/` 写请求；我们目前只覆盖面板
   原生切换路径，直连 Clash API（curl、第三方客户端）的切换仍会旁路 DB，下次 apply 复位。
   注意：接这条线等于面板要代理 Clash API（原样转发 Buffer、25mb 上限、`/delay` 60s 504），
   不是只加一个钩子。
4. **DNS 过滤应用语义对齐（小）**：`update` 严格 `=== true` 才走纯刷新路径；
   `listId` 校验在 busy 检查之前；`force` = `listId || true`；流水线失败 400 而非 500。
   `Pl` prune 暂不适用（见上）。
5. **客户端协议面（大，属暂缓线）**：`wS` 配置包 + `Dd` 封印 + `iP` 视图 + 十个路由
   （`GET /client-config/file` + 九个 `/client/v1/*`），约占本轮新增断言的三分之二。
   用户 2026-10-19 已明确客户端先不管，主攻面板与路由器核心；是否重启该线需另行拍板。
   若将来做，注意三点：客户端 fakeip 用 `198.18.0.0/16`（部署用 `198.19.0.0/16`，别合并）；
   面板端口接线须显式传 `PANEL_PORT`（原版读 `PORT`，我们读 `OPENBOX_PANEL_PORT`）；
   图标字典在真实部署里是空的，照抄 `{}` 降级，不要自造图标表。

### 结构性差异（注明，不急于改）

- 诊断引擎 `Yl`/`fo` 仍是双方都没有的：原版剩 4 个 diagnostics 桩（penetration、
  `route-test`、两条 terminal-test）全卡在它上面；`deps.dnsUpstreamRoutes` 也等它。
  我们的穿透测试是其子集（字面规则 + geosite/geoip 展开），原版完整诊断台仍未复刻。
- 分析者的测试教训（可直接借鉴，与实现无关）：写「什么都不该发生」的断言前，先确认
  那条路径真的会走到「该发生什么」的分支（prune 空转教训）；加一条路由 = 四处数字
  （`cov.implemented` ×2 + README ×3 + 各 `*_KEYS` 精确数组），开工前先 grep；写新模块前
  先 grep（`client-device.mjs` 白写 300 行）；测试红了先怀疑模型不是断言（token 明文事件）。

## 五、建议的下一步（按价值排序，供用户选）

1. **服务动词补齐 + 语义对齐**（小，先做）：enable/disable + #25 的失败模型，收口服务面。
2. **控制器反代触发选择同步**（中小）：堵住「非面板切换旁路 DB」的口子。
3. **统一部署管线 POST /deploy**（大）：按 #22 形状收敛 apply + start + 状态机，需单独拍板。
4. DNS 过滤应用语义对齐（小）：update/force/listId/400 四处。
5. 客户端协议面（大，暂缓线）：需用户另行拍板是否重启。

以上均为 v7 对照建议，未经用户点头不开工；基线跟进 v0.1.344 之后版本仍按用户决定暂不做。
