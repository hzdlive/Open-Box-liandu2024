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

- [x] SQLite 存储：订阅 / 节点 / 站点集 / 设置 / 规则集 / 链式代理 / 节点组 / 健康结果
- [x] 订阅 CRUD（自动识别 base64 链接串 / Clash YAML，解析入库）、节点列表、站点集 CRUD
- [x] 路由预览：输入域名/IP，返回命中的站点集与出口（源项目"规则·真实路由"预览页的核心）
- [x] 配置生成/预览接口（复用 `core/`，含组、链式代理 detour、规则集展开）
- [x] 规则集：远程抓取、clash-classical / domain-list 解析、合并进站点集参与匹配
- [x] 链式代理：socks/http 出口经前置节点/组 detour；加入静态 selector，不进动态 urltest
- [x] 节点组：urltest / selector，动态关键词自动收编，默认 auto / manual
- [x] 节点健康检查：TCP 连通 + TLS 握手延迟；UDP 协议（tuic/hysteria2/wireguard）如实标记跳过
- [ ] 故障转移组：sing-box 原生无 failover 出站类型。真 failover 语义留到 Phase 3，
      方案二选一：a) 基于 GPL 内核源码自研补丁新增出站类型；b) 面板侧 watcher 动态改写。
      当前用 urltest 近似。

## Phase 2 — 面板前端

- 基于 zashboard（MIT）基座 + 自研页面，或全新实现（待定）
- 页面对标：概览、代理·策略、域名穿透、规则调试、订阅管理、出站节点、
  目标分流、链式代理、DNS、后端设置、流量统计

## Phase 3 — 系统集成（2026-10-14 已交付，commit 695cc59）

- core/service.py：KernelManager，pidfile 守护 sing-box 进程，
  启停/重启/版本/日志，只用公开 CLI（version/check/run）
- core/apply.py：构建 → sing-box check 校验 → 原子写入 → 启动/重启；
  坏配置永不替换线上配置
- core/transparent.py：nftables TPROXY 脚本 + ip rule/route + dnsmasq 片段，
  只生成不自动应用（需 root 手动操作）
- 真 failover：failover 组类型（按成员顺序定优先级），core/failover.py
  做健康选举，经公开 clash API（PUT /proxies/{组}）无重启切换；
  明确为面板侧方案，非内核出站类型
- 订阅分享：core/share.py 节点→链接编码器（vmess/vless/trojan/ss，
  与 parser 往返验证），/api/share/qr 出 PNG 二维码
- 整包备份/恢复：core/backup.py，全表 JSON，原子恢复
- oss/scripts/：install/upgrade/rollback/uninstall.sh + OpenWrt procd init
- 面板 API：/api/service*、/api/config/apply、/api/transparent/*、
  /api/failover/elect、/api/share、/api/backup；前端对应页面已接线
- tests/test_phase3.py：假 sing-box 二进制 + stub clash API，全绿
- 未验证项：真机 nft 应用、OpenWrt 实机安装流程（无路由器环境）

## Phase 4 — 客户端（长期）

- 路由器端配对、本地分流/节点分流、订阅同步
- 选型待定（Tauri / Flutter / 原生），先以后端 API 为准

## 不做的事

见 [BOUNDARY.md](../BOUNDARY.md)。任何阶段都不引入闭源二进制，不逆向其实现，
不复刻授权/验签机制。
