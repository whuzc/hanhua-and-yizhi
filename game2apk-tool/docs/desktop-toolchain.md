# 桌面版工具链说明

Windows Release 不包含 Android SDK、JDK、Gradle 缓存、签名材料或原游戏资源，因此发布包体积小且不会携带用户数据。

启动时只做本地检查。若电脑已经安装 Android Studio/SDK，工具会优先读取 `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME`、PATH，以及常见的 `%LOCALAPPDATA%\Android\Sdk` 路径；不需要重复安装。用户也可以在工具链卡片中手动选择 SDK、JDK 和 Gradle 用户目录，配置保存到当前 Windows 用户的 `%APPDATA%\game2apk-tool\toolchain.json`，不会写入仓库，也不会保存 API Key 或签名密码。

缺少组件时，用户可以明确确认后从官方 HTTPS 地址下载 Android Command-line Tools 或 Temurin JDK 17，并选择安装目录。Command-line Tools 只是提供 `sdkmanager`，下载后仍需用户在选定 SDK 目录安装项目需要的 Android platform、build-tools 和 platform-tools（也可以使用 Android Studio 完成），工具不会静默接受许可证或安装额外组件。下载失败时可改用手动路径配置；命令行入口仍可使用 `game2apk-tool.exe --cli ...`。

## Gradle 缓存的范围与清理策略

界面中的“Gradle 用户缓存”是 `GRADLE_USER_HOME`，默认位于当前用户的 `%APPDATA%\game2apk-tool\gradle-home`（也可以手动指定）。它是用户级、跨项目共用的 Gradle User Home，不属于某一个游戏；里面包含 wrapper 分发包、依赖、插件和日志等可再生内容。后续迁移其他游戏时复用它可以避免重复下载。

因此构建完成后不会自动删除这个目录。Gradle 自身也会按版本和最近使用时间做后台清理；只有磁盘空间紧张、缓存损坏或需要强制重新下载时，才建议在关闭构建进程后手动清理，下一次构建可能需要重新联网下载。

每次构建的项目暂存目录和没有外部工具链时使用的 `.work` 临时 Gradle 副本与该共享缓存不同；它们属于工具可再生的项目级产物，不会进入 portable 或 Git 仓库。确认不再需要报告和日志后，可以单独清理 `.work`；不要把 `.state`、签名状态、存档或原游戏目录当作 Gradle 缓存删除。
