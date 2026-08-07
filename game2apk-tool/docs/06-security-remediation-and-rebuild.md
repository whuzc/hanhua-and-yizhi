# 安全修复、输入层重构与 1.0.1 重建报告

*权威收尾报告｜game2apk-tool｜2026-08-07｜最终候选与最终 run 以本文记录为准*

---

## 🔎 结论与证据边界

最终可交付候选已经生成并通过本地静态门禁：

- 最终 run：fcbb83767c6b47908c67db1f6b05556c
- 最终 APK：F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.1-signed.apk
- SHA-256：ae14a4ffd680dfc93abdced71199176b27ebb933fad5b6884be6f5b6ea893fda
- verification-report.json：passed=true，signatureCandidate=true
- 签名：v2=true、v3=true；证书 SHA-256 为 b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14
- 设备：adb devices 返回 0 台连接设备，因此本文不声称真机已安装、已运行或“可玩”已被真机验证

本文是工作区根目录的唯一权威报告：F:\code\汉化加转apk\docs\06-security-remediation-and-rebuild.md。产品目录内的同名文档只作为同步副本，不得被解释为另一套结果。

前一个实施任务因网络 stream disconnected/systemError 中断，但本地实现、测试和真实构建证据被保留。本次接管没有从头重做，也没有删除旧证据；先复核现有状态，再针对代码审查发现的两个输入阻断缺陷修复并重新走真实流水线。

边界记录如下：

- 只读原游戏输入严格限定为 F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\www。
- 旧失败目录 F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\android 未在本次接管中再次访问、枚举、使用或修改。
- 前序任务曾执行过一次只读容量命令，从原游戏根目录递归枚举；按已有记录，该命令存在可能经过旧 android 的风险，但该操作只读、未修改。本次任务不再重复该访问。
- 旧的 1.0.0 NO-GO APK 保留，未覆盖、卸载或删除。
- 未生成 AAB，未调用真实 DeepSeek，未下载模拟器，未卸载应用，未清空数据。
- 最初接管时的 run 82b0ad2539804d95bcb07efe9e9edbe6 及其证据保留；它在本次代码修复前生成，已被最终 run fcbb83767c6b47908c67db1f6b05556c 明确取代，不作为最终候选依据。

## 🧭 反馈、设计、实现与测试映射

| 真机反馈或风险 | 设计决定 | 当前实现 | 验证证据 |
|---|---|---|---|
| 右侧基础键无效、方向行为不稳定 | 方向键改为独立 hold；动作键改为 tap pulse | 37 左、38 上、39 右、40 下；确认 Enter=13、取消 X=88、ESC=27、立绘 A=65；A 触发 Common Event 25 | Python/Node 回归、Game2ApkConfigTest、KeyActionTest、KeyPulseStateMachineTest、最终 APK 配置 |
| 游戏区单击误变 Enter，ChoiceList 第二项点不到 | 游戏空白区必须穿透到 WebView/MV 原始触摸；只有真实控件命中时 overlay 才消费 | OverlayView 对游戏区初始 ACTION_DOWN 返回 false；控制区命中才拦截；InputRootLayout 只做一次坐标修正后的 MotionEvent 转发 | mv_touch_regression.js：letterbox 下第二项命中并确认 |
| 地图空地不能寻路，NPC 不能交互 | 单指游戏区保持原始 MotionEvent/MV TouchInput 语义 | 选择项、地图 destination/dash、NPC 默认 touch action 均交给 MV；没有把游戏区单击改成 Enter | mv_touch_regression.js：choice、map destination/dash、NPC |
| 双击返回描述不符合实际且容易误触 | 改为双指轻点状态机 | 两指都从游戏区开始且均抬起才触发一次 ESC/cancel；移动、超时、第三指、控制区命中均失格；三指长按恢复 | TwoFingerTapGestureStateMachineTest、OverlayView 静态审查与最终构建 |
| 多点触控可能被控制区和游戏区同时解释 | 控制区命中优先，三指优先恢复，候选取消不可回生 | OverlayView 在 down/move 上检查控制区；任一跟踪指移动到控制区调用 invalidateCandidate；ACTION_CANCEL、释放、隐藏、生命周期均走 releaseAll | 15 项独立 JUnit、InputRootLayout ACTION_CANCEL 路径审查 |
| 单指长按文本需要加速 | 不由 overlay 截断长按 | 游戏区单指不消费，保留 MV TouchInput 的 repeated/long-press | mv_touch_regression.js：show-fast / long press |
| 旧快捷键和摇杆造成歧义 | 收敛到固定八键协议 | 移除摇杆、W=87、Ctrl=17、双击取消；README/手册/portable 当前说明不再把它们写成当前功能 | Python 安全/CLI 文档测试、全树文本检查 |

