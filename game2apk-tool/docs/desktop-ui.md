# 桌面 UI 视觉层

桌面版保留标准 Tk 控件和零额外运行时依赖，但增加了一层独立的视觉原语：

- `LiquidBackdrop` 在背景上以低频坐标动画移动柔和光斑，动画只更新 Canvas 的 transform-like 坐标，不改变布局。
- `GlassCard` 使用圆角、多层描边和高亮边缘模拟玻璃卡片；Windows 11 上会尽力启用 DWM transient/Mica 背景，旧系统自动回退。
- `GlassButton` 提供悬停颜色和按压反馈，快速响应且可被中断。
- 设置 `GAME2APK_REDUCE_MOTION=1` 可关闭背景运动，保留操作反馈。

动画遵循短时、可中断、只做装饰的原则；构建、检查、下载等功能逻辑仍由原有 Python 服务完成。发布包不需要浏览器或 Android 工具链运行时。
