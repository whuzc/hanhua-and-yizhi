# 独立 QA / 审查报告（第 5 份）

日期：2026-08-07（Asia/Hong_Kong）  
范围：只读审查、验证命令、隔离测试；未修复产品代码，未重签名或替换最终 APK。

## 结论

结论：**FAIL / NO-GO**。

- 静态 APK 结论：最终 APK 是一个可独立静态验收、可侧载候选；包名、版本、签名、V2/V3、对齐、核心资源、无存档、stage 对账均通过。
- 真机结论：adb devices 返回 0 台设备/模拟器；没有安装、没有下载模拟器、没有声称“真机可玩”。因此不能把本报告当作真机可玩验收。
- 阻断原因：发现 1 项 P1 安全问题——CLI 接受签名密码/API key 作为命令行参数，存在进程列表、命令历史或审计记录泄露凭据的路径。当前最终 APK、run 报告、build.log 和 dist 扫描未发现实际明文密码，但代码接口本身违反本任务的凭据边界。
- 未发现 P0；因此即使修复 P1，仍需另行决定是否做真机和输入帧级验收。

## 1. 输入、证据和隔离边界

已完整阅读并独立复算以下既有材料，不直接采信其结论：

- F:\code\汉化加转apk\docs\01-compatibility-audit.md（231 行）
- F:\code\汉化加转apk\docs\02-architecture-and-acceptance.md（158 行）
- F:\code\汉化加转apk\docs\03-chief-architect-review.md（57 行）
- F:\code\汉化加转apk\docs\04-real-integration-report.md（185 行）
- F:\code\汉化加转apk\game2apk-tool\README.md（62 行）
- F:\code\汉化加转apk\game2apk-tool\templates\android-rpgmv\README.md（98 行）

本次固定输入：

- 产品：F:\code\汉化加转apk\game2apk-tool
- 只读源：F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22
- 禁止使用的旧失败目录：F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\android；本次未访问、未修改；代码/关键证据中精确旧路径搜索为 0 命中。
- 最终 APK：F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk
- 最终 run：F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd

工具：JDK 21.0.11、Node.js、Python C:\Users\24713\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe、Android SDK Build Tools 36.1.0（另以 verifier 发现的 37.0.0 复核）。aapt 直接处理中文绝对路径时退出 1 并报告 Illegal byte sequence；因此只将最终 APK 复制到我创建的 ASCII 临时路径做工具输入，并验证字节/哈希完全一致。该临时目录已在封板前删除，未替换最终 APK。

## 2. 最终 APK 身份、签名和包格式

独立命令及结果：

~~~powershell
Get-Item -LiteralPath 'F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk'
Get-FileHash -Algorithm SHA256 -LiteralPath 'F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk'
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt.exe dump badging <ASCII-QA-copy> ; exit 0
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt2.exe dump badging <ASCII-QA-copy> ; exit 0
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt.exe dump permissions <ASCII-QA-copy> ; exit 0
F:\AndroidDev\android-sdk\build-tools\36.1.0\aapt.exe dump xmltree <ASCII-QA-copy> AndroidManifest.xml ; exit 0
F:\AndroidDev\android-sdk\build-tools\36.1.0\apksigner.bat verify --verbose --print-certs <ASCII-QA-copy> ; exit 0
F:\AndroidDev\android-sdk\build-tools\36.1.0\zipalign.exe -c -v 4 <ASCII-QA-copy> ; exit 0
~~~

独立复算值：

| 项目 | 实际值 | 结论 |
|---|---:|---|
| 文件大小 | 1,283,655,347 bytes | 与 run APK 相同 |
| dist 最后写入 UTC | 2026-08-07T08:39:04.0798669Z | 记录 |
| dist 创建 UTC | 2026-08-07T08:26:36.8717108Z | 记录 |
| APK SHA-256 | 8ab67d7621cebb479999c45c017c6056580e7cb3f96767227bc92b0e7f428c11 | 与集成声称相同 |
| run APK 大小 / SHA-256 / mtime | 1,283,655,347 / 同上 / 同一 UTC mtime | 与 dist 字节、哈希完全相同 |
| package | com.game2apk.xianyaoshengcanver22 | 通过 |
| versionCode / versionName | 1 / 1.0.0 | 通过 |
| label | 仙肴圣餐超魔改 Ver22 | 通过 |
| launchable activity | com.game2apk.rpgmv.MainActivity | 通过 |
| compile / min / target SDK | 36 / 24 / 36 | aapt/aapt2 一致 |
| orientation | sensorLandscape / landscape feature | 通过 |
| android:debuggable=true | 未发现；aapt badging marker 为 0，XML tree 无该属性 | release 非 debuggable |
| INTERNET 权限 | aapt dump permissions 仅输出 package 行，无 INTERNET | 通过 |
| v1 / v2 / v3 / v4 | false / true / true / false | 通过 |
| 证书 DN | CN=com.game2apk.xianyaoshengcanver22, OU=game2apk-tool | 通过 |
| 证书 SHA-256 | b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14 | 与集成声称相同 |
| 签名算法 / 密钥 | RSA 2048 | 通过 |
| ZIP 4-byte 对齐 | Verification successful | 通过 |

