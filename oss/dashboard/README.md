# oss-zashboard 分支：基于 zashboard 的二开前端

本分支把面板主 UI 换成基于 [zashboard](https://github.com/Zephyruso/zashboard) 二开的前端。
`oss` 分支的自研 Vue UI 不动，仍可通过 `/legacy/` 访问，作为过渡期回退。

## 为什么选这个版本

- 锁定 **v3.22.0**：最后一个支持 sing-box 的上游版本（含 sing-box 原生 gRPC API
  与 Clash API 兼容层，`src/api/singbox/`、`src/assembly/*/singbox.ts` 俱在）。
- 上游在 **v3.23.0 起移除了 sing-box 支持**（见上游 `docs/sing-box-deprecation.md`），
  因此本分支**不跟进上游 3.23+**，sing-box 相关问题自行维护。
- 许可证 **MIT**，源码内保留上游 `LICENSE`，本文件与 `THIRD_PARTY_NOTICES.md`
  记录来源与修改。

## 目录

- `zashboard-src/` — zashboard v3.22.0 源码 + Open-Box 二开补丁
  - `src/openbox/` — 二开模块：`api.ts`（面板 `/api/*` 封装）、`auth.ts`（登录门禁）、
    `backend.ts`（首次打开自动接入本机 Clash API）、`LoginView.vue`（面板密码登录页）
  - `src/views/manage/` — 管理中心：`ManageView.vue`（tab 骨架）、`SubsTab.vue`（订阅管理，已完整移植）
  - 路由/导航：`src/router/index.ts`、`src/constant/index.ts` 新增 `manage` 路由，
    侧边栏自动出现「管理」入口；`src/i18n/{en,zh,zh-tw,ru}.ts` 新增 `obx` 词条
  - `src/main.ts` — 启动时先查 `/api/auth/status`，需登录则只挂载登录页；
    否则自动注册 Open-Box 后端再挂载主应用
- `zashboard-src/dist/` — 构建产物，**刻意入库**：VPS/路由器上 `git pull` 后直接可用，
  无需在目标机器上装 node/pnpm

## 构建

```sh
cd zashboard-src
# 本机 pnpm 10 可直接构建；上游 packageManager 字段要求 pnpm 11.20.0，
# 若自动下载失败，加 --config.manage-package-manager-versions=false
pnpm install --frozen-lockfile
FONT=none pnpm exec vite build   # 无字体版，体积最小；默认会打全量字体
```

`dist/` 构建后直接提交（本分支策略）。

## 后端配合（本分支已改）

- `oss/core/models.py` — `AppConfig` 新增 `clash_api_listen`（默认 `127.0.0.1`）、
  `clash_api_secret`（默认空）
- `oss/core/singbox.py` — `experimental.clash_api.external_controller` 使用上述监听地址，
  有 secret 时下发 `secret`
- `oss/panel/db.py` — 两个新设置走 `get_setting`，无需数据库迁移
- `oss/panel/app.py`
  - `GET /api/openbox/clash-config` → `{port, secret, listen}`（需登录），供前端自动建后端
  - `/` 托管 `zashboard-src/dist`；旧 UI 改走 `/legacy/`

## 局域网访问注意

zashboard 跑在**浏览器**里，直连 sing-box 的 Clash API（含 WebSocket），
Flask 无法代转。`clash_api_listen` 默认 `127.0.0.1` 时，只有本机浏览器能连上；
要在局域网其他设备上用仪表盘，需把 `clash_api_listen` 设为 `0.0.0.0`
（建议同时设置 `clash_api_secret`）。设置项后续会做到管理中心页面里，
目前可直接改数据库 `settings` 表后重启面板。

## 移植路线图

- [x] 订阅管理（列表/新增/编辑/启用/刷新/删除）
- [ ] 分流站点（站点集 CRUD）
- [ ] DNS 设置
- [ ] 出站节点组
- [ ] 终端分流 / 透明代理 / 面板设置 …
- 实时部分（代理切换、连接、日志、规则、概览）直接用 zashboard 原生能力，不重复造轮子
