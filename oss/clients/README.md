# 客户端（Phase 4b 骨架）

原生双端：`android/`（Kotlin）+ `ios/`（Swift），包名/ID 均为 `com.openbox.oss`
（刻意避开闭源 App 的 `com.openbox.app`）。复刻的公开行为：路由器配对、
订阅同步、模式切换、Wi-Fi 自动暂停、分享链接导入。面板侧接口见
`../docs/client-api.md`，已实现并测试（`tests/test_phase4.py`）。

## 架构

```
面板 (Flask)                    客户端 App
/api/pair/*      ←扫码/粘贴→   配对（一次性码 → 长期 token）
/api/client/*    ←Bearer Token→ 状态/节点/组切换/配置/同步/Wi-Fi策略
```

- 两端共用同一套面板 API（`PanelApi.kt` / `PanelAPI.swift`），逻辑对等。
- 内核：sing-box 核心经 gomobile 打包（Android `libbox.aar` / iOS
  `Libbox.xcframework`），构建自 GPL 源码包（`docs/kernel-tcp23.md` 所述
  `build-libbox.sh` 流程）。App 只负责建 TUN（VpnService / NEPacketTunnelProvider）
  并把 fd + 面板下发的客户端配置交给核心——见两处 `startCore` 集成点。

## 目录

```
clients/
  android/                      # Android Studio 项目
    app/src/main/
      AndroidManifest.xml       # 权限/Deep Link/VpnService（对标公开 manifest 能力集）
      java/com/openbox/oss/
        api/  PanelApi.kt Models.kt TokenStore.kt   # 面板 API 客户端
        vpn/  ProxyVpnService.kt                    # VpnService + 核心集成点
        sync/ SyncWorker.kt                         # WorkManager 周期同步
        wifi/ WifiPauseReceiver.kt                  # SSID 豁免自动暂停
        ui/   MainActivity.kt PairingActivity.kt ImportActivity.kt
  ios/
    Package.swift  Sources/OpenBoxCore/  # PanelAPI/Models/TokenStore/SyncManager/WifiPolicy
    App/   OpenBoxApp.swift ContentView.swift PairingView.swift Info.plist
    Tunnel/PacketTunnelProvider.swift   # NetworkExtension 目标（Xcode 中建 target 后加入）
```

## 构建

- Android：Android Studio 打开 `clients/android`，`minSdk 31 / targetSdk 36`；
  把 gomobile 产物放到 `app/libs/libbox.aar` 并取消 `app/build.gradle` 里对应行注释；
  补上 `PairingActivity` 的 CameraX + ZXing 扫码接线（TODO 已标）。
- iOS：Xcode 新建 App target（Bundle ID `com.openbox.oss`）+ Network Extension
  target（Packet Tunnel），把 `App/`、`Tunnel/` 文件加入对应 target，
  `OpenBoxCore` 以 Swift Package 引入；配置 App Group `group.com.openbox.oss`、
  `wifi-info` entitlement（SSID 读取用）。

## 诚实说明（验证状态）

- ✅ 面板侧全部接口已被 `tests/test_phase4.py` 覆盖；客户端的数据模型与之逐字段对齐。
- ✅ 权限/Deep Link 清单来自 APK 静态 manifest 分析（未反编译）。
- ❌ 本机无 Android SDK / Xcode，Kotlin/Swift 未编译验证——以“源码骨架 + 完整业务逻辑”交付，
  在真机工具链下按上节步骤构建。
- ❌ `libbox.aar` / `Libbox.xcframework` 需自行用 gomobile 从 GPL 源码包构建（`startCore`
  处为唯一集成点，已留好）。
- ❌ iOS 后台持续 SSID 监控受系统限制（见 `WifiPolicy.swift` 注释），行为弱于 Android，
  这是平台限制不是实现问题。