XML tree 同时确认 allowBackup=false、usesCleartextTraffic=false、硬件加速和配置变化声明。最终 APK 的 application icon 字段为 icon=''，见 P2-APK-001；这不影响上述静态包格式检查。

## 3. APK ZIP、资源对账和安全内容

独立 Python zipfile 审计使用 ZipInfo.flag_bits、CP437-to-UTF-8 规范化、逐文件 SHA-256；退出码 0。结果：

| 检查 | 实际值 |
|---|---:|
| ZIP entry 总数 | 2567 |
| assets/www 文件 entry | 2517 |
| stage manifest 期望源文件 | 2515 |
| 生成文件 | 2 |
| missing | 0 |
| unexpected（排除 2 个生成文件后） | 0 |
| 原始非 ASCII asset 名称 | 18 |
| 非 ASCII 名称中缺 UTF-8 flag | 18 |
| 规范化后名称数 | 2517 |
| 规范化名称碰撞 | 0 |
| 敏感路径命中（save、rpgsave、keystore 等） | 0 |
| 敏感文本命中（DeepSeek URL/key、私钥标记、store/key password） | 0 |

两个受控生成文件精确为：

- assets/www/game2apk-config.json
- assets/www/js/game2apk-input.js

严格哈希对账不是“模糊放行”：原始 stage 文件中只有 1 项差异：

| 文件 | stage 期望 | APK 实际 | 判定 |
|---|---|---|---|
| index.html | 1690 bytes，e40ef308a0d51304aa36bfbe43449787687c4a50af81cafc7f687905f1ff6d34 | 1766 bytes，a8ce7023aeda6898d3349caaa33c4c4d795779f821ca582682b598c43ceda4f9 | 唯一、明确受控的 bridge 注入差异 |

因此 raw hash mismatch 为 1、允许 mismatch 为 1、未授权 mismatch 为 0。verifier 报告中的 modifiedAllowed=["index.html"] 与此一致；它没有把该允许差异重复列入 hashMismatches，独立审计已补足这项可见性。

18 个日文/非 ASCII 名称的原始 ZIP 标志缺 UTF-8 flag，但其 CP437 解码结果可逐一无碰撞地反解为 UTF-8 名称；产品 verifier 使用同等 _normalize_zip_name 规则，当前 APK 对账完整。这是当前文件集下合理且可证明的规范化，不是无条件放行；代码尚未对未来规范化碰撞做显式阻断，列入 P2-ZIP-001。

assets/www/data/System.json 确实包含 MV 的 hasEncryptedImages、hasEncryptedAudio、encryptionKey 元数据。只记录“键存在”，没有输出值；它是游戏资源解密元数据，不是 DeepSeek/API key 或 Android signing keystore。APK 中未发现 save、.rpgsave、私钥、keystore、API key 或凭据字符串。

## 4. 源树、stage manifest 和存档隔离

独立 Python 全树快照（逐文件 SHA-256，未输出存档内容）退出码 0：

| 项目 | manifest | 独立复算 |
|---|---:|---:|
| 源文件数 | 2524 | 2524 |
| 源字节数 | 1,311,499,268 | 1,311,499,268 |
| 源快照 before | 7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6 | 相同 |
| 源快照 after | 7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6 | 相同 |
| sourceUnchanged | true | before/after 相等 |
| 纳入复制文件 | 2515 / 1,311,391,806 bytes | 相同 |
| 排除文件 | 9 / 107,462 bytes | 相同集合 |
| manifest staged snapshot | fc4bf977e6c345b2173a2cf8501553d551c5d40b861f3d3fb7b4ca65a27d7b98 | 从 copiedFiles 重建相同 |

9 项排除集合（仅路径、大小、哈希，不输出内容）：

