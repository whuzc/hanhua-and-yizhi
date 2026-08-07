# RPG Maker MV 转 Android APK 工具：冻结架构与验收门槛

状态：总设计基线 v1  
日期：2026-08-07  
目标：把 `仙肴圣餐超魔改 Ver22` 的 RPG Maker MV `www` 内容打成可签名、可侧载安装的 Android APK；同时提供可复用的 Windows 图形工具和可选的 DeepSeek 预翻译功能。

## 1. 已冻结的范围

- 当前只支持“已解包的 RPG Maker MV 项目”：必须存在 `www/index.html`、`www/js/rpg_core.js`、`www/data/System.json`。不宣称支持任意 Windows 游戏、RPG Maker XP/VX/VX Ace/MZ 或需要模拟 x86 Windows 的游戏。
- 原游戏目录永久只读。检查、翻译、补丁注入和 Gradle 构建一律发生在带安全标记的临时副本中。
- 旧的 `仙肴圣餐超魔改 Ver22/android` 是失败样本，只用于提取失败原因，不作为新模板基线，也不得覆盖。
- 发布目标只有本地侧载 APK；不实现 Google Play、AAB 或 Play Asset Delivery。
- APK 内不包含 DeepSeek API 密钥，也不在手机端调用 DeepSeek。翻译只在 Windows 构建前发生。
- 当前目标游戏已经包含大量中文，默认跳过翻译；用户可显式强制翻译未汉化的其他 MV 项目或其中的非中文文本。

## 2. 已确认的目标游戏事实

- 引擎：RPG Maker MV 1.6.1。
- 实际逻辑分辨率：YEP Core Engine 配置为 1024 x 768，比例 4:3。
- `www`：2524 个文件，约 1.221 GiB。
- 图片和音频均使用 RPG Maker MV 标准加密资源；保留 `.rpgmvp`、`.rpgmvo` 和 `System.json` 中的密钥信息，不做解密或 DRM 绕过。
- 已启用约 70 个插件。关键自定义键包括：A -> 公共事件 25（立绘开关）、W -> 公共事件 294（导石快捷）、Ctrl -> 消息跳过。
- `www/save` 中存在个人存档。默认不打包，避免泄露、重复导入或覆盖手机端存档。
- 旧失败样本曾生成约 1.30 GB APK，这只证明“大文件能被打包”，不证明真机可玩。

## 3. 总体结构

新工程固定放在 `game2apk-tool/`，与原游戏和旧失败样本隔离：

```text
game2apk-tool/
  src/game2apk/              Windows GUI、CLI、检查、翻译、构建和验收逻辑
  templates/android-rpgmv/   干净、无游戏资产的版本化 Android 模板
  tests/                     纯单元测试、小型 MV 夹具和集成测试
  scripts/                   构建便携版、验收 APK 的入口
  docs/                      用户手册和开发说明
  dist/                      便携工具与最终 APK；不放密钥
  .work/                     可删除的临时工作区；必须有安全标记
  .state/                    项目配置、翻译缓存、签名状态；默认不打包分发
```

Windows 端采用 Python 3.11 + Tkinter/ttk，并同时提供 CLI。首版避免大型 GUI 运行时依赖，使用 PyInstaller 生成便携目录。Android 端采用 Java、Gradle Groovy DSL 和单 Activity，尽量减少依赖；唯一必要的 Jetpack 依赖是稳定版 `androidx.webkit`。

## 4. 构建流水线

