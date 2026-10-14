# OpenBox-OSS

OpenWrt 一体化透明代理方案的**开源重构**（clean-room reimplementation）。

> 目标：复刻上游 Open-Box **闭源部分**（路由器端程序 + 客户端 App）的公开行为，
> 代码完全独立重写。本分支不包含任何 Open-Box 闭源二进制与混淆产物，
> 不做反编译 / 反汇编 / 逆向；授权/验签类机制不在复刻范围内。
> 详细边界见 [BOUNDARY.md](BOUNDARY.md)。项目名称为暂定，正式发布前确认。

## 功能目标（对标公开文档描述的行为）

- 一条命令完成 sing-box 内核 + 管理面板的安装（OpenWrt / Debian / Docker）
- 浏览器面板完成订阅、节点、站点集分流、DNS、防火墙配置，无需手写配置文件
- 订阅解析：Clash YAML、base64 分享链接、常见 sing-box 分享链接
- 节点组：自动择优（urltest）、手动选择（select）、故障转移
- 目标分流：站点集（域名 / 后缀 / 关键词 / IP 段 / 规则集），先命中先生效
- DNS 分流：国内外上游分离、防污染
- TUN / nftables 透明代理，组件统一升级

## 当前进度

- [x] Phase 0：分支骨架、许可边界、首个模块 `core/`（订阅解析 → sing-box 配置生成）
- [x] Phase 1（后端大部）：Flask 面板后端 API——SQLite 存储（订阅/节点/站点集/设置）、
      订阅 CRUD（自动识别 base64 链接 / Clash YAML）、站点集 CRUD、路由预览（域名/IP 命中判定）、
      配置生成/预览接口、系统状态
- [x] Phase 1（协议与策略）：anytls/wireguard 解析与出站生成；规则集（远程规则抓取/解析/合并进站点集）；
      链式代理（socks/http 出口经前置 detour）；节点组（urltest/selector、动态关键词、默认 auto/manual）；
      节点健康检查（TCP 连通 + TLS 握手延迟，UDP 协议如实标记跳过）
- [ ] Phase 1（剩余）：故障转移组（需真 failover 语义，见下）、订阅分享、导入导出整包
- [x] Phase 2：管理面板前端（Vue 3 自研实现，15 个页面；源码在 `oss/panel/frontend/src/`，
      构建产物提交于 `oss/panel/frontend/dist/`，Flask 直接托管 dist，部署时不需要 node）
- [ ] Phase 3：系统集成（nftables/TUN 部署、DNS 接管、安装/升级脚本）
- [ ] Phase 4：客户端（长期可选）

## 快速试用（本机）

```bash
git clone -b oss https://github.com/hzdlive/Open-Box-liandu2024.git openbox-oss
cd openbox-oss/oss
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# 面板后端（开发模式），浏览器打开 http://127.0.0.1:8080
.venv/bin/python panel/run.py
```

可选环境变量：

前端开发（Vue 3 + Vite，源码 `oss/panel/frontend/src/`）：

```bash
cd oss/panel/frontend && npm install && npm run dev   # 开发服务器 http://127.0.0.1:5173（代理到后端 8080）
npm run build                                          # 构建到 dist/（已提交，Flask 直接托管）
```

- `OPENBOX_PANEL_PASSWORD=xxx` —— 给面板设置登录密码（不设则为开放开发模式）
- `OPENBOX_SINGBOX_BIN=/path/to/sing-box` —— 指定 sing-box 内核二进制（默认 `/usr/local/bin/sing-box`）
- `OBX_DB=/path/to/panel.db` —— 数据库位置（默认 `~/.openbox-oss/panel.db`）
- `OBX_TRAFFIC_COLLECT=1` —— 开启每日流量采集（需要内核运行）
- `PORT=8080` —— 监听端口

说明：

- 不装 sing-box 也能跑面板：订阅/站点集/规则/路由预览/配置生成都可用；
  内核相关功能（启动服务、应用配置、连接页、流量统计、热切换）会提示内核未运行。
- sing-box 可用官方 Release（SagerNet/sing-box），或从 GPL 源码包自行构建；
  本分支生成的配置面向标准 sing-box。
- 路由器部署（OpenWrt）见 `scripts/install.sh --kernel-url <tarball>`。

路线图见 [docs/roadmap.md](docs/roadmap.md)。

路线图见 [docs/roadmap.md](docs/roadmap.md)。

## 许可

- 本分支新增代码：MIT（见 [LICENSE](LICENSE)）
- 第三方组件：sing-box（GPL）、zashboard 基座（MIT）、Node.js、Geo 数据等，各按原许可；随包保留原始许可证
- 上游 Open-Box 自有程序：闭源专有许可，**不在本分支内**
