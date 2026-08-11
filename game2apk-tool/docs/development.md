# 开发说明

## 目录

`src/game2apk/` 是领域服务层。`inspector.py` 只读识别 MV；`staging.py` 复制并保护源；`patcher.py` 注入唯一输入点；`translation.py` 做安全字段提取、DeepSeek transport、缓存和应用；`builder.py` 做 SDK/JDK/Gradle 发现、模板渲染和 ASCII 路径映射；`signing.py` 管理 per-applicationId 密钥；`verifier.py` 做静态 APK/可选 adb 验收；`pipeline.py` 是 GUI/CLI 共用门面。

## 写权限和不变量

本任务只写 `game2apk-tool` 非模板部分。不要修改 `game2apk-tool/templates/android-rpgmv/`，不要把原游戏 `www` 或旧 `android` 作为输出目录。所有工作目录必须能向上找到 `.game2apk-work-marker.json`，删除还要匹配 project id。

所有 subprocess 均使用参数数组、`shell=False`；Gradle wrapper 的 `.bat` 通过 `[COMSPEC, '/d', '/c', ...]` 启动。日志写入前运行脱敏。长任务通过 progress callback 和 `threading.Event` 取消；GUI 只在后台线程调用服务，Tk 主线程通过 queue 更新界面。

## 模板集成假设

当前模板契约是：

1. `gradlew.bat`/`gradlew` 位于模板根目录。
2. app module 位于 `app/`，资产目录为 `app/src/main/assets/www`。
3. `MainActivity` 从 `game2apk/config.json` 读取 schemaVersion 1 的顶层配置。
4. `app/build.gradle` 通过 `game2apkApplicationId`、`game2apkVersionCode` 和 `game2apkVersionName` Gradle properties 接收应用标识，release 已明确 `debuggable false`，并有 Android 资源 `noCompress` 扩展名配置。
5. 输入桥由模板的 Java 代码通过 WebView `evaluateJavascript` 调用；Windows 侧只负责把 `game2apk-input.js` 放到 `assets/www`。

构建器在副本中复制 `www` 和 `assets/game2apk/config.json`，会忽略模板的 `.gradle`、`.gradle-home`、`build`、`dist`、keystore 和 APK 文件，防止旧产物混入。暂存 `www` 的保守估算接近 ZIP32 4 GiB 边界时，`resource_pack.py` 改为生成 ZIP64 `*-resources.g2ares`，APK 只保留模板运行时，并把 `assets/game2apk/resource-pack.json` 写入 APK。Android `ResourcePackPathHandler` 通过 `WebViewAssetLoader` 从应用专属外部目录按需读取 `www/*`，不把多 GB 资源一次性加载到内存；`verifier.py` 同时校验 APK 内元数据和外部包清单。

## 高级作弊变量选择契约

检查任务的 `result.cheatCatalog` 只公开 `data/System.json` 中前 256 个非空变量的稳定 ID 和标签，ID 格式为 `variable:N`。`POST /api/cheat-catalog` 使用与构建相同的 DeepSeek 思考设置，在一次性的 `System.json` 副本中翻译标签，返回 `status: ready` 的同一组 ID；源游戏文件不会被写入，翻译缓存可供之后的正式构建复用。

`POST /api/build` 接受 `advancedCheatVariableIds`。省略或传 `null` 表示兼容旧版行为——显示全部可发现变量；显式 `[]` 表示不显示任何高级数值变量。其他数组会去重并按变量编号排序，在 patch 阶段还必须属于暂存 `System.json` 的前 256 个非空变量，否则拒绝构建。开关目录不受该字段影响。选择会进入 prepared-stage resume key，变更选择不会复用旧的注入结果。

## 测试策略

优先运行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\game2apk-tool\src).Path
python -m unittest discover -s .\game2apk-tool\tests -p 'test_*.py' -v
```

测试不复制真实 1.221 GiB 游戏。`test_build_verify_fixture_end_to_end_without_real_gradle` 用临时 Android fixture 和假的 Gradle runner，验证 `inspect → stage → patch → build → verify` 领域链；真实 Gradle 可用时，再用小 fixture 手工运行模板 wrapper。真实目标 APK、设备输入、音频、加密资源和存档回归属于后续集成/设备任务。

## 便携构建

`scripts/game2apk.spec` 只收集 Python 标准库应用和 Tkinter GUI；`scripts/build-portable.ps1` 先运行单元测试，再调用 PyInstaller 生成目录。构建产物不把 `.state`、`.work`、模板资产、游戏目录、签名材料或环境变量复制进去。
