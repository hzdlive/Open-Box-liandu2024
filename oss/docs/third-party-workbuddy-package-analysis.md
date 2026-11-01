# 第三方包分析（Open-Box-liandu2024_0_9kbp.zip）

- 来源：`workspace/user/files/Open-Box-liandu2024_0_9kbp.zip`（11MB，解压 138MB，571 条目）
- 结论：**与 v7 同一 workbuddy-ai 管道的后续包，覆盖面收口**。v7 为 469 条目 / 122 路由 108 已实现 / 14 stub / 60 套件 3807 断言；本包为 **122/122 路由、0 stub、71–72 套件、4559–4613 断言**（MEMORY.md 记 71 套件 4559 断言，README 记 72 套件 4613 断言，差值恰为新增的 wave5-write-shapes 54 断言，两处自洽）。
- 评级：**A-**（覆盖面收口 + 只读面真机对拍；但作者本轮更明确地承认契约“推导自美化源码”，按我方干净屋边界，可用度仍是“线索 + 黑盒复核”，不能直接当真理用）。
- 版本 skew（三处不一致，引用时必须注明）：冻结契约与解包源码为 **v0.1.330**，真机对拍目标为 **v0.1.337**，我方 oss 对标基线为 **v0.1.341**。作者自己的处理是“差分只比对两版都有的字段；新字段按契约实现”（TRAPS 73，如 `failover/status` 的 `recheckPending` 只在 0.1.337 出现）。

## 一、包的构成（571 条目）

| 部分 | 内容 | 我方处理 |
|---|---|---|
| 顶层 README.md / PRIVACY.md / docs/pic / scripts / docker | 原项目公开材料（README 即 liandu2024/Open-Box 公开 README，含闭源声明；PRIVACY.md 2026-10-10） | 公开材料，可读 |
| `open-box-rea-report.html` / `.zh.html` | 30 节逆向分析报告（v0.1.330），含“面板服务反混淆分析”“面板前端还原（dist 分块级）”“深度二进制分析”“源码级补丁 tcp1–tcp24” | **逆向产物，不作实现依据**，仅作线索 |
| `open-box-core-reversed.json` / `open-box-windows-reversed.json` | 与 v6/v7 **字节相同**（md5 实测：`48fe1849e8bcbab1db4373a4edbc0c0d` / `2cf4a789916194e1afd8ccb85dc47175`） | **继续屏蔽**，无新增逆向内容 |
| `open-box-failover-engine.json`、`-api-paths.txt`、`-components.txt`、`-frontend.json`、`-i18n-additions.txt` | 逆向过程的提取物（函数/路径/组件/i18n 清单） | 仅作线索，不直接用 |
| `rea-tools/`（80 文件）+ `zh/`（batch-1..9.html 等） | 逆向工具链：反汇编（arm64dis/disasm）、字符串/符号提取（gosyms）、NSIS 解包、函数提取；以及黑盒探针（probe-http-surface/traffic/rules、diff-live-store）与契约维护脚本（fix-router-bodylimits、derive-body-limits、sync-openapi） | 工具本身不用；探针类工具的方法论可参考；契约维护脚本的结论见下 |
| `panel-contract/`（23 文件） | 冻结契约：`contract.json`（122 路由，`_meta.corrections` 13 条）、`behavior-spec.md`（页面清单 + 6 大子系统）、`openapi.yaml`（49 条实测路由带真实类型）、`routing-golden.json`（81 例）、`sharelink-golden.json`（43 例）、`response-shapes.json`（63 路由）、`singbox-*.md`、core-rpc/state-schema、desktop-client.md | **主要可用部分，但须按来源分级**（见二） |
| `openbox-panel/`（Node/Express 5.2.1，MIT 自称） | 净室重实现：src/handlers 34 个、src/core 全量、test 73 文件；作者称 122/122 零桩 | **不采纳代码**（栈不同 + 来源不满足我方干净屋定义）；只取行为线索 |
| `.workbuddy-ai/memory/`（13 文件，2026-10-15→10-27） | 另一助手会话的工作记忆：MEMORY.md（全局规则 42 条）、TRAPS.md（793 行，陷阱 28–96+ 号） | 行为线索来源；**其中含用户家里路由器的 live 访问信息，一律不引用、不复述、不落我方记忆** |
| `openbox-panel/.tmp*/stub-core.exe` | 作者自写的桩核心（tools/stub-core/main.go 编出），非原版二进制 | 无原版二进制随包（原版二进制只在作者本机 Temp 目录，不在包内） |

## 二、来源分级（决定每部分怎么用）

作者在 MEMORY.md 中自述的方法论，决定了可用度：

