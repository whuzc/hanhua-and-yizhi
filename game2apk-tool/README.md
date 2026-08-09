# game2apk-tool

当前发布候选为 versionCode `7`、versionName `1.2.0`（由 6/1.1.0 升级），包含可逆无敌、战斗胜负控制、作弊器面板、事件回想传送和加密音频修复。

Windows 本地工具：检查 RPG Maker MV、在受标记的 `.work` 副本中暂存和补丁、可选离线翻译、Gradle 构建、稳定签名并做 APK 静态验收。原游戏目录只读；本项目不生成 AAB。

Windows portable 版默认打开完整的 Tk 桌面向导；它使用独立的玻璃/液态视觉层：动态光斑、圆角卡片、DWM 背景和按压反馈见 `docs/desktop-ui.md`。另有 `game2apk-tool.exe --web` 可选打开 StarRail Calc 风格的玻璃前端预览（完整构建仍由默认 GUI 执行），说明见 `docs/desktop-frontend.md`。动画可用 `GAME2APK_REDUCE_MOTION=1` 关闭。

## 快速开始

```powershell
$env:PYTHONPATH = (Resolve-Path .\game2apk-tool\src).Path
python .\game2apk-tool\scripts\game2apk.py inspect ".\仙肴圣餐超魔改 Ver22"
python .\game2apk-tool\scripts\game2apk.py run ".\仙肴圣餐超魔改 Ver22" `
  --template .\game2apk-tool\templates\android-rpgmv `
  --version-code 7 --version-name 1.2.0
```

签名密码默认优先读取稳定 `applicationId` 对应的 Windows DPAPI 凭据。首次创建或 standalone 签名只能使用 `--password-env NAME`、`--password-stdin` 或 `--password-prompt`；`run` 对应为 `--sign-password-env NAME`、`--sign-password-stdin` 或 `--sign-password-prompt`。DeepSeek 只允许 `--api-key-env NAME`、`--api-key-stdin` 或 `--api-key-prompt`，其中 argv 只出现环境变量名，不出现秘密值。旧的 `--api-key VALUE`、`--password VALUE`、`--sign-password VALUE` 及等价 raw-secret 参数会被拒绝。

本次更新目标 APK 固定为 `com.game2apk.xianyaoshengcanver22`、versionCode `7`、versionName `1.2.0`。稳定 keystore 位于 `.state/signing/<applicationId>/`，密码不写入日志、报告、APK、dist 或子进程 argv。覆盖安装必须继续使用同一 applicationId、同一签名证书，并使用 `adb install -r`；不要卸载或清除应用数据，否则 WebView 存档无法保留。详见 `docs/storage-and-upgrade.md`。

## Android 输入契约

覆盖层保持半透明横屏布局，只消费实际按钮命中区域；游戏空白区的单指事件原样留给 WebView/MV `TouchInput`。因此选择窗口会按触点切换选项，地图会保留 `Game_Temp.setDestination` 的触摸寻路、默认 dash 和事件交互，单指长按也保留 MV 消息加速语义。

屏幕键位如下：

| 区域 | 行为 | MV keyCode |
| --- | --- | ---: |
| ↑ ↓ ← → | 按住持续方向，抬起立即释放，可多点同时按 | 38 / 40 / 37 / 39 |
| 确认 | tap pulse，Enter/OK | 13 |
| 取消 | tap pulse，X；保留原始 X code | 88 |
| ESC | tap pulse，Escape | 27 |
| 立绘 | tap pulse，A；目标游戏 Common Event 25 | 65 |

系统返回键和游戏空白区两指轻点都产生一次 `27` cancel/back pulse。两指轻点必须两指都从游戏区开始，第二指在短窗口内落下，移动不超过 slop 且短时全部抬起；控制区多点、超时、拖动和三指不会误触发。识别第二指时只向 WebView 发送一次独立 `ACTION_CANCEL` 副本。隐藏/恢复控件、三指长按恢复、页面导航和 Activity 生命周期都会执行 `releaseAll`。

## 安全边界与测试

```powershell
python .\game2apk-tool\tests\run_tests.py
```

测试覆盖 Python 安全来源、raw-secret 拒绝、日志/argv 脱敏、ZIP 规范化碰撞、默认 icon、暂存排除和 FakeTransport；Node 覆盖 MV key pulse、选择窗口 letterbox、地图目的地/dash/NPC 触摸和长按。Android Java 测试位于 `templates/android-rpgmv/app/src/test`，可用独立 JUnitCore 运行；不要依赖漂移的硬编码测试数量。

