# 桌面版工具链说明

Windows Release 不包含 Android SDK、JDK、Gradle 缓存、签名材料或原游戏资源，因此发布包体积小且不会携带用户数据。

启动时只做本地检查。若电脑已经安装 Android Studio/SDK，工具会优先读取 `ANDROID_SDK_ROOT`、`ANDROID_HOME`、`JAVA_HOME`、PATH，以及常见的 `%LOCALAPPDATA%\Android\Sdk` 路径；不需要重复安装。用户也可以在工具链卡片中手动选择 SDK、JDK 和 Gradle 用户目录，配置保存到当前 Windows 用户的 `%APPDATA%\game2apk-tool\toolchain.json`，不会写入仓库，也不会保存 API Key 或签名密码。

缺少组件时，用户可以明确确认后从官方 HTTPS 地址下载 Android Command-line Tools 或 Temurin JDK 17，并选择安装目录。Command-line Tools 只是提供 `sdkmanager`，下载后仍需用户在选定 SDK 目录安装项目需要的 Android platform、build-tools 和 platform-tools（也可以使用 Android Studio 完成），工具不会静默接受许可证或安装额外组件。下载失败时可改用手动路径配置；命令行入口仍可使用 `game2apk-tool.exe --cli ...`。
