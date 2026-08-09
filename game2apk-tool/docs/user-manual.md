# 用户手册

当前发布候选为 versionCode `8`、versionName `1.3.0`，从 7/1.2.0 原地升级；安装更新时不要卸载或清除数据。

## 工作流

选择原 RPG Maker MV 根目录或 `www`，依次执行 inspect → stage → patch → build → sign → verify。原目录只读；`.work/<project-id>` 必须带 marker，存档、备份和临时文件在 stage 时排除。构建前后会复算 source snapshot，任何源树变化都会阻止候选输出。

目标游戏的 YEP Core 有效画布为 1024×768；Android 运行时保持 `sensorLandscape`，WebView asset origin 固定为 `appassets.androidplatform.net`。没有 adb 设备时只能报告静态签名兼容结论，不能声称真机可玩。

## 输入

游戏区单指触摸不再统一映射为 Enter。透明覆盖层的空白区让 WebView 成为原生 touch target，MV 自己处理选择窗口 hitTest、地图 `setDestination`、默认 dash/触摸事件和消息长按加速。

屏幕保留四向箭头和四个动作键：方向 ↑/↓/←/→ 为 38/40/37/39 hold；确认 Enter 为 13，取消 X 为 88，ESC 为 27，立绘 A 为 65，后三者为 tap pulse。立绘键对应本游戏 Common Event 25；W 87、Ctrl 17 和摇杆已移除。

系统返回键和游戏区双指轻点发一个 27 pulse。二指候选要求两指都从游戏区开始，并满足短时间、touch slop 和短时抬起；控制区多点、拖动、超时或三指不 cancel。三指长按恢复优先。隐藏、恢复、页面导航和 Activity destroy 都会 releaseAll。

## 密钥与签名

CLI 不接受秘密值作为 argv。DeepSeek 只能用明确的环境变量名（如 `--api-key-env DEEPSEEK_API_KEY`）、stdin 或隐藏 prompt；签名密码优先使用 applicationId 对应 DPAPI 凭据，standalone 才从 `--password-env NAME`、stdin 或 prompt 取值。子进程只看到 `env:GAME2APK_SIGNING_PASSWORD` 这类变量名，日志、报告、dist、APK 和 portable 不含凭据值。自动化测试使用 FakeTransport，不调用真实 DeepSeek。

## DeepSeek 翻译设置

浏览器前端默认开启 V4 Flash thinking，强度默认 `high`。启用翻译时可选择：`low`（较快）、`high`（推荐平衡）或 `max`（最慢、为复杂语境预留更多推理预算）；也可关闭 thinking 以优先速度。RPG Maker MV 连续对话行按完整消息块发送，模型会结合同一块中的上下文并保持行数与顺序。

命令行 `translate`/`run` 对应使用 `--thinking-mode enabled|disabled` 与 `--reasoning-effort low|high|max`。真实网络翻译前仍需明确确认第三方传输，Key 只通过环境变量名、stdin 或隐藏 prompt 提供。

## 验收

```powershell
python .\tests\run_tests.py
python .\scripts\game2apk.py --help
powershell -ExecutionPolicy Bypass -File .\scripts\build-portable.ps1
```

Android 更新候选需确认 applicationId `com.game2apk.xianyaoshengcanver22`、versionCode 8、versionName 1.3.0、同一证书、非 debuggable、无 INTERNET、默认 icon 非空、zipalign/apksigner 通过、assets 严格对账且无 save/secret/keystore。覆盖安装只允许 `adb install -r`；禁止卸载和清数据。WebView 存档保留规则见 `docs/storage-and-upgrade.md`；历史验收证据见 `docs/06-security-remediation-and-rebuild.md`。

Gradle 的 `app-release-unsigned.apk` 只是文件名；本工具会在原路径 signed-in-place，必须查看签名/验收报告而不是只看文件名。留空签名密码时会尝试当前 applicationId 的 DPAPI 状态；没有状态又没有密码会直接阻止任务，避免交付真正未签名包。

### 内置作弊器

右上角“作弊”按钮打开面板，可增加金币、修改角色标准属性与经验、开启无敌、进入识别出的回想/场景地图并在离开后返回原地点，以及打开包含数据库物品/武器/防具的免费商店。面板打开时会读取当前游戏的 `$dataSystem.variables`、`switches`、`$dataMapInfos`，按原名生成高级变量、开关和回想候选，并用关键词标注欲望、感度、成长、关系等类别；未命名变量不会全部暴露，插件私有字段也不会被猜测写入。不同游戏仍需玩家确认同名变量的实际含义。免费商店只提示按需购买，不限制购买数量；短时间大量购买可能导致游戏卡顿或崩溃。旧游戏若未提供可识别的变量/地图名称，会回退到工具内置的审计白名单/Map136候选。

无敌会持续将操纵角色的 HP、攻击和防御维持在高值；关闭时只撤销工具增加的参数增量，并按关闭瞬间的当前自然 HP 限制到新的最大 HP，不覆盖无敌期间的升级、装备或其他参数变化。战斗面板中的“战斗胜利/战斗失败”按钮只在战斗场景且战斗尚未结束时启用，分别调用 MV 原生胜利奖励/公共事件流程和失败/可败北规则。
