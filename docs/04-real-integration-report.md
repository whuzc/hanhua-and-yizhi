# 真实游戏集成与签名 APK 验收报告

_目标：`仙肴圣餐超魔改 Ver22`；执行日期：2026-08-07；报告只记录本机真实运行证据。_

---

> ✅ **结论：** 已生成可侧载的 release 签名静态候选 APK，静态验收通过并提升到明确的 `dist` 路径。
>
> ⚠️ **边界：** 本机 `adb devices` 返回 0 台设备，因此没有安装、启动或真机可玩性证据；本报告不把静态候选称为“真机可玩”。原游戏、私人存档和旧失败目录均未作为输入、模板或产物基础。

## 🎯 范围与交付结果

| 项目 | 已冻结值/结果 |
| --- | --- |
| 原游戏（只读） | `F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22` |
| 工具所有权 | `F:\code\汉化加转apk\game2apk-tool\` |
| 应用名 | `仙肴圣餐超魔改 Ver22` |
| applicationId | `com.game2apk.xianyaoshengcanver22` |
| versionCode / versionName | `1` / `1.0.0` |
| 翻译策略 | 检测为中文主体，跳过 DeepSeek；未提供或调用 API key |
| 构建形式 | release APK；未生成 AAB |
| 最终 APK | `F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk` |
| 最终静态结论 | `passed=true`、`signatureCandidate=true` |
| 最终完整 run 证据区间 | `2026-08-07T08:37:48Z`（stage 创建）至 `2026-08-07T08:39:10Z`（verification report） |

旧失败目录 `F:\code\汉化加转apk\仙肴圣餐超魔改 Ver22\android` 全程不作为模板、输入或输出；最终完整 `run` 的构建工作目录落在 marker 保护的 `game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd\` 下，先前 run 目录也保留为历史证据。

```mermaid
flowchart LR
    accTitle: Real APK delivery flow
    accDescr: Read-only game content moves through a marker-protected staged copy, patched WebView assets, release build, stable signing, static verification, and final dist promotion.

    source_input([Read-only source]) --> marker_stage[Marker stage]
    marker_stage --> patch_www[Patch staged www]
    patch_www --> release_build[Release build]
    release_build --> stable_sign[Stable signing]
    stable_sign --> static_verify[Static verify]
    static_verify --> dist_apk([Promoted APK])

    classDef process fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef success fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d

    class marker_stage,patch_www,release_build,stable_sign,static_verify process
    class dist_apk success