1. **黑盒对拍（最可信）**：只读面真机对拍——63 路由 response-shapes、28 条契约修正全是契约缺陷（移植本来就对）、9/9 值对等（搬真机状态进临时库再起真服务比）、HTTP 表面 21 本地 + 17 真机探针 0 漂移、tutorial-videos 真机逐字节相同。这些结论可直接作为我方黑盒复核的**靶子**（即：拿我方 VPS 黑盒参照去比，看是否一致），而不是直接抄。
2. **静态推导（线索级）**：契约的 `sourceLine`、大量行为“transcribed from index.mjs”（36279 行美化源码）、`parseNodeInput` 的怪异行为“read out of the source”。作者自己写明“契约是推导出来的，会错；改它要留痕”。这类内容**必须经我方黑盒实测复核后才能进实现**，与实测冲突以实测为准（与 v7 规则一致）。
3. **逆向产物（屏蔽）**：两份 reversed JSON（字节同 v6/v7）、rea-report 的反混淆/前端还原/二进制分析章节、rea-tools 的反汇编与符号工具及其中间产物。**不读内容、不指导实现。**
4. **作者自称“净室”的 openbox-panel**：按我方 2026-10-14 确立的边界（禁止反编译/反汇编/逆向恢复），一份从美化源码推导契约再实现的 Node 服务**不满足干净屋定义**，且栈（Express）与我方（Flask）不同。**不采纳、不移植代码**；只在需要时按“线索 → 黑盒复核 → 自研实现”的路径使用其行为描述。

## 三、相对 v7 的增量（v7 剩余 14 桩已清零）