1. **选择与识别**：用户选择游戏根目录或 `www`。检查器识别 MV 版本、标题、加密资源、逻辑分辨率、插件和自定义键。
2. **静态门禁**：检查启用插件中的 `require`、`fs`、`path`、`process`、`nw.gui`，大小写冲突、非法/过长路径、丢失资源、视频/音频格式和源目录可写风险。明确区分“兼容、需补丁、阻断未知”。
3. **语言判断**：从允许翻译的字段采样，不只相信 `System.locale`。若简体中文占比达到阈值，默认关闭翻译。
4. **可选翻译**：仅写入工作副本，生成可预览差异和翻译报告；失败条目保留原文。
5. **安全暂存**：只复制 `www`，排除 `save/`、`*.rpgsave`、`*.sfk`、`*.sfl`、编辑器临时文件和旧 Android 目录。复制前检查可用空间，建议至少为源资源体积的 2.5 倍再加 2 GiB。
6. **输入桥注入**：在暂存副本的 `index.html` 中、`rpg_core.js` 之后注入 `game2apk-input.js`；找不到唯一注入点时阻断，不猜测修改。
7. **模板生成**：写入应用名、稳定包名、版本号、图标和控制配置；API 配置、路径和密钥绝不进入 APK。
8. **Gradle 构建**：使用可配置的 Android SDK/JDK/Gradle 缓存目录，针对大资产配置 JVM 内存和 `noCompress`（至少包含 `rpgmvp/rpgmvo/rpgmvm/ogg/m4a/webm`）。Windows 上若受控工作目录含非 ASCII 字符，必须临时用 `subst` 把同一目录映射为仅含 ASCII 的空闲盘符，并从该盘符以 `--no-daemon` 执行 Gradle，避免复用映射前启动、看不到临时盘符的 daemon；文件仍留在带安全标记的 `.work`，成功、失败或取消都要在所有子进程退出后于 `finally` 解除映射。
9. **稳定签名**：首次为包名生成独立签名密钥，后续构建必须复用。密钥密码不得写入日志或 APK；在 Windows 上可用 DPAPI 保护本机保存的密码，并向用户提供明确的密钥备份提示。
10. **验收输出**：输出签名 APK、SHA-256、包名/版本、证书摘要、资源清单和验证报告。任何一步失败时保留诊断日志，但不得把旧 APK 当作新结果。

所有删除操作只能命中 `.work` 下同时包含工具安全标记和预期项目 ID 的目录；不得对用户选择的源目录执行递归删除。临时 `subst` 盘符只允许指向该次已验证的工作目录，不能作为删除范围判断依据。

## 5. Android 运行壳

### 5.1 WebView

- 使用 `WebViewAssetLoader` 从 `https://appassets.androidplatform.net/assets/www/index.html` 加载，保持同源语义；不使用 `file:///android_asset`。
- 开启 JavaScript、DOM Storage、硬件加速和无需手势的本地媒体播放；关闭文件 URL 跨域访问、明文流量和外部导航。
- APK 不申请 `INTERNET` 权限。若游戏试图打开网络 URL，默认阻止并写诊断。
- 不向不受信任的游戏脚本暴露宽泛的 `addJavascriptInterface`。原生层只通过受控的 `evaluateJavascript` 调用输入桥。
- WebView 的 localStorage 随相同包名和相同签名的覆盖安装保留；工具不得通过卸载实现更新。

### 5.2 输入桥

输入桥不派发浏览器合成 `KeyboardEvent`，而是调用 MV 的 `Input._onKeyDown/_onKeyUp`，让游戏最终的 `Input.keyMapper` 决定含义。这样 A、W、Ctrl 以及插件重新映射的按键都能走原游戏输入路径。

原生覆盖层支持多点触控和独立 pointer ID：

- 左下：半透明四向/八向摇杆，含死区和方向切换释放。
- 右侧默认关键键：`A/立绘`、`W/导石`、`Ctrl/跳过`。工具允许修改标签、键码、位置、大小、透明度和“点按/按住”模式。
- 非控件区域单击：Enter/OK。为区分双击，单击在系统双击窗口确认后触发。
- 非控件区域双击：Esc/Cancel，并取消待触发的单击。
- 隐藏按钮：隐藏摇杆和关键键，仍保留单击/双击手势；留下极小的半透明恢复柄，并支持三指长按恢复。
- Android 系统返回键优先发送一次游戏 Cancel；不得第一次按下就结束 Activity。
- 控件显示状态、透明度和布局写入 SharedPreferences，应用重启后保留。

Android 内嵌控制配置契约为版本化 JSON，首版核心字段如下：

```json
{
  "schemaVersion": 1,
  "tap": {"singleKeyCode": 13, "doubleKeyCode": 27},
  "joystick": {"enabled": true, "deadZone": 0.22, "diagonal": true},
  "overlay": {"opacity": 0.38, "hiddenByDefault": false},
  "buttons": [
    {"id": "portrait", "label": "立绘", "keyCode": 65, "mode": "tap"},
    {"id": "warp", "label": "导石", "keyCode": 87, "mode": "tap"},
    {"id": "skip", "label": "跳过", "keyCode": 17, "mode": "hold"}
  ]
}
```

未知 `schemaVersion` 必须拒绝并显示可诊断错误，不可静默猜测。

## 6. DeepSeek 翻译流水线