便携构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\game2apk-tool\scripts\build-portable.ps1
```

portable 不得包含原游戏、存档、APK、AAB、keystore、DPAPI 文件或任何凭据值。完整修复和候选证据见 [docs/06-security-remediation-and-rebuild.md](docs/06-security-remediation-and-rebuild.md)。

## 项目定位与版权边界

`game2apk-tool` 是一个面向 Windows 的本地迁移工具：它把用户自己拥有或获授权的 RPG Maker MV 项目暂存到干净模板中，生成可侧载安装的签名 APK，并给出可追溯的静态验收报告。它不是游戏发行平台，也不包含原游戏内容、破解补丁包或自动上架流程。

请只处理自己拥有版权或取得分发授权的项目。GitHub 源码仓库只分享工具代码、干净 Android 模板、测试和文档；原游戏目录、`www` 资源、加密密钥、存档、签名材料、API Key 以及任何生成的 APK 都属于用户本地数据，严禁提交或上传。生成 APK 仅供授权用户本地测试/侧载，不应作为项目 Release 附件分发。

## 主要功能

- **MV → Android**：检查 RPG Maker MV 目录、识别引擎与分辨率、排除存档、在受标记的 `.work` 副本中补丁，使用版本化 Android 模板构建并静态验收。
- **工具链自动发现**：启动时优先读取已存在的 `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME`、`PATH`、Android Studio 默认目录和用户配置；如果本机已有 Android 工具，会直接调用，不重复安装。缺少组件时仅在用户点击下载并确认后访问官方 HTTPS 地址，安装目录由用户选择。Command-line Tools 下载后仍需用户用 `sdkmanager` 或 Android Studio 安装项目所需的 platform/build-tools/platform-tools；工具不会静默接受许可证。
- **可选 DeepSeek 翻译**：默认不联网、不翻译。勾选强制翻译并明确确认第三方传输后，使用环境变量名、stdin 或隐藏 prompt 提供 Key；Key 不出现在 argv、日志、报告、APK 或 portable。建议先备份并逐段审阅机器翻译结果。
- **签名与静态验收**：沿用固定 `applicationId=com.game2apk.xianyaoshengcanver22`、`versionCode=7`、`versionName=1.2.0` 的升级身份，自动完成 zipalign/apksigner/manifest/资源清单等静态检查；没有连接手机时不会宣称已完成实机验证。
- **手机输入契约**：悬浮层保留确认、取消、ESC、立绘和四向方向键；方向键按住持续、抬起立即释放。单指点击游戏区保持 MV 原触摸语义（选项、地图目的地、dash、NPC/事件互动），单指长按加速文本；双指轻点发送一次返回/取消，三指和多余触点被忽略。悬浮层可以隐藏，避免遮挡原游戏。
- **内置作弊器**：右上角入口可打开金币 `999999999`、角色字段编辑（等级、经验、HP/MP、基础参数及游戏存在的淫欲等扩展字段）、免费物品商店、无敌、回想房间传送、战斗强制胜利/失败。免费商店不做购买限额保护，仅提示按需购买；无敌开启时保存当前 HP/攻击/防御快照，关闭时按角色当前正常值恢复而不是覆盖升级后新值。作弊可能破坏事件、数值或存档，请复制存档后按需使用。
- **存档升级契约**：应用升级必须保持同一 `applicationId` 和同一签名证书，并使用 `adb install -r` 或系统覆盖安装；不要卸载、清除数据或更换签名。WebView 的 localStorage、RPG Maker 存档和设置因此可以保留。新版本只增加兼容字段，不主动删除用户存档。

## Windows portable

Release 包不内置 AndroidDev/SDK/JDK/Gradle 缓存，体积更小且不会夹带第三方工具授权。解压到用户有写入权限的目录后双击 `game2apk-tool.exe`，默认打开完整 Tk 向导：选择项目目录 → 检查 → 配置/发现工具链 → 填写应用与签名 → 构建并验收。工具链路径只保存到当前用户 `%APPDATA%\\game2apk-tool\\toolchain.json`，不会写回仓库。

如只想体验 StarRail Calc 风格的毛玻璃视觉壳，可运行：

```powershell
.\game2apk-tool.exe --web
```

`--web` 仅绑定 `127.0.0.1`，提供静态前端、只读工具链健康检查和明确的桌面 GUI fallback；浏览器不能安全地读取本地游戏目录或持有签名密码，因此完整构建仍从默认 GUI 执行。设置 `GAME2APK_REDUCE_MOTION=1` 可关闭 Tk 液态背景；浏览器前端响应 `prefers-reduced-motion`。

## 从源码运行

需要 Windows、Python 3.11（`<3.12`）、JDK 17、Gradle wrapper 和 Android SDK build-tools。项目运行时依赖仅 Python 标准库；Node.js 只用于运行 MV 回归脚本。建议在仓库根目录执行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\game2apk-tool\src).Path
python .\game2apk-tool\scripts\game2apk.py --help
python .\game2apk-tool\tests\run_tests.py
python .\game2apk-tool\src\game2apk\portable_entry.py --web
```