最终按键合同：

| 控件 | 行为 | Android/MV keyCode |
|---|---|---:|
| 左 | 按住持续，松开立即释放 | 37 |
| 上 | 按住持续，松开立即释放 | 38 |
| 右 | 按住持续，松开立即释放 | 39 |
| 下 | 按住持续，松开立即释放 | 40 |
| 确认 | tap pulse，Enter/OK | 13 |
| 取消 | tap pulse，X/cancel | 88 |
| ESC | tap pulse | 27 |
| 立绘 | tap pulse，Common Event 25 | 65 |
| 游戏区双指轻点 | 两指均抬起后只发一次 cancel/back | 27 |

## 🛡️ P1 凭据安全修复

P1 的目标是避免秘密出现在 raw secret argv、子进程命令行、日志、报告、portable 或 APK 中。

- DeepSeek 凭据只接受环境变量名、stdin 或交互式 getpass；argv 只允许出现变量名，不允许出现 token 值。
- 独立签名密码优先使用对应 applicationId 的 DPAPI 凭据；没有可用凭据时只接受 env-name、stdin 或 getpass。
- GUI 使用掩码输入；秘密只存在当前进程内存，传入子进程时通过短生命周期环境变量，绝不拼入命令行。
- keytool、apksigner、Gradle 子进程均使用清理后的环境；不会继承不必要的 ambient API key。
- SafeArgumentParser 统一拒绝旧的 raw-secret flags，错误文本不会回显 token。
- FakeTransport 覆盖测试不发真实 DeepSeek 请求；中文原游戏按既定策略跳过在线翻译。
- 对最终 run、签名报告、build log、portable、dist 和 APK 做敏感路径/敏感文本扫描：命中 0。DPAPI 状态只保留在既有签名状态目录，密码值未进入报告、日志、dist 或 APK。

## 🔧 P2/P3 修复与安全门禁

### 输入与生命周期

- OverlayView 修复了普通游戏区初始 ACTION_DOWN 被 overlay 错误消费的问题；这是本次接管后发现的真实阻断缺陷。
- TwoFingerTapGestureStateMachine 增加 invalidateCandidate；任一候选指针在移动中命中控制区时，双指候选立即失格。
- 控制区多点、第三指优先、超时/移动失格和游戏区 cancel 只触发一次均由状态机约束。
- HeldKey 在抬指、ACTION_CANCEL、隐藏、page-not-ready、Activity 生命周期变化时释放；releaseAll 是统一收口。
- WebView 使用 WebViewAssetLoader，origin 保持 https://appassets.androidplatform.net/assets/www/index.html；没有 addJavascriptInterface。
- Android 清单没有 INTERNET；应用不是 debuggable；方向保持 sensorLandscape。

### 构建、APK 与 ZIP

- ZIP 名称规范化后，对 expected、actual 和 raw 三组条目显式阻断重复/碰撞；本次 normalizedCollisionCount=0。
- 模板带默认 game2apk_launcher vector icon；最终 aapt 输出为非空 res/ZA.xml。
- stage 只复制 www 的产品资源，排除 9 个 sidecar/save 条目；最终 APK 中没有 save、keystore、secret、AAB 或敏感路径。
- verifier 的 2515 个 expected 资源与 APK 的 2517 个 assets/www 条目一致，额外的 2 个条目正是流水线生成的 game2apk-config.json 和 js/game2apk-input.js；missing、unexpected、hash mismatch 均为 0。
- build log 和 signing-report 明确区分 Gradle 的 signed-in-place 输入与最终签名 APK，未记录密码。

### 文档、工具与证据

- README/手册/portable 的当前功能说明已移除摇杆、W/Ctrl、双击取消和“游戏区单击=Enter”表述；历史 QA 文档 docs/01..05 保留历史说明，不篡改。
- portable 使用当前源码和干净模板重新打包；模板对账逐文件一致。
- 文档中的最终路径、run、hash、证书、版本、设备限制以本报告为准；产品内副本已同步这些最终事实。

## 🧪 命令、结果与退出码

以下是本次接管实际执行的关键命令和结果。路径中的 www 是唯一原游戏输入。

### Python、Node、CLI