- API Base URL 默认 `https://api.deepseek.com`，先通过 `GET /models` 获取当前模型；无法获取时允许用户手工填写模型名，避免永久硬编码已淘汰型号。
- 使用 `POST /chat/completions` 和 JSON Output；首选非思考模式、低随机性。处理空内容、截断、`content_filter`、401/402、429、500/503 和断点续传。
- API Key 只接受遮罩输入或 `DEEPSEEK_API_KEY`，默认仅在当前进程内存中存在；日志必须脱敏。
- 调用前明确告知“选中的游戏文本将发送给第三方 DeepSeek 服务”，需要用户确认。图片、音频、存档、脚本和密钥不上传。
- 首版安全翻译范围：数据库的显示名称/说明/消息字段，地图和公共事件中的显示文本、滚动文本与选项，System terms。脚本、插件源码、note 标签、文件名和资源路径默认不翻译。
- 必须保护并逐项校验 MV 控制码和占位符，例如 `\\V[n]`、`\\N[n]`、`\\C[n]`、`\\I[n]`、`%1`、`{0}`、HTML/note 标签和转义字符；保护项数量或内容不一致时拒绝应用该译文。
- 相邻的消息行作为带稳定 ID 的块发送，返回 JSON 中 ID、数组长度和占位符均需匹配。无法满足时保留原文并列入人工复核。
- 翻译记忆以“原文 + 目标语言 + 模型 + 提示词版本 + 术语表哈希”为键，去重、可恢复、可重新应用；每次输出原文/译文差异和失败清单。
- 对当前已汉化目标，构建默认不调用 API。

## 7. 签名与版本契约

- 每个 `applicationId` 对应一把长期密钥。版本升级只能递增 `versionCode` 并复用同一签名。
- 自动生成的签名材料放在 `.state/signing/<applicationId>/`，不进入 `dist`、源码包或日志。
- 最终构建必须为 `debuggable=false` 的 release APK。
- 输出验收至少执行：`aapt2 dump badging` 或等价元数据读取、`zipalign -c -v 4`、`apksigner verify --verbose --print-certs`、SHA-256，并确认文件时间晚于本次构建开始时间。
- 安装验证使用覆盖安装语义；不得建议先卸载旧版本来掩盖签名、包名或存档兼容问题。

## 8. 验收分级

只有所有必需层级完成，才可宣称相应结论：

### A. 工具层（必需）

- 检查器、路径安全、排除规则、源目录不变性、翻译字段提取、占位符保护、缓存恢复、配置渲染和签名状态均有自动化测试。
- 小型 MV 夹具能完整走完 inspect -> stage -> build -> verify。
- GUI 的长任务不阻塞主线程，可取消且错误可诊断；CLI 与 GUI 调用同一领域逻辑。

### B. Android 输入层（必需）

- 纯 Java 测试覆盖摇杆死区、对角方向、pointer 分离、按键 down/up、单击延迟、双击取消单击、隐藏/恢复。
- 合成 HTML/MV 输入夹具能证明 Enter、Esc、方向、A、W、Ctrl 均到达输入桥，且控件触摸不会同时触发页面单击。

### C. 目标 APK 静态层（必需）

- 对真实 1.221 GiB `www` 生成新的 release APK。
- 包名、版本、签名、对齐、SHA-256、资产数量和关键文件存在性全部核验。
- 原游戏目录在构建前后无内容变化，`www/save` 未进入 APK。

### D. 设备运行层（“可玩”结论必需）

- 在 Android 7+ 的真实设备或可用模拟器上完成安装、冷启动和二次启动。
- 验证标题/地图、加密图片、背景音乐/音效、读写存档并重启恢复。
- 验证摇杆移动、A/W/Ctrl、单击确定、双击取消、系统返回、隐藏与恢复、多点同时操作。
- 至少进入一次菜单、地图事件和战斗；收集无致命异常的 logcat。

若没有设备或模拟器，只能交付“已签名、静态验收通过的候选 APK”，不得写“已验证可玩”。

## 9. 实现任务文件所有权

- Android 模板任务只写 `game2apk-tool/templates/android-rpgmv/` 及其局部测试/说明。
- Windows 工具任务写 `game2apk-tool/` 的其余部分，不改 Android 模板实现。
- 集成与修复任务在前两者结束后才获得全目录写权限，并负责生成真实 APK。
- 独立 QA 任务默认只读产品代码，只写审查报告；发现问题后由单独修复任务处理。

该所有权规则用于非 Git 共享工作区，避免并发覆盖。