| 路径 | bytes | SHA-256 |
|---|---:|---|
| audio/se/Hkouka_kosuru.ogg.sfk | 1428 | 8062a886a836d36e414f41578f6b621d1d2a379dbc2e52161b2d62d2d8139f49 |
| audio/se/Hkouka_kosuru.ogg.sfl | 38 | 5cc19e5c0126065f258d0a566feefd18397a2f552e8fc502b9216d51999f3a7b |
| audio/se/Hkouka_kuchu.ogg.sfk | 1500 | 54e8f2c338e82ddf1329a45bdce002a4e03e897d9bba1cafe49b26c51e9e29bc |
| audio/se/Hkouka_kuchu.ogg.sfl | 38 | fb6baad5a3dade894da045b591b215126cecd0467d26b7cf56d85e527412817b |
| audio/se/HSE_lick.ogg.sfk | 896 | 8f8761f99ac72f1ee7536c03e48e8953cbd13a9e66a8b874e0239c7e1f7e0e73 |
| audio/se/HSE_lick.ogg.sfl | 34 | 034518460f76c2df666b07679bd958072fe7f0e06d6de13237c15efe84f17d4f |
| save/config.rpgsave | 272 | 7b55877894749b5e007114c76e0d7c2de2b2f26a74d056feffaeab1a6d54e299 |
| save/file11.rpgsave | 101812 | 82e8eff702f0e6de9dfde4faf9115f2ebd2f31281d2a9c7cc1b5e36267409c9f |
| save/global.rpgsave | 1444 | c6a5decba7882879c550d26a486b6c134ee3b99876ddc29ab7541bf810432fb8 |

源 save/ 独立发现 3 个 .rpgsave，总计 103,528 bytes；当前 staged tree 为 2517 文件、1,311,393,337 bytes，save/.rpgsave 数为 0；最终 APK ZIP save 命中为 0。源文件未被删除，存档内容未输出。

证据：

- F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd\stage-manifest.json
- F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\www

## 5. run、验证、promote 和旧路径检查

最终 run 中以下证据均存在：

- stage-manifest.json：423,461 bytes
- build.log：2,840 bytes
- verification-report.json：18,087 bytes
- verification report：passed=true、signatureCandidate=true、device.connectedCount=0

build.log 第 63、66、67 行分别显示 :app:assembleRelease、BUILD SUCCESSFUL in 55s、42 actionable tasks。第 49 行的 S:\runs\... 是 ASCII subst 工作路径，不是旧失败 ...\仙肴圣餐超魔改 Ver22\android；关键证据精确旧路径命中为 0，当前 subst 状态为空。

代码顺序独立复核：cli.py:157-174 为 inspect → stage → patch → build → sign → verify → promote；pipeline.py:85-103 只有 verification 返回后才调用 promote。当前 run APK 与 dist APK 的大小、mtime、SHA-256 全部相等，且已对最终 dist 字节副本独立执行 aapt、apksigner、zipalign，因此当前 promote 产物确实是已验证内容。

独立 AAB 扫描：在 game2apk-tool 与 docs 递归查找 .aab，数量 0；本项目未生成 AAB。

## 6. Python、Node、Android、portable 和 ADB 验证

### Python / Node

~~~powershell
& 'C:\Users\24713\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe' 'F:\code\汉化加转apk\game2apk-tool\tests\run_tests.py'
~~~

退出码 0；Python unittest 16 项通过，Node MV frame sampling regression 通过。compileall 对 src 和 tests 退出码 0；生成的 pycache 只在 QA 临时目录，已清理。

### 隔离 Android 模板

干净复制 templates/android-rpgmv 到我自己的临时目录，以 ASCII subst T: 执行；没有以产品模板作为 Gradle 工作目录。

~~~powershell
T:\gradlew.bat --no-daemon --max-workers=1 compileDebugUnitTestJavaWithJavac
T:\gradlew.bat --no-daemon --max-workers=1 assembleDebug assembleRelease
~~~

- compileDebugJavaWithJavac：退出 0。
- compileDebugUnitTestJavaWithJavac：退出 0。
- 独立 java -cp ... org.junit.runner.JUnitCore ...：JUnit 4.13.2，14 tests，OK，退出 0。
- assembleDebug assembleRelease：BUILD SUCCESSFUL，退出 0。
- Gradle 原生 testDebugUnitTest 尝试退出 1，错误为本机 Gradle test worker 启动时 ClassNotFoundException: worker.org.gradle.process.internal.worker.GradleWorkerMain；同一隔离模板的 test 编译和直接 JUnit 14 项已通过，故将其记录为本机 Gradle worker/缓存启动问题，不伪造为 Gradle test task 通过。
- C:\ 临时 Gradle cache 曾在 JDK ZipFS 关闭 JAR 时返回 AccessDeniedException；改用已存在的可写 Gradle cache 后编译/assemble 通过。没有因此修改产品 Java、模板源、最终 APK。

