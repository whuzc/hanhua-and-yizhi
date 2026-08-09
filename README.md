# game2apk-tool

RPG Maker MV 项目迁移到 Android 的 Windows 本地工具。它把**用户自己拥有或获得授权的 MV 项目**暂存到干净模板中，生成可侧载安装的签名 APK，并输出可追溯的静态验收报告。

> 当前工具版本：`v1.3.9`（作弊标签改用文本文档批量翻译，支持助词例外、集中修复与 2% 失败容忍）
> [下载 Windows portable v1.3.9](https://github.com/whuzc/hanhua-and-yizhi/releases/tag/v1.3.9)

## 这是什么

项目由两个部分组成：

- `game2apk-ui.exe`：面向普通用户的浏览器前端，负责选目录、填写配置、显示进度和结果。
- `game2apk-tool.exe`：无 UI 后台和命令行入口，由前端或脚本调用。

界面采用圆润玻璃质感布局，后台只监听本机 `127.0.0.1` 随机端口。项目不会上传游戏文件，也不会把 Android SDK/JDK、原游戏资源、APK、存档、密钥或 API Key 打进 Release。

本工具不是游戏发行平台，不包含任何原游戏内容、破解补丁或自动上架流程。请只处理自己拥有版权或取得分发授权的项目。

## Windows portable：安装与启动

1. 从 [Releases](https://github.com/whuzc/hanhua-and-yizhi/releases) 下载 `game2apk-tool-windows-portable.zip`。
2. 解压到有写入权限的目录。建议每次更新解压到新目录，不要覆盖正在运行的旧程序。
3. 在 PowerShell 中启动前端：

   ```powershell
   cd "D:\Tools\game2apk-tool"
   .\game2apk-ui.exe
   ```

   Windows PowerShell 默认不会从当前目录执行程序，所以要写 `.\game2apk-ui.exe`，不能只写 `game2apk-ui.exe`。

4. 浏览器打开后，按页面顺序选择游戏目录、检查项目、配置工具链和构建。关闭前端时后台会自动回收。

portable 包不内置 AndroidDev、SDK、JDK 或 Gradle 缓存。它们体积较大且属于第三方工具，首次使用时由用户指定目录或在界面中确认官方 HTTPS 下载。

## 第一次使用

### 1. 选择 MV 项目

点击“浏览目录”，选择包含 `www`、`index.html` 和 `data` 的 RPG Maker MV 项目目录。原目录只读，工具会在受标记的 `.work` 副本中暂存、补丁和构建，不直接修改源项目。

点击“检查项目”后，页面会显示引擎、分辨率、资源和可构建状态。检查未通过时，“构建并验证”不会启用。

### 2. 配置 Android 工具链

工具启动时会自动检查：

- `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME` 和 `PATH`；
- Android Studio 常见安装目录；
- 当前用户保存的 `%APPDATA%\\game2apk-tool\\toolchain.json`。

如果电脑已经安装 SDK/JDK，直接浏览并保存实际目录即可，不会重复下载。SDK 根目录应直接包含 `platforms` 和 `build-tools`，JDK 根目录应直接包含 `bin\\java.exe`。

如果缺少组件，可在工具链卡片点击官方下载按钮，选择安装位置并确认下载。Command-line Tools 只提供 `sdkmanager`；项目所需的 `platform`、`build-tools` 和（连接手机时需要的）`platform-tools` 仍由用户用 SDK Manager 或 Android Studio 安装并接受许可。

Gradle 用户目录是跨项目共用的 `GRADLE_USER_HOME`，不是某一个游戏专属的缓存。模板优先使用阿里云 Gradle ZIP/Maven 镜像；Gradle ZIP 下载失败时自动回退官方 URL，Maven 依赖也保留官方仓库回退。构建后默认保留缓存，可加快下次构建和其他游戏构建；只有磁盘紧张或缓存损坏时才在关闭构建进程后手动清理。不要把 `.state`、存档或原游戏目录当作缓存删除。

### 3. 填写应用与签名

填写应用名、包名、版本名和 versionCode。要覆盖安装旧 APK，必须保持同一个 `applicationId`、同一签名证书，并递增 versionCode。

签名密码和 DeepSeek Key 不应写进命令行参数。桌面前端只在当前构建请求中传递它们，后台不会写入日志、报告、设置文件、APK 或 portable 包。

### 4. 构建并验证

点击“构建并验证”。页面每 500 ms 获取任务状态，显示阶段、百分比、滚动日志、错误、APK 路径、SHA-256、签名候选和静态验收报告。报告区域只保留最近日志，支持手动滚动；点击“取消任务”会请求后台停止当前阶段。

构建失败后，用相同的游戏目录、模板、应用配置和翻译选项再次点击“构建并验证”，工具会复用已完成的暂存/补丁/翻译检查点，跳过这些步骤并直接重试 Android 构建。源目录、配置、模板或翻译思考选项改变时会自动新建安全的检查点；Gradle 自身的任务不会按单个文件断点，已下载的依赖仍由共享 Gradle 缓存复用。

没有连接 Android 设备时，工具只报告静态验收结果，不会声称完成实机验证。

## 可选 DeepSeek 翻译

翻译默认关闭。检查项目时工具会在本地统计文本语言，提示项目是否已经包含中文以及仍存在多少非中文文本；**检测到中文不会自动翻译**。

勾选翻译后仍需明确确认“向第三方 DeepSeek 发送待翻译文本”，并通过环境变量名、stdin 或隐藏 prompt 提供 API Key。API Key 不会出现在 argv、日志、报告、APK 或 portable 包中。

翻译策略：

- 默认模型为 `deepseek-v4-flash`，`v4flash` 和 `v4-flash` 会规范化为该模型；
- 只翻译非中文文本；纯中文块保留，混合文本中的中文片段也保留；
- 连续对话行会组成一个完整消息块发送，保留上下文、行数、顺序和 MV 控制符，不会逐词翻译；
- 默认开启 thinking，可选择关闭，或选择思考强度 `low`、`high`、`max`；强度越高通常越自然，也越慢、越耗 Token；
- 默认每批 20 个文本块、最多 4 路并发，并启用去重、翻译缓存、占位符保护和限流重试。

可用环境变量调整吞吐：

```powershell
$env:GAME2APK_TRANSLATION_CONCURRENCY = "4"  # 1–8
$env:GAME2APK_TRANSLATION_BATCH_SIZE = "20" # 1–100
```

机器翻译仍可能有专有名词或语气问题。建议先备份项目并逐段审阅结果。完整策略见 [docs/translation-performance.md](game2apk-tool/docs/translation-performance.md)。

正文和作弊标签分别统计翻译失败率：失败块占本组不超过 2%（含 2%）时继续生成产物，失败块保留原文并在报告中列出；超过 2% 才停止任务。这样少量模型偶发失败不会让用户完全看不到已完成的翻译效果。

## Android 运行时功能

生成的 APK 面向横屏 WebView/MV 游戏，包含：

- 半透明悬浮控制层：四向方向键、确认、取消、ESC 和立绘键；悬浮层可隐藏；
- 单指点击游戏区保留 MV 原触摸语义：选项切换、地图目的地、dash、NPC/事件互动；
- 单指长按加速文本；双指轻点发送一次返回/取消；三指和多余触点忽略；
- 加密 OGG 音频使用 `.ogg → .rpgmvo`，兼容 Android WebView、外放和蓝牙音频路径；
- APK 静态检查包含 manifest、资源清单、zipalign、apksigner 和签名候选状态。

### 内置作弊器

右上角“作弊”入口会根据目标 MV 项目的运行时数据库动态生成高级选项，尽量适配不同游戏：

- 金币 `999999999`；
- 角色等级、经验、HP/MP、基础参数和项目中识别到的自定义变量（例如淫欲、感度、开发/关系等）；
- 免费物品商店（只提示按需购买，不设置购买限额保护）；
- 可逆无敌；关闭时只移除作弊增加量，保留无敌期间的升级、装备和正常变化；
- 回想房间传送与返回原位置；
- 战斗中强制胜利或失败。

动态菜单依赖项目的 `$dataSystem.variables`、`$dataSystem.switches` 和地图信息。未命名或语义无法判断的字段不会全部暴露，避免把未知变量误当成作弊项；请在游戏内核对效果。作弊可能破坏事件、数值或存档，使用前务必复制存档。

## 覆盖更新与存档

这是转换出来的游戏 APK 的升级规则，不是工具本身的更新规则：

1. 新 APK 保持相同 `applicationId` 和同一签名证书；
2. versionCode 递增；
3. 使用系统覆盖安装或 `adb install -r`；
4. 不要卸载应用、清除数据或更换 keystore。

示例：

```powershell
adb devices
adb install -r "D:\output\game2apk.apk"
```

这样 WebView localStorage、RPG Maker 存档和设置才有机会保留。若系统提示签名冲突，停止安装并检查是否误用了另一份 keystore。

工具 portable 的更新则是：关闭旧的 `game2apk-ui.exe`，把新 ZIP 解压到新目录，再运行新目录中的 `.\game2apk-ui.exe`。`%APPDATA%\game2apk-tool\toolchain.json` 不随 portable 目录移动；旧目录中的 `.state`、Gradle 缓存和项目文件请按需保留，不要把它们上传到 GitHub。

## 命令行与源码运行

portable 兼容入口：

```powershell
.\game2apk-tool.exe --cli --help       # 原有脚本式命令行
.\game2apk-tool.exe --backend --port 0 # 无 UI 本机后台
.\game2apk-tool.exe --web              # 兼容：直接打开浏览器前端
.\game2apk-tool.exe --legacy-gui      # 仅排障使用的旧 Tk 界面
```

从源码运行需要 Windows、Python 3.11（`<3.12`）、JDK 17、Gradle wrapper 和 Android SDK build-tools；项目运行时 Python 依赖仅标准库，Node.js 只用于 MV 回归脚本。

```powershell
$env:PYTHONPATH = (Resolve-Path .\\game2apk-tool\\src).Path
python .\\game2apk-tool\\scripts\\game2apk.py --help
python .\\game2apk-tool\\tests\\run_tests.py
python -m game2apk.ui_launcher
```

构建 portable：

```powershell
powershell -ExecutionPolicy Bypass -File .\\game2apk-tool\\scripts\\build-portable.ps1
```

## 测试与安全边界

测试覆盖路径逃逸、raw-secret 拒绝、日志/argv 脱敏、ZIP 规范化碰撞、翻译中文检测与占位符保护、前端 API 会话、MV 触摸/按键/音频/作弊器桥接和 Android 模板静态契约。运行：

```powershell
python .\\game2apk-tool\\tests\\run_tests.py
```

GitHub 仓库和 Release 只包含工具源码、干净模板、前端资源、测试和文档。严禁提交或上传：

- 原游戏目录、`www`、加密密钥和任何未授权资源；
- `.apk`、`.aab`、`.rpgsave`、存档、`.state`；
- `.jks`、`.keystore`、DPAPI 凭据、签名密码和 API Key。

## 文档

- [桌面前端与后台生命周期](game2apk-tool/docs/desktop-frontend.md)
- [Android 工具链配置](game2apk-tool/docs/desktop-toolchain.md)
- [翻译性能、思考模式与缓存](game2apk-tool/docs/translation-performance.md)
- [存档保留与覆盖升级](game2apk-tool/docs/storage-and-upgrade.md)
- [安全修复与静态验收](game2apk-tool/docs/06-security-remediation-and-rebuild.md)

## 许可证与版权

本仓库的公开内容是迁移工具和模板代码。第三方 Android/Gradle/DeepSeek 服务遵循其各自许可与条款。使用者应自行确认游戏内容、翻译文本和生成 APK 的版权与分发权限。
