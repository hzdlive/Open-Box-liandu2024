# Roadmap

## Phase 0 — 骨架与最小可用核心（当前）

- [x] 分支与目录骨架，LICENSE（MIT）/ BOUNDARY.md / README
- [x] `core/`：订阅解析（vmess/vless/trojan/ss/tuic/hysteria2 的 base64 分享链接）
      → 节点模型 → sing-box 配置 JSON 生成（含 tun/mixed 入站、urltest/select 节点组、
      站点集路由规则、DNS 分流、clash_api）
- [ ] 用上游 Release 的 `sing-box-1.14.1-openbox-tcp23-source.tar.gz` 验证构建，
      确认魔改点（tcp23）内容，决定用官方魔改版还是上游 sing-box

验收：`python3 -m core.cli build` 对示例订阅产出合法 sing-box 配置，
`sing-box check -c` 通过（待装 sing-box 后验证）。

## Phase 1 — 配置生成器完善

- Clash YAML 订阅导入；规则集（domain/domain-suffix/keyword/ip-cidr）解析与合并
- DNS 策略：国内外上游分离、FakeIP 可选、防污染默认
- 站点集语义：自上而下先命中生效；IP/域名隔离判定
- 链式代理（前置节点）建模
- 导出 / 导入整包配置

## Phase 2 — 管理面板

- 后端：Python（Flask，用户技术栈）或 Node，二选一待定；
  接口：订阅管理、节点组、站点集、DNS、规则调试（真实路由预览）、连接查看（clash_api）
- 前端：基于 zashboard（MIT）基座重写，或全新实现，待定
- 与 `core/` 共用同一套配置生成逻辑

## Phase 3 — 部署脚本开源重写

- install / update / uninstall 一键脚本（OpenWrt / Debian / Docker）
- 组件校验（sha256）、版本管理、回滚、卸载清理
- 可直接复用并改进上游公开脚本（许可允许）

## Phase 4 — 客户端（长期、可选）

- Android / 桌面客户端的开源实现，评估 Tauri / Flutter 等方案

## 不做的事

见 [BOUNDARY.md](../BOUNDARY.md)。任何阶段都不引入闭源二进制，
不逆向其实现。
