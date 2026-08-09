# game2apk-tool

当前发布候选为 versionCode `7`、versionName `1.2.0`（由 6/1.1.0 升级），包含可逆无敌、战斗胜负控制、作弊器面板、事件回想传送和加密音频修复。

Windows 本地工具：检查 RPG Maker MV、在受标记的 `.work` 副本中暂存和补丁、可选离线翻译、Gradle 构建、稳定签名并做 APK 静态验收。原游戏目录只读；本项目不生成 AAB。

Windows portable 版的桌面 UI 使用独立的玻璃/液态视觉层：动态光斑、圆角卡片、DWM 背景和按压反馈见 `docs/desktop-ui.md`。动画可用 `GAME2APK_REDUCE_MOTION=1` 关闭。

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