v7 剩余：client-config/file + 9×/client/v1/* + diagnostics 4 个。本包新增套件正好覆盖：

| v7 缺口 | 本包对应套件（断言） |
|---|---|
| 客户端配置包/视图/卡片/信封 | wave5-client-bundle 50、bundle-doc 41、client-view 70、client-panels 67、client-seal 17、client-routes 53、client-config 50、client-app 56 |
| 诊断 4 个 | wave5-diagnostics-core 87、wave5-system-diagnostics 96（支持包：12 命令 + 2 文件并行读；settings 11 字段白名单；密钥先于主机替换；meta.json 与 etc/config.meta.json 不混） |
| 部署管线收口 | deploy-artifacts 83、deploy-flip 90、deploy-hotflip 62、deploy-leaves 60、deploy-rulesets 43、deploy-service 58、native-bypass 59、clash-selection 66、dns-filter-artifacts 61、dns-upstreams 50、selection-sync 30、controller-proxy 39、service-verbs 28 |
| 其他收口 | validate 47、kernel-watch 40、ruleset-stage 27、regex-suffix 57、forward-plan 21、dns-takeover 60、kernel-start 23、preflight 22、deploy-assembly 40、deploy-run 65、response-shapes 18、live-diff 32、openapi-sync 20、boot-sweep 21、http-surface 46、write-shapes 54 |

## 四、对 oss 最有价值的线索（按价值排序，全部待黑盒复核）

1. **客户端面完整映射（我方暂缓线，解冻时用）**：/api/client/* 全量路由、信封（seal）、视图、配置包、4 张卡片、握手。v7 时这条线只有骨架，现在是完整行为描述。注意作者规则 30：`penetration`（预测）与 `route-test`（实测）是两条腿，不能合并；`route-test` 有副作用（真拨号），对真机发之前先问——与我方现有实践一致。
2. **诊断支持包形状**：12 命令 + 2 文件并行读、每条探针把失败渲染成文本（只有组装出错才 500）、settings 白名单 11 字段、密钥替换顺序。对应我方 v7 剩余的 diagnostics 4 桩。
3. **HTTP 表面规则（我方尚未系统对标）**：原版**没有 404 处理器**（未匹配路径落到 Express finalhandler，答 `404 text/html Cannot GET /api/x`）、**不禁用 X-Powered-By**、**不设 trust proxy**（设了等于让调用方伪造 lastSyncFrom）、static 只配 setHeaders、SPA 兜底只排除大小写敏感的字面 `/api/`（`/api/HEALTH`→404 而 `/API/HEALTH`→200 外壳）。我方 Flask 的 404/响应头行为与此不同，如要 1:1 需单独立项核对。
4. **body limit 生效规则（机制级，值得复核）**：声明 ≠ 生效——Express 按注册顺序跑每个前缀匹配的 router，`req._body` 已置位就跳过，**第一个匹配的赢**。服务 router（裸 `/api/openbox`，1mb）注册更早，导致 nodes(10mb)/node-info(16kb)/site-latency(32kb)/dns-filter(128kb)/latency-history(256kb) 的声明全作废、实际 1mb；failover 4kb、license 20kb 的声明是死代码（真机 5031 字节 body 得 404 而非 413、21504 字节 license body 得 400 而非 413）。例外：`POST /backup/import` 实际 32mb（app 级解析器挂在该路径、早于 router 挂载）。我方目前无逐路由 body 限制语义，如要补，先按此机制黑盒验证。
5. **故障转移状态机细节（我方 failover_sm 的候选修正）**：失败那轮不切换（切换在下一轮，10 秒后而非 5 分钟）；切换后必须读回验证（`切换失败:切到 B 后读回的是 A`）；urltest 类页签有“未确认”态（只有内核实际选中的节点通过、或更新的匹配延迟才算 up）；每轮 staleness token 与 1 小时 abort；recheck 轮里 `priority:"critical"` 给的是不紧急的探针（反直觉）；`ro` 返回秒非毫秒；`status()` 里无 `recheckPending`（0.1.330）而 0.1.337 有。注意我方调度器是 60s tick，与作者的 10s/interval 节奏不同，照搬前须先对齐节奏假设。
6. **订阅 UA 阶梯（我方搁置项的完整答案）**：clash-verge / ClashMetaForAndroid / mihomo / clash-verge-rev / sing-box / Open-Box；**429 直接停**；全被拒才走系统 curl；解析成功但 0 节点报“订阅是空的”而非 HTTP 失败。我方现用 `openbox-oss/1.0` 单 UA，改 UA 时应按整条阶梯复核，而非只改最后一项。
7. **分享链接不对称（我方分享面若未实现，可作对照）**：token 即凭证（24 随机字节→48 hex；用户自带 token 须 40–64 hex 且未占用，否则静默替换；regenerate 是唯一吊销；修复下限 32 保旧链接）；创建 201（全 panel 唯一）、删未知 id 404（订阅是幂等 200）、PATCH 非法 protocol 清空为 `""`（POST 回退 https）、`enabled` 不校验类型（`{enabled:"no"}` 等于开启）；校验顺序 name→subscriptions→host→protocol 只报第一个；GET 剪枝只读不写回。
8. **探针与 node-info 精确语义**：三条探针路由都不经运行中内核（写一次性配置 → 起第二个 sing-box → 轮询 /version → 测 → 杀；nodes/latency 先问运行中内核复用 `reused:true` 且故意不写历史；job 按 `tag\0url\0expected` 去重）；node-info 只查订阅节点与 enabled 且 link 恰好解析成一个节点的链式代理；出站生成失败答 400（前缀 `生成不出这个节点的出站:`）；exit 卡缓存 6h、key 含 detour、`refresh` 跳 6h 不跳 15s 防抖。
9. **流量/DNS/内容过滤/规则集/备份的陷阱集（TRAPS 33–72）**：`traffic_daily` 的 day/kind 双约定（hour 写普通日、节点小时桶写 `day@HH`）；`?direct=0` 是减法（逐字段 max(0,…)）；新建直连连接不写任何行；`filterKey` 排除 autoUpdate 且依赖 JSON 键序；Adblock 编译按 (kind, options) 分组；RE2 闸门宽容（放行 lookaround 与反向引用，真机验证 `^a(?=b)` 能建集）；`.mrs` succinct trie 位序（写错不报错、只解出合理垃圾）；备份 `includes` 是删除语义、`?flag` 只有字面 `"0"` 才算关、导入校验顺序 mode→format→version→…只报第一个。以上每条都已在作者侧注明“真机验证”或“差分验证”，我方采纳前仍须黑盒复核。
10. **激活/许可证边界（不在我方范围，仅记录）**：激活只存标签不存码；许可证每次现调核心 Ed25519 验签（包里只有公钥）；16 KiB 上限按字节算、边界精确；四句错误文案全小写无标点。**授权/验签不在我方复刻范围**，此节仅作认知，不进入实现。

## 五、诚实缺口与风险

- **来源天花板**：本包作者自述契约来自美化源码的静态推导 + 真机对拍；推导部分（尤其 validation 顺序、错误文案、解析器怪异行为）未经我方黑盒复核前，一律视为“待验证线索”，不得直接写入 oss 实现或文档当作事实。
- **版本 skew**：契约 0.1.330、真机 0.1.337、我方基线 0.1.341——三版之间路由与字段有已知差异（如 recheckPending），引用具体字段时必须注明版本。
- **包内敏感信息**：`.workbuddy-ai/memory/` 含用户家里路由器的 live 访问信息（地址与凭据）。本分析**不引用、不复述、不落档**；该包的保管与传递请用户自行注意，不要把它当作普通资料转发。
- **未验证项**：本分析未运行包内任何代码与工具（未执行 rea-tools、未启动 openbox-panel、未读取 reversed JSON 内容）；断言数与路由数采信作者自述的套件输出与 contract.json 的结构计数（122 endpoints、`_meta.corrections` 13 条已实测），未逐条重跑其 4613 断言。
- **与 oss 的关系**：本包不改变 oss 的既定方向（面板与后端核心；客户端线继续暂缓）。它提供的是“解冻客户端线 / 补诊断 4 桩 / 核对 HTTP 表面与 body 限制”时的行为参考，不是待办清单。
