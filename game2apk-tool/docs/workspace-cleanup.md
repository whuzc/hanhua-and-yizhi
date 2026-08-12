# 构建空间与中间副本

工具不会把 Gradle 用户缓存按游戏复制。`GRADLE_USER_HOME` 是跨项目共用的依赖缓存，保留它可以让后续游戏复用 Gradle wrapper、插件和 Maven 依赖。

每个游戏 run 在 `.work/<project-id>/runs/<run-id>/` 下有两类内容：

- `staged/www`：带补丁、翻译和断点信息的暂存副本；构建失败或取消时会保留它，下一次相同配置可以续做。
- `android`、`resource-pack`：本次构建生成的 Android 工程和待发布资源包，均可再生。

签名、静态验收通过并复制到 `dist` 后，工具会自动删除该 run 的 `staged`、`android` 和 `resource-pack`，只留下 `stage-manifest.json`、日志、签名报告和验收报告等小型审计文件。这样最终只保留原游戏目录和 `dist` 中的交付物；APK 或 `.g2ares` 内含游戏资源，是必须保留的最终产物。

构建失败或取消时，工具只删除 `android` 和未发布的 `resource-pack`，保留 `staged/www` 作为断点检查点。若 Windows 仍有文件被占用，日志会显示清理警告；关闭 Gradle、Java 或文件预览进程后可以安全重试。

旧版本已经留下的 `.work` run 不会被新版本猜测性删除。确认不再需要旧日志和检查点后，可在工具关闭、没有 Gradle/Java 进程占用时删除对应的 `.work/<project-id>`；不要删除 `.state`、签名状态、存档或原游戏目录。Gradle 缓存只有在磁盘紧张或损坏时才建议手动清理。