如需打开源码 GUI，可运行 `python .\\game2apk-tool\\scripts\\game2apk.py gui`。构建 portable 需要 PyInstaller：

```powershell
powershell -ExecutionPolicy Bypass -File .\game2apk-tool\scripts\build-portable.ps1
```

## 首次配置 Android 工具链

1. 启动 GUI，等待“Android 工具链”卡片完成本地扫描。已有 Android Studio/SDK/JDK 时优先点击保存并重检，确认 SDK、JDK 和 Gradle 用户目录。
2. 如果缺少 SDK/JDK，点击对应的官方工具下载按钮，选择安装位置并阅读确认框。下载仅允许官方 HTTPS host，失败时可以改为手动选择已下载目录。
3. Command-line Tools 只提供 `sdkmanager`，按模板的 `compileSdk`/`buildToolsVersion` 安装 platform 和 build-tools；需要手机调试时再安装 platform-tools。接受许可证和安装组件的动作由用户执行。
4. Gradle wrapper 首次构建会把可再生缓存写入用户 Gradle 目录，不会写入 portable 或 Git 仓库。

## 构建、签名与安装 APK

命令行可先检查项目，再执行完整 run（Key/密码只使用安全来源）：

```powershell
$env:PYTHONPATH = (Resolve-Path .\game2apk-tool\src).Path
python .\game2apk-tool\scripts\game2apk.py inspect ".\我的MV项目"
python .\game2apk-tool\scripts\game2apk.py run ".\我的MV项目" `
  --template .\game2apk-tool\templates\android-rpgmv `
  --version-code 7 --version-name 1.2.0 `
  --sign-password-prompt
```

GUI 构建完成后会显示 APK 路径、SHA-256、签名候选和静态报告。安装到已连接设备前确认包名/证书与现有版本一致：

```powershell
adb devices
adb install -r "D:\\output\\game2apk.apk"
```

`adb install -r` 只覆盖安装，不清除数据；若系统提示签名不一致，停止操作并检查是否误用了另一份 keystore。不要为了“修复安装”而卸载应用，否则存档可能丢失。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 启动提示缺 SDK/JDK/aapt2/zipalign/apksigner | 在工具链卡片选择实际 SDK/JDK 根目录并保存；SDK 根目录应直接包含 `platforms`、`build-tools`，JDK 根目录应直接包含 `bin\\java.exe`。 |
| 已安装 Android Studio 但没有被发现 | 检查 `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME` 和 PATH，或手动选择目录；保存的配置位于 `%APPDATA%\\game2apk-tool\\toolchain.json`。 |
| Gradle 下载或构建失败 | 检查网络/代理和磁盘空间，删除用户 Gradle 缓存中的不完整下载后重试；不要删除当前项目源码、`.state` 或存档。 |
| APK 安装失败“签名冲突” | 使用原 applicationId 对应的 keystore；不能用新随机证书覆盖旧安装。 |
| 覆盖后找不到存档 | 确认使用 `adb install -r`、相同包名和相同签名，且没有清除 Android 应用数据；检查游戏内存档目录和 WebView storage。 |
| 手机没有声音 | 先确认原 MV 项目包含音频；加密音频移动端必须使用 `.ogg → .rpgmvo`，并在系统音量/蓝牙路由可用时重新启动游戏。 |
| 触屏选项/移动/互动异常 | 检查是否点击了悬浮控制区；单指点击游戏区保持原 MV 触摸，双指才是返回/取消，长按才是文本加速。 |
| 作弊器造成事件或数值异常 | 回退到使用作弊前的存档；免费商店和强制胜负没有“购买限额保护”，请按需使用并预留可恢复备份。 |

## 分享前检查清单

```text
[ ] GitHub 只包含工具源码、模板、前端资源、测试和文档
[ ] 未提交 APK/AAB、原游戏/www、存档、.jks/.keystore、.state、DPAPI 或 API Key
[ ] Release portable 扫描无 .rpgsave、密钥、密码字段和 APK
[ ] 给他人的安装说明要求同包名/同证书 + adb install -r
[ ] 明确说明 DeepSeek 是可选第三方传输，作弊功能可能破坏存档
```
