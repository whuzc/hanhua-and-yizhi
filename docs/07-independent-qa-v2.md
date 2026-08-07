# 07 独立 QA v2 报告

审查日期：2026-08-07（Asia/Hong_Kong）

审查对象：

- 最终候选：`F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.1-signed.apk`
- 旧 NO-GO 对照：`F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk`
- 最终 run：`F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\fcbb83767c6b47908c67db1f6b05556c`

## 结论

**CONDITIONAL PASS：最终 APK 是签名覆盖安装候选，不是“已真机可玩”结论。**

本次未发现 P0/P1。静态工件身份、V2/V3 签名、资源对账、源存档排除、安全边界、输入源码、最终 stage 资产、Python/Node/Java/Gradle 和 portable 门禁均通过。由于 `adb devices` 没有设备/模拟器，没有执行安装、覆盖安装、卸载、清数据或任何真机交互；真机选择项、点地 dash/NPC、长按文本、双指、方向+动作多点和数据保留仍是 P2 未完成证据项。

本 QA 没有修改产品源码、模板、APK、签名材料、portable 或已有 run 证据；只新增本报告。禁止访问的旧失败 `android` 目录未访问、未枚举、未使用、未修改。未调用真实 DeepSeek。QA 临时目录已在封板前按绝对路径核验并清理。

## 1. 最终工件身份与覆盖安装合同

使用的工具版本/路径：

```text
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt.exe
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt2.exe
F:\AndroidDev\android-sdk\build-tools\36.1.0\apksigner.bat
F:\AndroidDev\android-sdk\build-tools\36.1.0\zipalign.exe
F:\AndroidDev\android-sdk\platform-tools\adb.exe
```

最终候选复算：

| 项目 | 结果 |
|---|---|
| size | 1,283,655,403 bytes |
| LastWriteTimeUtc | 2026-08-07T10:59:30.1282081Z |
| SHA-256 | `ae14a4ffd680dfc93abdced71199176b27ebb933fad5b6884be6f5b6ea893fda` |
| run 内 release APK size/SHA | 1,283,655,403 / 与最终候选完全一致 |

旧 APK 复算为 1,283,655,347 bytes，LastWriteTimeUtc 为 `2026-08-07T08:39:04.0798669Z`，SHA-256 为 `8ab67d7621cebb479999c45c017c6056580e7cb3f96767227bc92b0e7f428c11`。

将两个 APK 复制到全路径 ASCII 的 `C:\Users\24713\AppData\Local\Temp\qa-v2-ascii` 后，副本 SHA-256 分别与原文件一致。对两个 ASCII 副本分别执行以下命令，全部 exit 0：

```text
aapt dump badging <apk>
aapt2 dump badging <apk>
aapt dump permissions <apk>
aapt dump xmltree <apk> AndroidManifest.xml
apksigner.bat verify --verbose --print-certs <apk>
zipalign.exe -c -P 16 -v 4 <apk>
```

最终候选静态元数据：

- applicationId：`com.game2apk.xianyaoshengcanver22`。
- versionCode/versionName：`2` / `1.0.1`。
- compile/target SDK：36；min SDK：24。
- label 非空：`仙肴圣餐超魔改 Ver22`；application icon 非空：`res/ZA.xml`。
- `screenOrientation` 为 `0x6`，即 `sensorLandscape`。
- `android.permission.INTERNET` 不存在。
- `allowBackup=false`、`usesCleartextTraffic=false`；没有 `android:debuggable`，run verification report 复核为 `debuggable=false`。
- `apksigner`：V1=false、V2=true、V3=true、V3.1=false、V4=false。
- 证书 DN：`CN=com.game2apk.xianyaoshengcanver22, OU=game2apk-tool`。
- 证书 SHA-256：`b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14`。
- `zipalign` 输出为 `Verification successful`。

旧 APK 的 package 与证书 DN/SHA 相同，versionCode/versionName 为 `1` / `1.0.0`；因此新旧包满足同包、同证书、1→2 单调升级。旧 APK 的 application icon 字段为空，但这是旧对照包状态，最终 1.0.1 icon 已非空。最终/旧 APK 的 classes.dex 均保留 `appassets.androidplatform.net` 与 `/assets/www/index.html` origin 字符串，静态 origin 未变；最终包 additionally 含 `InputRootLayout`、`TwoFingerTapGestureStateMachine` 等最终输入实现类名。该结果只支持静态 `adb install -r` 覆盖安装兼容判断，不代表已在设备上验证数据保留。本次没有运行 adb install。

## 2. ZIP、stage、源资源与敏感材料

权威证据：

