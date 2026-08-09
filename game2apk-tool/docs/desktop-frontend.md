# 桌面前端壳

Release 默认打开 Tk 桌面向导，因为它包含完整的本地项目选择、暂存、构建、签名和静态验收流程。仓库同时提供 `--web` 视觉壳，方便体验 StarRail Calc 风格的 topbar、玻璃卡片、液态光斑和状态动效：

```powershell
.\game2apk-tool.exe --web
```

`--web` 只绑定 `127.0.0.1`，静态资源严格限制在 `frontend/`，`/api/health` 只读返回本机工具链发现结果，`/api/inspect` 仅返回“由桌面 GUI 执行”的边界提示。浏览器不能安全地读取用户本地路径、弹出可信的目录选择器或持有签名密码，因此它不是构建入口；完整操作仍回到默认 Tk GUI。Release 不包含 Android SDK/JDK、原游戏资源、存档、APK、签名材料或 API 凭据。

CSS 使用 `backdrop-filter`（不支持时回退到半透明表面）、仅 transform/opacity 的可中断动效、按钮按压缩放和 `prefers-reduced-motion`；桌面用户也可以设置 `GAME2APK_REDUCE_MOTION=1` 禁用 Tk 液态背景。