QA 创建的 ASCII APK、模板、cache、GUI 日志和构建目录已清理；清理后 QA 临时目录不存在、subst 为空、portable 进程数为 0。

### portable EXE

目标：F:\code\汉化加转apk\game2apk-tool\dist\portable\game2apk-tool\game2apk-tool.exe

- game2apk-tool.exe --help：退出 0，命令列表完整。
- verify --help：退出 0；sign --help：退出 0。
- GUI：通过 cmd.exe /d /c start ... game2apk-tool.exe gui 启动，launch exit 0；进程实际存在且 Responding=true，QA 等待至少 3 秒后按 PID 结束。不是“进程启动失败后写通过”。
- portable 包：1128 files、59 directories；顶层仅 templates、_internal、game2apk-tool.exe；模板 40 文件与产品模板逐文件大小/SHA-256 一致。
- portable 内无 .apk、.aab、.keystore、.jks、.rpgsave、save 目录、.work、.state、build/gradle 输出；敏感文本扫描 0 命中。

独立 portable verify --apk <ASCII-QA-copy> --application-id com.game2apk.xianyaoshengcanver22 --version-code 1 退出 0，报告 passed=true、signatureCandidate=true，且无设备原因明确为 no Android device or emulator available。没有执行 standalone sign，因为对最终 APK sign 会违反本任务的“不重签名”边界；只验证了工具链帮助和 verifier。

### ADB

~~~powershell
F:\AndroidDev\android-sdk\platform-tools\adb.exe devices
~~~

退出码 0，输出只有 List of devices attached，连接数 0。未安装 APK、未创建/下载模拟器、未声称真机可玩。

## 7. 代码审查结果

### 输入、触摸和生命周期

审查范围：

- templates/android-rpgmv/app/src/main/java/com/game2apk/rpgmv/KeyPulseStateMachine.java
- .../OverlayView.java
- .../MainActivity.java
- .../RpgInputBridge.java
- .../TapGestureStateMachine.java
- .../JoystickStateMachine.java
- .../OverlayVisibilityStateMachine.java

静态映射和测试结果：

- Enter 13：单击 tap 走 pulse；Esc 27：双击立即 pulse，系统返回第一次 Cancel pulse、第二次在窗口内退出。
- A/W 65/87：tap；Ctrl 17：hold，抬起/取消释放；方向 37/38/39/40：独立 pointerId 的四/八方向摇杆状态机。
- KeyPulseStateMachine 立即发 keyDown，至少 40ms 后 keyUp；重叠 pulse 合并计数，releaseAll 取消 callback 并释放全部 key。
- 多点 pointer、button hold、隐藏手柄、三指长按恢复、窗口隐藏/恢复、detach/destroy 释放路径存在；RpgInputBridge.setPageReady(false) 也调用 release。
- Java 14 项、Node 的“down 在 update 前可见、40ms 后 up”回归通过。

限制：40ms 是时间下界，不是 WebView/MV Input.update 的帧确认；测试使用模拟调度器和最小 VM，不能证明真实设备卡顿、启动时序或 MV 帧边界。它满足当前实现的 bounded-minimum-duration 设计，但真机/帧级结论仍未验证，列为 P2-INPUT-001，不把静态测试写成真机通过。

### WebView、离线和安全设置

MainActivity.java 使用 WebViewAssetLoader，入口为 https://appassets.androidplatform.net/assets/www/index.html；关闭 file/content access、file URL 跨域、universal access 和 mixed content，使用横屏，导航/外链被拦截。addJavascriptInterface 在源码/模板中无命中；输入通过受控 evaluateJavascript，不是 JavaScript interface。manifest 无 INTERNET，cleartext 为 false。

### 101/401、105/405、说话人、占位符和语言启发式

对只读源独立提取结果：