- `F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\fcbb83767c6b47908c67db1f6b05556c\stage-manifest.json`
- `F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\fcbb83767c6b47908c67db1f6b05556c\verification-report.json`
- `F:\code\汉化加转apk\docs\06-security-remediation-and-rebuild.md`

### stage 与源 `www`

独立调用当前 `game2apk.staging._snapshot`，只读取允许的 `F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\www`，没有读取其兄弟目录：

| 项目 | 独立复算 | stage manifest |
|---|---:|---:|
| source 文件数 | 2,524 | 2,524 |
| source bytes | 1,311,499,268 | 1,311,499,268 |
| source snapshot | `7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6` | 相同 |
| copied 文件数 | 2,515 | 2,515 |
| copied bytes | 1,311,391,806 | 1,311,391,806 |
| excluded 文件数 | 9 | 9 |
| excluded bytes | 107,462 | 107,462 |

9 个排除项为 6 个 `.sfk/.sfl` 临时文件和以下 3 个源存档文件：`save/config.rpgsave`、`save/file11.rpgsave`、`save/global.rpgsave`。源目录仍有 3 个存档文件，但没有输出它们的内容或任何 `encryptionKey`。before/after snapshot 完全相同，`sourceUnchanged=true`。

独立 ZIP 对账最终 APK：

- ZIP entries：2,568；`assets/www`：2,517。
- 期望源资产：2,515；生成资产：2 个（`game2apk-config.json`、`js/game2apk-input.js`）。
- missing=0、unexpected=0、未授权 hash mismatch=0。
- 允许修改项 `index.html`=1；ZIP 名称修复=18。
- raw duplicate=0；规范化 expected/actual collision=0。
- `assets/www` 中 save/.rpgsave entries=0；最终 APK 未携带源存档。
- AAB 数为 0（产品 tree、dist、portable、最终 run 均为 0）。

独立 ZIP 审计还复核了 ZIP 无 UTF-8 flag 的中文资产名称；通过 verifier 的规范化路径对账。`src/game2apk/verifier.py` 的 `_stage_asset_check`（约 93–176 行）同时维护 expected/actual collision map，并把任一规范化 collision 纳入 `passed=False`。仓库测试覆盖了 raw duplicate；另有独立内存 ZIP 测试构造“两个不同 raw 名称规范化到同一名称”，结果为 `passed=False`、actual collision detected=True，不依赖当前集合为 0 collision 的偶然性。

### 敏感扫描

扫描范围只包括最终/旧 APK、portable、最终 run、dist；扫描只输出计数，不输出路径中的 secret 值、存档内容或 canary：

| 范围 | 文件数 | forbidden path/file | 常见 secret 模式 | canary | APK | AAB | keystore/JKS | save/.rpgsave |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| portable | 1,129 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| dist | 1,131 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| final run | 10,559 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| final/old APK ZIP 内容及 raw bytes | 2,568 / 2,567 entries | 0 | 0 | 0 | — | — | — | 0 |

扫描的 secret 模式包括 DeepSeek `sk-` 类值、私钥头、常见云 token 形态以及本 QA 的内存 canary；没有真实 DeepSeek 请求。portable 中原始匹配到 3 个 `legacy/joystick` 文本位置，逐一核实为“拒绝旧配置”的 README、源码和负测试，不是把旧快捷键写成当前功能说明。

## 3. P1 安全复核

源码逐项检查：

- `src/game2apk/cli.py:29-50` 在 argparse 前拒绝 `--api-key`、`--password`、`--sign-password` 及等价 raw/value/`=` 形式；错误经 `redact_text` 输出，不回显后续 token。
- 支持来源仅为环境变量名、stdin、隐藏 prompt/getpass；`--api-key-env NAME` 等 argv 只携带变量名。
- `src/game2apk/gui.py:78-80` 的 API key 和签名密码输入均为 `show="*"`，设置值仅在当前进程内存传递。
- `src/game2apk/security.py:57-63,75-127,130-` 提供 secret 值、Bearer、DeepSeek key 脱敏，读取来源校验和 child environment 清理。
- builder 的子进程使用 `shell=False`、清理后的 env、逐行 `redact_text`；signing 使用 `-storepass:env GAME2APK_KEYTOOL_PASSWORD` / `--ks-pass env:GAME2APK_SIGNING_PASSWORD` 这种环境变量名，命令 argv、日志和报告不含密码值，并在子进程返回后清除临时 env 项。

独立 canary harness（未将 canary 写入文件或报告）：

```text
raw cases=9; rejected=9; no echo=9
env=True; stdin=True; getpass/prompt=True
child secret name removed=True
serialized command canary absent=True
redaction output canary absent=True
exit=0
```

