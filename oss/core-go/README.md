# oss-core（Go 配置核心）

三层结构里的中间层：面板与 sing-box 内核之间的配置编译器。
契约见 [CONTRACT.md](CONTRACT.md)。

## 构建

```sh
# 本机（amd64）
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o oss-core .

# 交叉编译（路由器目标）
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o oss-core-linux-amd64 .
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o oss-core-linux-arm64 .
```

Go 版本与内核构建对齐（当前 1.25.5；开发机工具链在 `~/go-dist`）。

## 当前状态

脚手架：`version` 可用，`config` / `configDetailed` / `emitGroups` 为
占位（退出码 4，`not implemented yet`）。移植按 Python 生成器
（`oss/core/singbox.py` 的 `build_config` 链路）逐片进行，每片用对照
工具与 Python 版做字节级对照：

- ✅ 片 1（出站）：`node_to_outbound` / `chain_to_outbound` /
  `build_outbounds` / `build_endpoints`（全部协议、TLS 原生/旧式/
  未知指纹、anytls 时长、故障转移 lane、loadbalance→selector、订阅组、
  flip 选择器、fallback 卡）。对照：`harness/compare_outbounds.py`
  + `harness/fixtures/profile1.json`，38 出站 + 1 endpoint，语义与
  键顺序均一致。
- ✅ 片 2（路由规则）：`build_route_rules`（入口旁路、终端策略 + IPv6
  补充、前置 8 类规则、订阅直连、站点集 + 每集 QUIC 拦截、内容过滤
  DNS 层与路由层回退、溯源记录、四组副作用集合）。对照：
  `harness/compare_route_rules.py` + `harness/fixtures/profile2.json`，
  DNS 层 28 路由 + 18 DNS 规则、回退 29 + 15 条，溯源与副作用均一致。
  ARP/DNS 解析由面板预先算好放进 profile（core 不读现网状态）。
- ✅ 片 3（DNS 与组装）：`build_config`（入站 tun/panel-in/dns-in/
  lan-share/share、DNS 服务器与延迟排序、WAN 上游、split 改写、
  region outside、规则集声明、obnode sentinel、clash_api）。对照：
  `harness/compare_config.py`，base / WAN+split 关 / region outside
  三组全量配置均一致（20 出站、31 路由规则、18 DNS 规则）。
- ✅ 片 4（规则集文件与两个方法）：`dnsfilter`（分片写入、幂等、allow
  sentinel；`config` 命令先写文件再生成，写失败回退路由层拦截）、
  `emitGroups`（builtin + 组派生出站）与 `configDetailed`（config +
  directHosts + dnsRuleOwners + failover）。对照：
  `harness/compare_dnsfilter.py`（6 万域名 3 分片 + 空名单 + 单分片，
  字节一致且幂等）、`compare_emitgroups.py`（16 组出站一致）、
  `compare_configdetailed.py`（config + directHosts + 17 DNS 溯源 +
  1 故障转移组一致）。Python 生成器同步加了可选 `dns_provenance`
  参数（默认 None，输出不变）；全套测试 477 过、3 个已知基线失败。
- ✅ 真库对照（2026-11-08，VPS 上实跑）：`harness/live_compare.py`
  对 live panel.db（116 节点、9 链、8 组、12 站点集、19 前置规则、
  90,757 拦截域名）全量配置一致（159 出站、46 路由规则、34 DNS
  规则），5 个 dns-filter 文件字节相同，`sing-box check` 在 Go
  输出上通过。移植收束。

`debug-outbounds` 是开发用命令（只出 outbounds + endpoints，供对照
工具用），`config` 完整实现后保留或移除。


## 分发

- 构建：`.github/workflows/core.yml`（Go 1.25，`go.mod` 定版），
  linux amd64 + arm64 静态二进制，产物为 workflow artifact
  `oss-core-linux-amd64` / `oss-core-linux-arm64`（裸二进制，非
  tar 包）。amd64 构建后跑全部 6 个 harness 对照当冒烟测试。
- 路由器安装：`oss/scripts/install.sh --kernel-url <内核直链>
  --core-url <core 直链>`（Debian + OpenWrt，amd64/arm64；两个
  URL 都必填，无默认上游）。脚本装内核 + core（`$PREFIX/bin/`，
  并链到 `/usr/local/bin`）+ 面板文件（`core/`、`panel/`、
  `dashboard/zashboard-src/dist/`、requirements.txt）+ 服务
  （Debian 用 systemd，OpenWrt 用 procd），面板经
  `OBX_CORE_BIN=$PREFIX/bin/oss-core` 找到 core。
- 手动装一个：`install -m 0755 oss-core /usr/local/bin/oss-core`，
  或 `OBX_CORE_BIN=/path/to/oss-core` 指定。
