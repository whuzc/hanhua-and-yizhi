# 旧 Tk 排障 UI 视觉层

浏览器前端是 Release 默认界面。该文档记录保留的标准 Tk 排障界面：它使用零额外运行时依赖，只有在 `game2apk-tool.exe --legacy-gui` 时才打开，并增加了一层独立的视觉原语：

- `LiquidBackdrop` 在背景上以低频坐标动画移动柔和光斑，动画只更新 Canvas 的 transform-like 坐标，不改变布局。
- `GlassCard` 使用圆角、连续描边和轻微偏移阴影模拟玻璃卡片，避免分段描边造成接缝；Windows 11 上会尽力启用 DWM transient/Mica 背景，旧系统自动回退。
- `GlassButton` 提供悬停颜色和按压反馈，快速响应且可被中断。
- 设置 `GAME2APK_REDUCE_MOTION=1` 可关闭背景运动，保留操作反馈。

动画遵循短时、可中断、只做装饰的原则；构建、检查、下载等功能逻辑仍由原有 Python 服务完成。默认浏览器前端的完整操作说明见 `desktop-frontend.md`；两种界面都不内置 Android 工具链运行时。
