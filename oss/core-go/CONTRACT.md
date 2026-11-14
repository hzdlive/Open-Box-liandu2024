# oss-core：独立配置核心（Go 静态二进制）

三层结构里的中间层：面板（Flask）与内核（sing-box）之间的配置编译器。
对标原版 `openbox-core` 的方法形态，但只复刻公开可观察行为（干净屋；
授权/验签不在范围；`routingFingerprint` 明确不实现，绝不返回猜测值）。

## 形态

- 单个静态二进制（`CGO_ENABLED=0`，`go build -trimpath -ldflags="-s -w"`），
  按架构分发：`linux/amd64`、`linux/arm64`。无运行时依赖、无网络访问。
- 纯函数：输入 = profile JSON + workdir，输出 = sing-box 配置 JSON。
  不读数据库（库是面板的，面板把 `AppConfig` 序列化成 profile 传进来），
  不碰面板状态。

## 命令

### `oss-core version`

握手。stdout 一行 JSON：

```json
{"name": "oss-core", "version": "0.1.0", "singbox": "1.14.4",
 "methods": ["emitGroups", "configDetailed", "config"]}
```

面板首次使用前调一次，主版本必须一致才允许部署；版本记入部署状态。
`routingFingerprint` 不在 methods 里——它明确不实现。

`singbox` 是配置面向的内核版本。1.14.4：loadbalance 出站需要
魔改内核 1.14.4-openbox-38+（1.14.1-openbox tcp28 与原版 1.14.x
都拒绝 `type: loadbalance`）。

### `oss-core config --profile <file> --workdir <dir> [--skip-rule-sets a,b]`

生成完整 sing-box 配置（等价于 Python `core.singbox.build_config`）。
stdout 只出一个 JSON 文档（配置本身）；诊断信息走 stderr。
同时把内容过滤的规则集文件写到 `<workdir>/dns-filter/`（分片、幂等，
内容不变不重写），配置里的 `rule_set` 声明引用这些路径——与 Python
`apply.py` 今天的行为一致。

### `oss-core configDetailed --profile <file> --workdir <dir>`

与原版同名方法。stdout：

```json
{"config": {...}, "directHosts": {"cidrs": [...], "domains": [...]},
 "dnsRuleOwners": [...], "failover": [...]}
```

`config` 与 `config` 子命令的输出相同（预览语义：不写规则集文件，
用 profile 自带的 `dns_filter_rulesets`）；其余三项是溯源信息：

- `directHosts`：obnode 直连集（订阅域名 + 节点服务器解析出的
  IP），键序 `cidrs`、`domains`（与原版一致）。仅当 `sub_node_direct`
  开启时有内容，否则为空——与 Python 生成器一致。
- `dnsRuleOwners`：每条 DNS 规则一条 `{kind, name, ...}` 记录，与
  `config.dns.rules` 一一对应（front / obnode / siteset / content）。
  形状是我方溯源格式，**不是**原版的 `{from, index, kind, name, to}`。
- `failover`：已启用的故障转移组 `[{name, lanes: [{name, members,
  mode}]}]`，lane 名为显示名（主用/备用 N 或自定义名），成员为已解析
  的节点/链 tag。原版的 lane 随机 id（`lane-…`）不可复现，不做。

### `oss-core emitGroups --profile <file>`

归一化后的组。stdout：

```json
{"builtin": {"direct": "直连", "directEnabled": true,
             "block": "拒绝", "blockEnabled": true},
 "groups": [...]}
```

`groups` 是组派生的出站（订阅组、用户组、内置、热切换选择器、“其他”），
与 `config` 的 `outbounds` 里节点/链之后的部分相同。原版 `emitGroups`
的 lane id 与 `dropped` 等字段不做（见上）。

### 组类型：loadbalance

`loadbalance` 组发内核原生出站（v0.1.384+，不是 selector）：

```json
{"type": "loadbalance", "tag": "<组名>", "outbounds": ["<节点1>", "<节点2>"],
 "interval": "120s", "url": "http://www.gstatic.com/generate_204"}
```

- 分流算法是**轮询**：2026-11-14 在 lab 内核 1.14.4-openbox-38 上
  实测，2 个真实节点、12 个连接严格 A,B 交替（各 6 次），不是随机、
  不是按延迟。成员按 `interval` 做 generate_204 健康检查，不健康的
  成员会被排除。
- `interval` 取组的 `interval_s`（面板默认 120s，未设时 120s），
  `url` 取组的 `test_url`、未设时取 profile 的 `speedtest_url`。
- 成员必须是**真实代理节点**：内核在启动时拒绝 direct/block/组/链
  成员（`load balance requires real proxy nodes`），且 `sing-box
  check` 不拦（check 能过、run 即 FATAL，整个内核起不来）。所以
  core 只把解析出的节点 tag 放进 `outbounds`；面板保存时也要校验
  成员是真实节点（见面板层），空成员的 loadbalance 组不允许保存。
- schema 只有 `{type, tag, outbounds, interval, url}` 这五个字段：
  内核拒绝 `pick` / `strategy` 等字段（`json: unknown field`），
  别拿其他 fork 的 pick/objective/strategy 文档当原版行为。

### 未实现的方法

`routingFingerprint` 及授权/验签类方法：退出码 4，stderr 说明
`not implemented yet`。绝不返回猜测值。

## 退出码

- `0`：成功，stdout 为单个 JSON 文档。
- `2`：输入错误（profile 解析失败、参数缺失）。
- `3`：生成错误（内部错误，附带 stderr 说明）。
- `4`：方法未实现。

## 对照标准

与 Python 生成器逐字段对照（`harness/compare_*.py`，语义 + 键序）：
出站、路由、完整配置、dnsfilter 文件、`emitGroups`、`configDetailed`
六组对照全部通过。金语料 `core-golden-225.json` 是原版 state 格式，
不能直接喂 Go core（Go core 吃我方 profile）；金语料的价值在 Python
复刻层（`emitGroups` 121/121、`configDetailed` 归一化后仅剩 obflip
摘要与 directHosts.cidrs 两处已知缺口），Go 层对照以 Python 生成器
为准。真库配置对照（部署前在目标机上跑 `sing-box check` 校验）待做。

已知缺口（与 Python 生成器一致，不在 Go 版里偷偷“修掉”）：
- obflip 摘要用 md5 占位（原版算法未拟合）；
- `directHosts.cidrs` 多 50 条；
- 规则集文件格式为 JSON source（原版为 binary），语义等价。
