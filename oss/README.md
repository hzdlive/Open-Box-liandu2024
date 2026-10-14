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
- [x] Phase 1（部分）：Flask 面板后端 API——SQLite 存储（订阅/节点/站点集/设置）、
      订阅 CRUD、站点集 CRUD、路由预览（域名/IP 命中判定）、配置生成/预览接口、系统状态
- [ ] Phase 1（剩余）：Clash YAML 导入、anytls/wireguard 解析、规则集、链式代理、
      节点健康检查、故障转移组/动态组
- [ ] Phase 2：管理面板前端（zashboard MIT 基座 + 自研页面）
- [ ] Phase 3：系统集成（nftables/TUN 部署、DNS 接管、安装/升级脚本）
- [ ] Phase 4：客户端（长期可选）

## 快速试用

```bash
cd oss
../.venv/bin/pip install -r requirements.txt   # 只需 Flask
# 配置生成（纯标准库）
python3 -m core.cli build --sub tests/sample-sub.txt --sites tests/sample-sites.json -o /tmp/config.json
# 面板后端（开发模式）
../.venv/bin/python panel/run.py   # http://127.0.0.1:8080/api/status
# 自检
python3 -m tests.test_core && ../.venv/bin/python -m tests.test_panel
```

路线图见 [docs/roadmap.md](docs/roadmap.md)。

## 许可

- 本分支新增代码：MIT（见 [LICENSE](LICENSE)）
- 第三方组件：sing-box（GPL）、zashboard 基座（MIT）、Node.js、Geo 数据等，各按原许可；随包保留原始许可证
- 上游 Open-Box 自有程序：闭源专有许可，**不在本分支内**
