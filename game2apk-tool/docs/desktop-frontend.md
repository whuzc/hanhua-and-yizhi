# 桌面浏览器前端与本机后台

发布包提供两个协作的 EXE：

| 文件 | 角色 | 正常使用方式 |
| --- | --- | --- |
| `game2apk-ui.exe` | 可见浏览器前端与生命周期管理器 | 双击或 PowerShell 中运行 `./game2apk-ui.exe` |
| `game2apk-tool.exe` | 无 UI 的本机后台和兼容 CLI | 由 UI 启动；脚本使用 `--cli` |

`game2apk-ui.exe` 会隐藏启动同目录后台，读取其一行 READY JSON 后打开默认浏览器。它不会把端口或会话凭据写入文件。后台在 `127.0.0.1` 随机端口托管 `frontend/` 资源和 API；退出启动器、浏览器心跳超时或显式关闭都会回收后台。浏览器刷新不会立即杀死后台，因此可以安全刷新页面。

## 页面能力

- “浏览目录”通过后台调用 Windows 原生目录选择器，可选游戏根目录/`www`、Android 模板、SDK、JDK 与 Gradle 缓存；浏览器本身不会读取游戏资源。
- “检查项目”提交异步检查任务；检查报告返回前构建按钮保持禁用。
- “构建并验证”按既有服务顺序执行检查、暂存、补丁、可选 DeepSeek 翻译、Gradle 构建、稳定签名和静态验收。页面以 500 ms 轮询显示阶段、百分比、日志、成功结果或错误。
- “取消任务”只设置既有 PipelineService 的取消事件，后端继续使用原有受标记 `.work` 与安全清理约束。
- 工具链卡片可先调用本机已安装的 SDK/JDK；缺少时，点击官方工具下载按钮、选择安装目录并确认后，后台才下载并解压，完成后自动保存路径。Command-line Tools 仍需用户用 `sdkmanager` 安装 platform/build-tools。
- SDK/JDK/Gradle 路径只写入 `%APPDATA%\\game2apk-tool\\toolchain.json`；没有任何静默下载。Release 不含 Android SDK/JDK、Gradle 缓存、原游戏、存档、APK、签名材料或凭据。

## 本机安全边界

静态资源只能从 `frontend/` 提供，路径越界会拒绝。变更型 API 要求同源 HttpOnly `SameSite=Strict` 会话 Cookie 和 `X-Game2Apk-Request: 1`；不提供 CORS，也不监听 LAN。前端的 DeepSeek Key 和签名密码只在当前 loopback 请求体中短暂传递，不经公网；后端不持久化、不输出到日志，并对任务进度和错误做脱敏。

可用的兼容/排障命令：

```powershell
# 推荐：有 UI、自动启动和回收后台
.\game2apk-ui.exe

# 兼容方式：打开完整浏览器前端，但不具备独立启动器的生命周期管理
.\game2apk-tool.exe --web

# 无 UI 后台，适合调试或其他本机前端
.\game2apk-tool.exe --backend --port 0

# 保留脚本自动化接口
.\game2apk-tool.exe --cli --help

# 仅排障用的旧 Tk 界面
.\game2apk-tool.exe --legacy-gui
```

CSS 使用 `backdrop-filter`（不支持时回退为半透明卡片）、短时 transform/opacity 动效、按钮按压缩放和 `prefers-reduced-motion`。高频检查/构建状态只更新文本与进度，不做阻塞性页面动画。