- 安全条目总数 15,777；message 10,911 条、message segments 19,612；choice 454；database-field 4,319；skip recommendation=true。
- 原始 JSON 命令统计：101/401 为 10,912/19,613；105/405 为 0/0；101 第五参数说话人值为 0。提取器输出 message 10,911、scroll-text 0、speaker-name 0；即代码覆盖 101→401、105→405 和说话人分支，但本游戏样本没有 105/405 或第五参数说话人条目。
- 占位符条目 10,179，placeholder token 总数 20,742；未输出原文。
- 日文 kana/CJK 判定位于 translation.py:288-301；当前项目被正确建议跳过翻译。
- FakeTransport 位于 translation.py:418，测试使用 FakeTransport 和缓存；本次没有调用 DeepSeekTransport、没有真实 API 请求、没有输出 API key。

### stage、marker、rmtree 和安全快照

staging.py 对 source snapshot 包含存档、复制阶段只排除已列规则；security.py/marker/rmtree 路径校验和恶意路径测试随 Python 回归通过。verifier.py 对 required assets、save、生成文件和 index patch 做检查。当前实际 source/stage/APK 对账如第 3、4 节所列，无实际存档进入 APK。

### DPAPI、证书、凭据和 toolchain

- password.dpapi 仅由 Windows DPAPI 保护；独立解密只在内存中用于比对，未输出密码值。
- keytool -list -v -storepass:env ... 退出 0；alias game2apk，Owner 与 APK DN 一致，SHA-256 与 APK 证书一致；密码未出现在 keytool 输出。
- 对 run 的 build.log、stage/verification JSON、run APK、dist APK 和 dist 文本证据的实际 DPAPI 密码扫描命中 0。
- 但是 CLI 暴露 translate --api-key、sign --password、run --api-key、run --sign-password；见 src/game2apk/cli.py:77,87,104-105。这是代码级命令行凭据泄露面，即使本次落盘证据扫描为 0，仍构成 P1。

### versionCode、icon、完整 run 和模板

GUI 有正整数 versionCode Spinbox，config.py:52-60 也限制 1..2,147,483,647；本次最终 aapt 实值为 1。icon 是可选参数，builder.py:278-303 支持注入，但本次 config 未提供 icon，最终 aapt 明确报告 icon=''。完整 run 的 verify→promote 顺序和最终哈希一致性已在第 5 节复核。

## 8. P0/P1/P2/P3 清单

### P0

无。

### P1

- **P1-SEC-001：凭据可经命令行传入。** --password、--sign-password、--api-key 会把 signing password/API key 放进进程命令行，可能被进程枚举、shell history 或审计采集；这违反本任务的命令行凭据边界。当前最终 artifact 扫描为 0 命中，不能抵消代码级暴露面。此项使结论必须为 FAIL/NO-GO。

### P2

- **P2-APK-001：最终 APK 没有 application icon。** aapt 两套输出均为 icon=''；构建器虽支持可选 icon，但本次最终产物没有注入。影响安装器/桌面体验，不改变签名和核心静态验收。
- **P2-INPUT-001：真实 MV 帧/设备输入仍未证实。** 40ms pulse、pointer 释放、隐藏恢复和测试均通过，但没有 WebView/MV 帧确认，也没有 adb 设备；不能据此宣称实际可玩。
- **P2-ZIP-001：规范化碰撞是代码硬化缺口。** 当前 18 个 raw 非 ASCII 名称规范化后 0 碰撞、对账完整；verifier 仍应显式拒绝未来发生的规范化重名，而不是仅依赖当前集合无碰撞。

### P3

- **P3-DOC-001：模板 README 测试数量陈旧。** README 声称 12 个 JVM 测试；独立 JUnitCore 实际运行 14 项，Python/Node 总回归另为 16 项 Python tests 加 Node 检查。
- **P3-EVIDENCE-001：build.log 使用 S: ASCII 映射且 APK 文件名仍为 app-release-unsigned.apk。** 这是中文路径兼容和 signed-in-place 工具链造成的审计可读性问题；独立 apksigner 已证明最终字节为 V2/V3 signed，且没有引用旧 android 目录。
- **P3-TOOL-001：aapt 直接处理中文绝对路径会失败。** 当前 pipeline 通过 ASCII subst 规避，最终 APK 本身已用 ASCII 副本通过 aapt/aapt2；这是工具调用约束，不是当前 APK 内容失败。

## 9. 封板交接

本次没有修复、没有删除真实证据、没有修改源游戏/存档、没有重签名或替换 dist APK。唯一应保留的本次交付物是本报告：F:\code\汉化加转apk\docs\05-independent-qa.md。后续若继续，先处理 P1-SEC-001，再由总设计师决定是否开真机输入/可玩性验证；本 QA 任务到此封板，不扩范围。
