# 用户手册

当前发布候选为 versionCode `5`、versionName `1.0.4`，从 4/1.0.3 原地升级；安装更新时不要卸载或清除数据。

## 工作流

选择原 RPG Maker MV 根目录或 `www`，依次执行 inspect → stage → patch → build → sign → verify。原目录只读；`.work/<project-id>` 必须带 marker，存档、备份和临时文件在 stage 时排除。构建前后会复算 source snapshot，任何源树变化都会阻止候选输出。

目标游戏的 YEP Core 有效画布为 1024×768；Android 运行时保持 `sensorLandscape`，WebView asset origin 固定为 `appassets.androidplatform.net`。没有 adb 设备时只能报告静态签名兼容结论，不能声称真机可玩。

## 输入

游戏区单指触摸不再统一映射为 Enter。透明覆盖层的空白区让 WebView 成为原生 touch target，MV 自己处理选择窗口 hitTest、地图 `setDestination`、默认 dash/触摸事件和消息长按加速。

屏幕保留四向箭头和四个动作键：方向 ↑/↓/←/→ 为 38/40/37/39 hold；确认 Enter 为 13，取消 X 为 88，ESC 为 27，立绘 A 为 65，后三者为 tap pulse。立绘键对应本游戏 Common Event 25；W 87、Ctrl 17 和摇杆已移除。

系统返回键和游戏区双指轻点发一个 27 pulse。二指候选要求两指都从游戏区开始，并满足短时间、touch slop 和短时抬起；控制区多点、拖动、超时或三指不 cancel。三指长按恢复优先。隐藏、恢复、页面导航和 Activity destroy 都会 releaseAll。

## 密钥与签名

CLI 不接受秘密值作为 argv。DeepSeek 只能用明确的环境变量名（如 `--api-key-env DEEPSEEK_API_KEY`）、stdin 或隐藏 prompt；签名密码优先使用 applicationId 对应 DPAPI 凭据，standalone 才从 `--password-env NAME`、stdin 或 prompt 取值。子进程只看到 `env:GAME2APK_SIGNING_PASSWORD` 这类变量名，日志、报告、dist、APK 和 portable 不含凭据值。自动化测试使用 FakeTransport，不调用真实 DeepSeek。

## 验收

```powershell
python .\tests\run_tests.py
python .\scripts\game2apk.py --help
powershell -ExecutionPolicy Bypass -File .\scripts\build-portable.ps1
```

Android 更新候选需确认 applicationId `com.game2apk.xianyaoshengcanver22`、versionCode 5、versionName 1.0.4、同一证书、非 debuggable、无 INTERNET、默认 icon 非空、zipalign/apksigner 通过、assets 严格对账且无 save/secret/keystore。覆盖安装只允许 `adb install -r`；禁止卸载和清数据。WebView 存档保留规则见 `docs/storage-and-upgrade.md`；历史验收证据见 `docs/06-security-remediation-and-rebuild.md`。