~~~powershell
cd /d F:\code\汉化加转apk\game2apk-tool
python tests\run_tests.py
# exit code: 0
~~~

结果：22 个 Python 测试通过；其中包含 2 个 Node/MV 回归：

- MV frame sampling：方向/动作 pulse 在 update 前可见，40ms 后释放
- MV touch：letterbox 选择项、地图 destination/dash、NPC 触摸、原始长按均通过

~~~powershell
python -m compileall -q src tests
# exit code: 0

python scripts\game2apk.py --help
python scripts\game2apk.py inspect --help
python scripts\game2apk.py stage --help
python scripts\game2apk.py patch --help
python scripts\game2apk.py translate --help
python scripts\game2apk.py build --help
python scripts\game2apk.py sign --help
python scripts\game2apk.py verify --help
python scripts\game2apk.py gui --help
python scripts\game2apk.py run --help
# each help invocation exit code: 0
~~~

### Android Java、Gradle、JUnit

~~~powershell
cd /d F:\code\汉化加转apk\game2apk-tool\templates\android-rpgmv
set GRADLE_USER_HOME=F:\code\汉化加转apk\game2apk-tool\.gradle-user-home
gradlew.bat --no-daemon --max-workers=1 compileDebugUnitTestJavaWithJavac
# exit code: 0

gradlew.bat --no-daemon --max-workers=1 assembleDebug assembleRelease
# exit code: 0
~~~

独立 JUnitCore 使用 debug main/test classes、JUnit 4.13.2、Hamcrest 1.3 和 org.json 依赖，运行 6 个测试类共 15 项，结果为 OK (15 tests)，exit code=0：

~~~text
com.game2apk.rpgmv.Game2ApkConfigTest
com.game2apk.rpgmv.HeldKeyStateMachineTest
com.game2apk.rpgmv.KeyActionTest
com.game2apk.rpgmv.KeyPulseStateMachineTest
com.game2apk.rpgmv.OverlayVisibilityStateMachineTest
com.game2apk.rpgmv.TwoFingerTapGestureStateMachineTest
~~~

实际调用形式为：

~~~powershell
java -cp <debug-main-classes>;<debug-test-classes>;<junit-4.13.2>;<hamcrest-core-1.3>;<org.json-20240303> org.junit.runner.JUnitCore com.game2apk.rpgmv.Game2ApkConfigTest com.game2apk.rpgmv.HeldKeyStateMachineTest com.game2apk.rpgmv.KeyActionTest com.game2apk.rpgmv.KeyPulseStateMachineTest com.game2apk.rpgmv.OverlayVisibilityStateMachineTest com.game2apk.rpgmv.TwoFingerTapGestureStateMachineTest
# exit code: 0
~~~

一次使用 F:\AndroidDev\gradle-home 的 Gradle 预检因无法创建 lock file 退出 1；这不是通过项，也不是断言失败。随后改用项目内 .gradle-user-home 重跑，compile 和 assemble 均为 0。此前历史性的 Gradle worker ClassNotFoundException 只作为环境证据保留；本次独立 JUnit 和实际 compile/assemble 结果是 0。

### 真实流水线

~~~powershell
cd /d F:\code\汉化加转apk\game2apk-tool
$env:PYTHONPATH=(Resolve-Path .\src).Path
python .\scripts\game2apk.py run "F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\www" --template .\templates\android-rpgmv --version-code 2 --version-name 1.0.1
# exit code: 0
~~~

实际顺序为 inspect → stage → patch → build → sign → verify → promote。最终 run 目录：

~~~text
F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\fcbb83767c6b47908c67db1f6b05556c
~~~

最终流水线控制台日志：

~~~text
F:\code\汉化加转apk\game2apk-tool\.work\post-input-fix-run-console.log
~~~

对应证据：

- verification-report.json：passed=true、signatureCandidate=true、device.checked=true、connectedCount=0
- stage-manifest.json：expected 2515、copied 2515、excluded 9、sourceUnchanged=true
- build.log：assembleRelease 成功、signed-in-place 证据齐全
- signing-report.json：同一 DPAPI keystore、证书与最终 APK 一致，未含密码

### 独立 APK 工具复核

以下命令均针对 ASCII 临时副本执行，避免工具对中文路径的环境差异；临时副本随后删除，最终 subst 为空：