独立 DPAPI/keytool 检查从既有 `.state/signing/<applicationId>/password.dpapi` 在内存解保护，未打印密码：DPAPI available=True、protected password+keystore present=True、keytool exit=0、稳定 owner 命中、证书 SHA-256 与最终声称一致、密码未出现在 keytool 输出。portable 未包含 `.state`、keystore、DPAPI 文件或 password 值。

## 4. 输入层最高优先级代码审查

以下文件已逐行读取当前模板版本；括号为本次读取的行数：

```text
InputRootLayout.java (78)
OverlayView.java (589)
OverlayLayout.java (62)
TwoFingerTapGestureStateMachine.java (137)
HeldKeyStateMachine.java (71)
Game2ApkConfig.java (279)
MainActivity.java (240)
RpgInputBridge.java (72)
game2apk-input.js (45)
```

关键静态结论：

1. 历史单指吞事件缺陷已修复。`OverlayView.onTouchEvent` 的游戏区 `ACTION_DOWN` 在 402–410 行明确 `return false`；实际控制区/handle 才进入消费路径。`InputRootLayout.dispatchTouchEvent` 在 33–56 行观察但普通事件继续 `super.dispatchTouchEvent`，因此普通游戏区 DOWN/MOVE/UP/长按保留给 WebView/MV TouchInput。
2. 父级 takeover 只在控制指针、有效全游戏双指或三指识别后发生。`InputRootLayout` 59–76 行只复制一个事件给 WebView，转换 root→WebView 局部坐标、改为 `ACTION_CANCEL`，`finally` 回收；没有递归 dispatch、原始事件重放或重复 dispatch。
3. 双指状态机把控制区、超时、超出 slop、移入控制区、三指全部置为 invalid；只有最后一指 UP 且仍有效时产生一次 `CANCEL` outcome。`OverlayView` 353–356 行只对该 outcome pulse 一次 ESC 27。三指恢复优先路径会 invalid 双指候选，不和双指 cancel 同时成立。
4. `HeldKeyStateMachine` 按 pointer/key 引用计数，独立处理方向 hold/release，取消和 `releaseAll` 不泄漏按键。最终 config 的方向为 37/38/39/40；动作是 confirm=13、cancel=88、esc=27、portrait=65。没有 joystick、W=87、Ctrl=17 或双击取消；系统返回在 `MainActivity:130-135` 映射为 27 pulse。
5. `Game2ApkConfig` 强制 schema=1、`touch.cancelKeyCode=27`、八个固定按钮和严格不重叠布局；最终 APK config 为 `window=250`、`slop=24`、opacity=0.38，严格按钮重叠复算为 False。按钮只有实际命中区进入 control/handle 分支，半透明绘制使用同一布局，最终按钮 key/mode 为 `left/up/down/right=37/38/39/40 hold`，`confirm/cancel/esc/portrait=13/88/27/65 tap`。
6. Overlay 采用宽高归一化坐标，绘制和命中使用同一坐标系，没有硬编码 1024×768 偏移。隐藏、page-not-ready、destroy 路径都会 release：`OverlayView:131,532-587`，`MainActivity:216-222,139-157`。WebView origin 使用 `https://appassets.androidplatform.net/assets/www/index.html`，外部请求和导航被阻断。
7. 最终 stage 生成的 `game2apk-input.js` 与最终 APK `assets/www/js/game2apk-input.js` 字节完全一致；`index.html` 中 `rpg_core.js` 出现 1 次、bridge 出现 1 次且 bridge 在其后。该 bridge 调用 MV `Input._onKeyDown/_onKeyUp`，不包含旧 Ctrl/W 映射。

最终 APK 编译产物中存在 `InputRootLayout`、`OverlayView`、`TwoFingerTapGestureStateMachine`、origin、`releaseAllInput` 等 class/string 证据；DEX 原始 token 不等价于框架运行时行为，不能代替真机。

### 输入回归证据边界

- 现有 Node 回归 exit=0：`mv_input_frame_regression.js` 验证 pulse 在首个 MV `Input.update` 前可见；`mv_touch_regression.js` 验证 letterbox 下第二选项、通过 `$gameTemp.setDestination` 的地图 destination/dash、`Game_Player` 触摸/NPC 路径，以及 `TouchInput.isLongPressed()`/`isRepeated()` 的 raw long press。共 2 个 Node 脚本。
- 额外用最终 stage bridge 本身运行独立 Node fixture，8 个 keycode（四方向+四动作）投递、首帧 pulse、方向 hold/release 均通过，exit=0。
- Java 单元测试覆盖 state machine、配置、方向 hold/release、KeyPulse、三指/控制区/移动/超时等；但没有 Android framework 对 `InputRootLayout`/`OverlayView` 的真实 View dispatch 测试。
- 因此上述 Node/Java 是源码/纯状态机/MV contract 证据，不声明真实 WebView 收到的事件序列、真实画布点击、真实 NPC 交互、真实长按加速或真机多点触摸已经通过。

