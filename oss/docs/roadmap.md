# Roadmap

## 目标

**复刻源项目闭源部分（路由器端程序 + 客户端 App）的公开行为**，clean-room 独立实现。
行为规格只来自公开文档（上游 README、release notes、docs），不触碰闭源二进制，
不反编译 / 反汇编 / 逆向。红线见 [BOUNDARY.md](../BOUNDARY.md)。

架构上不照搬源项目（Node+Go 双进程），而是用本分支自己的实现达到同样的用户可见功能。
源项目中纯属授权/验签/防改的机制（Ed25519 验签、激活码、功能权限检查）**不复刻**——
开源软件不需要它们。

## Phase 0 — 配置生成核心（已完成）

- [x] `core/`：订阅解析（vmess/vless/trojan/ss/tuic/hysteria2）→ 节点模型 →
      sing-box 配置 JSON（含 tun/mixed 入站、urltest/select 节点组、站点集路由、DNS 分流）

## Phase 1 — 面板后端 API（进行中）

Flask（Python）实现，对应源项目面板后端除授权外的全部管理能力：

- [x] SQLite 存储：订阅 / 节点 / 站点集 / 设置
- [x] 订阅 CRUD（解析入库）、节点列表、站点集 CRUD
- [x] 路由预览：输入域名/IP，返回命中的站点集与出口（源项目"规则·真实路由"预览页的核心）
- [x] 配置生成/预览接口（复用 `core/`）
- [ ] Clash YAML 订阅导入、anytls/wireguard 协议解析
- [ ] 规则集（远程规则链接）支持、链式代理建模
- [ ] 节点健康检查（调 sing-box / clash_api，或自研 urltest）
- [ ] 故障转移组、动态关键词组

## Phase 2 — 面板前端

- 基于 zashboard（MIT）基座 + 自研页面，或全新实现（待定）
- 页面对标：概览、代理·策略、域名穿透、规则调试、订阅管理、出站节点、
  目标分流、链式代理、DNS、后端设置、流量统计

## Phase 3 — 系统集成

- sing-box 进程管理、配置热切换（复刻"切换不重启内核"：只改写小规则集；
  可直接用 GPL 内核源码中的 `outbound-hot-replace` 补丁思想，自己实现）
- nftables / TUN 透明代理部署、DNS 接管（dnsmasq / 防火墙劫持）
- 安装 / 升级 / 回滚 / 卸载脚本（可复用并改进上游公开脚本）
- 导出 / 导入整包配置、订阅分享（二维码/链接）

## Phase 4 — 客户端（长期）

- 路由器端配对、本地分流/节点分流、订阅同步
- 选型待定（Tauri / Flutter / 原生），先以后端 API 为准

## 不做的事

见 [BOUNDARY.md](../BOUNDARY.md)。任何阶段都不引入闭源二进制，不逆向其实现，
不复刻授权/验签机制。