~~~powershell
aapt dump badging <final-apk>
# exit code: 0
aapt2 dump badging <final-apk>
# exit code: 0
aapt dump permissions <final-apk>
# exit code: 0
aapt dump xmltree <final-apk> AndroidManifest.xml
# exit code: 0
apksigner verify --verbose --print-certs <final-apk>
# exit code: 0
zipalign -c -P 16 -v 4 <final-apk>
# exit code: 0
adb devices
# exit code: 0; connected devices: 0
~~~

独立结果还包括：package、versionCode、versionName、label、icon、SDK、debuggable、INTERNET、v2/v3 和证书均与下文一致。

### portable 与 GUI

~~~powershell
cd /d F:\code\汉化加转apk\game2apk-tool
powershell -ExecutionPolicy Bypass -File .\scripts\build-portable.ps1
# exit code: 0
~~~

portable 顶层 templates、_internal、game2apk-tool.exe；顶层及模板扫描均无 APK/AAB/keystore/save/.work/.state/secret/旧说明文件。portable 中 10 个 help 命令均 exit code=0。GUI 使用打包后的 exe 实际启动，主窗口句柄有效并存活至少 3 秒，随后按精确 PID/路径停止并确认进程已退出。PyInstaller 输出有本机 tkinter.ttk hidden-import 环境警告，但打包 exit=0，GUI 存活验收通过。

最终进程和挂载点复核：

- Java/Gradle/game2apk-tool 遗留进程：无
- subst：无映射
- 本次仅停止了本次启动、路径精确匹配的 portable GUI 进程；没有停止无关进程

## 📦 最终 APK 独立复核

### 交付 APK 与旧 APK

| 项目 | 1.0.1 最终候选 | 1.0.0 旧 NO-GO |
|---|---|---|
| 路径 | F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.1-signed.apk | F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk |
| SHA-256 | ae14a4ffd680dfc93abdced71199176b27ebb933fad5b6884be6f5b6ea893fda | 8ab67d7621cebb479999c45c017c6056580e7cb3f96767227bc92b0e7f428c11 |
| size | 1,283,655,403 bytes | 1,283,655,347 bytes |
| mtime UTC | 2026-08-07T10:59:30.1282081Z | 2026-08-07T08:39:04.0798669Z |
| applicationId | com.game2apk.xianyaoshengcanver22 | com.game2apk.xianyaoshengcanver22 |
| versionCode | 2 | 1 |
| versionName | 1.0.1 | 1.0.0 |
| certificate SHA-256 | b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14 | 相同 |
| v2/v3 | true / true | true / true |

### 最终候选属性

| 属性 | 独立结果 |
|---|---|
| aapt/aapt2 package | com.game2apk.xianyaoshengcanver22 |
| version | versionCode=2，versionName=1.0.1 |
| label | 仙肴圣餐超魔改 Ver22 |
| icon | res/ZA.xml，非空 |
| SDK | minSdk=24，targetSdk=36 |
| debuggable | false |
| INTERNET | 不存在 |
| orientation | sensorLandscape |
| signature | v2=true，v3=true，v1=false，v3.1=false，v4=false |
| certificate | b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14 |
| zipalign | Verification successful |
| APK ZIP entries | 2568 |
| assets/www | 2517 |
| normalized collisions | 0 |
| verifier missing/unexpected/hash mismatch | 0 / 0 / 0 |
| save entries | 0 |
| secret/keystore path or text hits | 0 |
| AAB | 0 |

最终 APK 的文件 mtime 为 2026-08-07T10:59:30.1282081Z；独立 SHA-256 为 ae14a4ffd680dfc93abdced71199176b27ebb933fad5b6884be6f5b6ea893fda。该 hash 与最终 run 的验证报告及 dist 候选一致。

### Stage 与原资源对账

| 项目 | 结果 |
|---|---:|
| www 源文件数 | 2524 |
| www 源字节数 | 1,311,499,268 |
| source before SHA-256 | 7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6 |
| source after SHA-256 | 7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6 |
| sourceUnchanged | true |
| stage copied | 2515 files / 1,311,391,806 bytes |
| stage excluded | 9 files / 107,462 bytes |
| APK assets/www | 2517 |
| pipeline generated | assets/www/game2apk-config.json、assets/www/js/game2apk-input.js |
| missing / unexpected / hash mismatch | 0 / 0 / 0 |
| ZIP normalized collision | 0 |
| ZIP repair count | 18 |
| APK save entries | 0 |

9 个排除项是 6 个 .sfk/.sfl sidecar 和 3 个存档：save/config.rpgsave、save/file11.rpgsave、save/global.rpgsave。原游戏 www 没有被写入；存档未进入 APK。独立 ZIP audit 还确认 raw duplicate、expected duplicate、actual duplicate、敏感路径和敏感文本命中均为 0。