```

## 🔧 已落地的高优先级修复

### 输入脉冲与释放

- `tap`、系统返回和 `mode=tap` 使用 `KeyPulseStateMachine`，按键按下至少跨过一次 MV `Input.update` 采样窗口，40 ms 后再释放。
- `mode=hold` 保持到松手；取消、销毁、页面切换和隐藏均释放 held/pulse 输入。
- `RpgInputBridge` 在 WebView 页面未 ready 或销毁时清空按键集合。
- Java `KeyPulseStateMachineTest` 和 Node `mv_input_frame_regression.js` 均模拟 MV 帧采样；最终均退出码 0。

### MV 文本提取与启发式

- 101 后连续 401 被合并为普通对话正文；可选第五参数只作为 `speaker-name`，不再作为唯一正文来源。
- 105 后连续 405 被提取为滚动文本。
- 真实目标有效统计：`message` 条目 `10,911`，正文段 `19,612`，`scroll-text` 条目/段均为 0；不再出现 `message=0`。
- 统计平假名和片假名占比；中文主体中少量假名不触发第三方翻译。本目标检测结果为 `recommendSkipTranslation=true`、`liveApiUsed=false`。

### 安全边界与真实集成

- 构建前严格校验 `.work/<project-id>/runs/<run-id>/staged/www`、marker、project/run、manifest 归属和路径边界；恶意伪造 manifest 回归证明外部 `android` 哨兵不变。
- 源快照包含 `save/` 和私人存档；复制阶段排除存档、`.sfk`、`.sfl` 和临时文件，且完整源快照保持一致。
- Activity 使用 `sensorLandscape`；输入控件仍按归一化坐标和 1024×768 逻辑分辨率工作，未把 816×624 当作硬编码事实。
- icon 参数保留时会复制图标并注入 `android:icon`；GUI 暴露正整数 `versionCode`。
- 首次签名在 Windows DPAPI 可用时自动生成强密码，并稳定复用同 applicationId 的 release keystore；密码不进入命令行、日志、报告、APK 或 `dist`。
- verifier 显式核验无 INTERNET、关键资源、stage/APK 资源对账、ZIP 对齐、签名 schemes、证书 SHA-256 和新鲜度。

## 🔍 源文件与暂存证据

### 源项目检查

只读 inspect 退出码为 0，识别到 RPG Maker MV 1.6.1；YEP_CoreEngine 把有效逻辑分辨率解析为 1024×768，MV 默认值 816×624 仅作为对照。原始 `www` 共 2,524 个文件、1,311,499,268 bytes；加密图片和音频保持原样，未执行解密或 DRM 绕过。

### 完整快照

| 证据 | 数值 |
| --- | ---: |
| 源文件数 | 2,524 |
| 源字节数 | 1,311,499,268 |
| 暂存复制文件数 | 2,515 |
| 暂存复制字节数 | 1,311,391,806 |
| 排除文件数 / 字节数 | 9 / 107,462 |
| 暂存前完整快照 SHA-256 | `7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6` |
| 暂存后源完整快照 SHA-256 | `7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6` |
| 暂存后 staged 快照 SHA-256 | `fc4bf977e6c345b2173a2cf8501553d551c5d40b861f3d3fb7b4ca65a27d7b98` |
| stage `sourceUnchanged` | `true` |
| 结束独立完整快照 | 2,524 / 1,311,499,268 bytes |
| 结束独立快照 SHA-256 | `7b2fbe678c9d3e17e242be1ab1918c203c134514f825bab86a446085e56d6bf6` |
| 开始/结束快照是否相同 | `true` |

最终暂存 manifest：`F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd\stage-manifest.json`；创建时间 `2026-08-07T08:37:48Z`。

### 被排除文件清单

下表只列路径、大小和 SHA-256，不输出任何存档或二进制内容。完整结构化记录也保存在上述 `excludedFiles` 字段中。

| 路径 | bytes | SHA-256 |
| --- | ---: | --- |
| `audio/se/HSE_lick.ogg.sfk` | 896 | `8f8761f99ac72f1ee7536c03e48e8953cbd13a9e66a8b874e0239c7e1f7e0e73` |
| `audio/se/HSE_lick.ogg.sfl` | 34 | `034518460f76c2df666b07679bd958072fe7f0e06d6de13237c15efe84f17d4f` |
| `audio/se/Hkouka_kosuru.ogg.sfk` | 1,428 | `8062a886a836d36e414f41578f6b621d1d2a379dbc2e52161b2d62d2d8139f49` |
| `audio/se/Hkouka_kosuru.ogg.sfl` | 38 | `5cc19e5c0126065f258d0a566feefd18397a2f552e8fc502b9216d51999f3a7b` |
| `audio/se/Hkouka_kuchu.ogg.sfk` | 1,500 | `54e8f2c338e82ddf1329a45bdce002a4e03e897d9bba1cafe49b26c51e9e29bc` |
| `audio/se/Hkouka_kuchu.ogg.sfl` | 38 | `fb6baad5a3dade894da045b591b215126cecd0467d26b7cf56d85e527412817b` |
| `save/config.rpgsave` | 272 | `7b55877894749b5e007114c76e0d7c2de2b2f26a74d056feffaeab1a6d54e299` |
| `save/file11.rpgsave` | 101,812 | `82e8eff702f0e6de9dfde4faf9115f2ebd2f31281d2a9c7cc1b5e36267409c9f` |
| `save/global.rpgsave` | 1,444 | `c6a5decba7882879c550d26a486b6c134ee3b99876ddc29ab7541bf810432fb8` |

## 🧪 命令与回归退出码

| 命令/阶段 | 退出码 | 证据与说明 |
| --- | ---: | --- |
| 只读 `inspect` | 0 | MV 1.6.1、1024×768、2,524 文件 |
| `tests/run_tests.py`（Python 16 项 + Node） | 0 | 最终回归通过 |
| Gradle `testDebugUnitTest assembleDebug assembleRelease`（ASCII `subst`、`--no-daemon`） | 0 | 模板 debug/release 编译通过 |
| 最终 Gradle `testDebugUnitTest`（ASCII `subst`、`--no-daemon`、单 worker） | 0 | Java 输入脉冲回归通过 |
| 最终完整真实 `run` | 0 | `inspect → stage → patch → build → sign → verify → promote`；run=`905b63d19c0b42e89019264541dac1dd` |
| 其中 Gradle `assembleRelease` | 0 | `--no-daemon`、ASCII `subst` 映射、隔离 `.work\gradle-home` |
| 其中真实 `sign` | 0 | DPAPI 状态和稳定 release keystore 可用，密码未暴露 |
| 其中静态 `verify` + adb 检查 | 0 | `passed=true`，无设备但检查正常返回 |
| 其中验收证据落盘 + promote | 0 | `verification-report.json` 生成，dist APK 已更新 |
| 最终 `build-portable.ps1` | 0 | 含测试、PyInstaller、干净 Android 模板 |
| 便携 EXE `--help` | 0 | CLI 冒烟通过 |
| 便携 EXE `gui` | 0 | 进程启动并保持 3 秒，随后由冒烟脚本结束 |
| `adb devices` | 0 | 连接设备数 0 |
| 最终 `subst` 查询 | 0 | 无残留映射 |

以下失败也保留在工作证据中，没有被改写成成功：第一次真实 `run` 在旧假名阈值下安全要求第三方确认并退出 2，未调用 DeepSeek；第一次构建因渲染器误把 noCompress 追加到 `settings.gradle` 退出 2（底层 Gradle 1）；一次完整 cache 复制因 Windows 长路径退出 2。修复后由最终完整 `run` 从 marker 暂存副本完成 build/sign/verify/promote。

## 📦 APK 静态验收

### 交付文件

| 属性 | 实测值 |
| --- | --- |
| 绝对路径 | `F:\code\汉化加转apk\game2apk-tool\dist\仙肴圣餐超魔改-Ver22-1.0.0-signed.apk` |
| bytes | `1,283,655,347` |
| mtime UTC | `2026-08-07T08:39:04.0798669Z` |
| SHA-256 | `8ab67d7621cebb479999c45c017c6056580e7cb3f96767227bc92b0e7f428c11` |
| 新鲜度 | `fresh=true`，相对最终 build 时间戳通过 |
| AAB | 未生成 |

### aapt、资源和权限

- `aapt dump badging`：package `com.game2apk.xianyaoshengcanver22`、versionCode `1`、versionName `1.0.0`、label `仙肴圣餐超魔改 Ver22`。
- `minSdk=24`、`targetSdk=36`，`debuggable=false` 且已检查；aapt 命令退出码 0。
- 关键资源存在：`assets/www/index.html`、`assets/www/js/rpg_core.js`、`assets/www/js/game2apk-input.js` 和 `assets/game2apk/config.json`；未发现 `assets/www/save/` 或 `.rpgsave`。
- stage/APK 对账：expected 2,515、actual 2,517；额外的正是 `assets/www/game2apk-config.json` 和 `assets/www/js/game2apk-input.js`；`index.html` 是允许的 patched 文件；missing、unexpected、hashMismatches 均为空。
- APK 中有 18 个非 ASCII ZIP 名称需要 CP437→UTF-8 可逆归一化，对账后仍为 0 missing/0 unexpected，不代表资源丢失。
- `aapt dump permissions` 退出码 0，`android.permission.INTERNET` 未出现，`internet=false`。

### 对齐、签名和稳定密钥

- `zipalign -c -v 4` 退出码 0，`Verification successful`。
- `apksigner verify --verbose --print-certs` 退出码 0：v2 `true`、v3 `true`，release 证书 SHA-256 为 `b3251d9ea67d2a643e8a17d85373ecb5dfcc6117f9432a6eb831a41121d51f14`，RSA 2048 bit。
- 稳定 keystore：`F:\code\汉化加转apk\game2apk-tool\.state\signing\com.game2apk.xianyaoshengcanver22\release.keystore`。
- DPAPI 保护的密码材料仅在 `.state/signing/<applicationId>/password.dpapi`；密码没有进入日志、报告、APK 或 `dist`。
- 所有构建子进程退出后，`subst` 清理返回码 0 且查询为空。

最终验收报告证据：`F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd\verification-report.json`；Gradle 日志：`F:\code\汉化加转apk\game2apk-tool\.work\project-985104049149f920\runs\905b63d19c0b42e89019264541dac1dd\build.log`；报告生成时间 `2026-08-07T08:39:10Z`。

## 🧰 便携包与 GUI 验收

最终便携目录为 `F:\code\汉化加转apk\game2apk-tool\dist\portable\game2apk-tool`，其中模板默认路径 `templates\android-rpgmv` 存在。扫描结果为：

- `build`、`.gradle`、`.gradle-home`、`.work`、`.state`、`dist` 目录：0 个
- APK、AAB、keystore、JKS、password、API key、`.rpgsave` 文件：0 个
- EXE `--help`：退出码 0
- EXE `gui`：启动后存活 3 秒，冒烟脚本退出码 0

直接使用当前 hermes Python 创建 Tk 根窗口曾因环境缺少 `init.tcl` 失败；便携 EXE 自带 `_tcl_data`/`_tk_data`，实际 GUI EXE 启动冒烟已通过。该环境差异不影响便携交付，但记录在此以免把两种运行时混为一谈。

## ⚠️ 未验证边界与封板状态

- 无已连接 adb 设备或模拟器；没有下载模拟器，没有执行安装，没有声称能进入游戏或可玩。
- 目标启用插件中存在 RPG Maker NW/Node 依赖风险；本次只完成 Android/WebView 静态打包与签名验收，真实运行兼容性仍需后续真机证据。
- 加密 `.rpgmvp`、`.rpgmvo` 等资源被原样复制并通过哈希/资产清单对账；没有解密、提取密钥或绕过 DRM。
- DeepSeek 未调用，未提供 API key；本目标默认跳过翻译。
- 源游戏和个人存档未修改；旧 `android` 目录未触碰；仅清理了模板中由 Java/Gradle 回归生成的明确可再生 `app/build`、根 `build/reports` 和 `.gradle`，真实 `.work` 构建证据保留。

本任务已封板：交付物是上述 signed APK 和本报告，后续只应在获得真机连接后进行安装/启动验证，不继续扩大本次范围。