## 5. 独立测试与构建

### Python/Node

命令：

```text
PYTHONDONTWRITEBYTECODE=1 python game2apk-tool\tests\run_tests.py
```

结果：Python `Ran 22 tests`、`OK`，exit=0；两个 Node 脚本均 exit=0。测试中使用 FakeTransport，没有真实 DeepSeek。

### 隔离 Android Gradle

将干净模板复制到 ASCII QA 临时模板 `F:\code\汉化加转apk\.qa-v2-gradle-template`，设置独立 `GRADLE_USER_HOME=F:\code\汉化加转apk\.qa-v2-gradle-cache`，未在产品模板运行。所有命令都带 `--no-daemon --max-workers=1`：

```text
gradlew.bat --no-daemon --max-workers=1 compileDebugUnitTestJavaWithJavac   exit=0
gradlew.bat --no-daemon --max-workers=1 assembleDebug assembleRelease       exit=0
```

实际产物曾生成 `app-debug.apk` 和 `app-release-unsigned.apk`；QA 完成后只删除了上述临时模板/cache。Gradle 8.11.1 单 worker 没有 worker 环境错误，只有 `android.overridePathCheck` experimental warning 和 MainActivity deprecated API 提示。

独立 JUnitCore 运行全部 6 个测试类、15 个测试：第一次手工 classpath 漏掉 `org.json`，exit=1；加入 Android stub 但顺序不对仍得到 stub failure；最终使用 Gradle 缓存中的 `org.json:json:20240303`（置于 Android stub 前）、JUnit 4.13.2、Hamcrest 和 android.jar 后：

```text
java -cp <main-classes>;<unit-test-classes>;<junit>;<hamcrest>;<org.json>;<android.jar> org.junit.runner.JUnitCore <6 test classes>
OK (15 tests)
exit=0
```

这两个初始 JUnit 失败是独立 runner classpath 错误，修正后全部通过，不是产品测试失败。

### adb 边界

```text
F:\AndroidDev\android-sdk\platform-tools\adb.exe devices
exit=0
List of devices attached
```

设备数为 0。没有下载模拟器、没有 install、没有 uninstall、没有 clear data，也没有声称真机可玩。

## 6. portable 与 GUI

只读使用现有 `F:\code\汉化加转apk\game2apk-tool\dist\portable\game2apk-tool\game2apk-tool.exe`，没有运行会重建/覆盖 portable 的脚本。以下 10 个入口全部 exit=0：

```text
--help
inspect --help
stage --help
patch --help
translate --help
build --help
sign --help
verify --help
gui --help
run --help
```

GUI 用同一个实际 EXE 启动，QA PID=45660：`path_exact=True`、`window_handle_nonzero=True`、`responding=True`、`alive_after_min_3s=True`；随后只停止该精确 PID，`stopped=True`。

产品模板与 portable 模板逐文件 SHA-256 对账（过滤可再生目录/产物）：product=41、portable=41、missing=0、unexpected=0、hash mismatch=0。portable 目录扫描没有 APK/AAB/keystore/JKS/save/.rpgsave/.work/.state、secret 或 canary。

## 7. 严重度清单与封板

### P0

0 项。

### P1

0 项。没有发现会阻断交付的包身份、签名、资源泄漏、raw secret argv、子进程 secret 输出或当前输入源码缺陷。

### P2

- **P2-DEVICE-001：没有真机/模拟器。** 只能判定签名覆盖安装候选，不能验证覆盖安装后的数据保留和实际游戏操作。
- **P2-RUNTIME-INPUT-001：缺少 Android framework/真实 WebView 事件运行证据。** 源码、DEX token、Java 状态机和 Node/MV contract 均通过，但不能把它们等同于真机上的 ACTION_CANCEL、原始单指 WebView 序列、canvas letterbox、NPC、长按文本和方向+动作多点结果。

### P3

0 项产品缺陷。QA 过程中的首次中文父路径 aapt 失败、首次 JUnit 缺 runtime jar、首次临时 PowerShell 参数错误均已在隔离 QA runner 中修正，不属于产品 P3。

最终状态保持 **CONDITIONAL PASS / SIGNED OVERLAY-INSTALL CANDIDATE**，本报告完成后封板，不扩展范围。