## 🔐 覆盖安装合同与 portable

### 覆盖安装合同

1. 新旧 APK 的 applicationId 相同：com.game2apk.xianyaoshengcanver22。
2. 新 APK versionCode=2 高于旧 APK versionCode=1，versionName 为 1.0.1。
3. 新旧 APK 使用同一证书 SHA-256：b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14。
4. WebView asset origin 不变，应用数据路径和存档策略未改；因此从包身份、签名、版本单调性和 origin 保持方面，静态结论满足 adb install -r 覆盖安装合同。
5. 本次没有执行 adb install -r，因为没有设备；不能把静态兼容结论写成实机安装成功。
6. 交付时不得先卸载、不得清除数据；应在保留手机端数据的前提下执行覆盖安装，并按本报告的方向键、动作键、双指、选择项、地图、NPC、长按路径复验。

### portable

portable 位置：F:\code\汉化加转apk\game2apk-tool\dist\portable\game2apk-tool

- 顶层包含 templates、_internal、game2apk-tool.exe。
- 文件数 1129，目录数 60。
- APK、AAB、keystore、jks、rpgsave、password、api-key、secret 等文件命中 0。
- save、.work、.state、build、.gradle、.gradle-home、dist 等目录命中 0。
- 旧 QA 说明文档命中 0。
- 产品模板与 portable 模板过滤可再生目录后均为 41 个文件，missing/unexpected/hash mismatch 均为 0。
- portable CLI help 和子命令 help 全部 exit code=0。
- GUI 已实际存活至少 3 秒，随后由本次任务停止并确认退出。

portable help 实际调用如下，每条 exit code 均为 0：

~~~powershell
.\dist\portable\game2apk-tool\game2apk-tool.exe --help
.\dist\portable\game2apk-tool\game2apk-tool.exe inspect --help
.\dist\portable\game2apk-tool\game2apk-tool.exe stage --help
.\dist\portable\game2apk-tool\game2apk-tool.exe patch --help
.\dist\portable\game2apk-tool\game2apk-tool.exe translate --help
.\dist\portable\game2apk-tool\game2apk-tool.exe build --help
.\dist\portable\game2apk-tool\game2apk-tool.exe sign --help
.\dist\portable\game2apk-tool\game2apk-tool.exe verify --help
.\dist\portable\game2apk-tool\game2apk-tool.exe gui --help
.\dist\portable\game2apk-tool\game2apk-tool.exe run --help
# each exit code: 0
~~~

重新打包后仅清理了模板中的可再生输出目录：templates\android-rpgmv\.gradle、templates\android-rpgmv\build、templates\android-rpgmv\app\build。没有清理 run、dist 交付物、旧 APK、源资源或签名状态。

## ⚠️ 限制、风险与封板状态

- 没有 Android 真机或模拟器：未执行安装，未声称真机可玩；音频、性能、系统返回、不同厂商触摸分发仍需用户在保留数据的手机上验收。
- 没有调用真实 DeepSeek；中文原游戏按策略不做在线翻译，P1 流程只用 FakeTransport/离线测试。
- 没有生成 AAB、下载模拟器、卸载应用或清空数据。
- 旧 android 目录仍是禁止访问边界；本次接管没有再次访问它。
- run 82 的旧候选和日志保留用于追溯，但因其生成于输入层修复前，不是最终交付对象。
- 当前最终 run 的 verification-report、stage-manifest、build.log、signing-report、最终 APK、portable 和本文已形成可追溯闭环。
- 封板判定：本地静态构建、安全、资源、签名、升级身份和 portable 门禁完成；实机验证保留为交付后的唯一未完成项，不阻断本次静态收尾。

## 📍 证据索引

- 权威报告：F:\code\汉化加转apk\docs\06-security-remediation-and-rebuild.md
- 产品副本：F:\code\汉化加转apk\game2apk-tool\docs\06-security-remediation-and-rebuild.md
- 最终 run：F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\fcbb83767c6b47908c67db1f6b05556c
- 最终控制台日志：F:\code\汉化加转apk\game2apk-tool\.work\post-input-fix-run-console.log
- 最终 APK：F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.1-signed.apk
- 旧 1.0.0 NO-GO APK：F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk
- 签名状态目录：F:\code\汉化加转apk\game2apk-tool\.state\signing\com.game2apk.xianyaoshengcanver22
